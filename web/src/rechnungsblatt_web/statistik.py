"""Besucherzahlen aus Plausible — für den Adminbereich.

Gezählt wird schon lange: Jede Seite trägt das Plausible-Skript. Die Zahlen
lagen aber nur in Plausible selbst. Dieses Modul holt sie über die Stats-API
zurück, damit der Betrieb an einer Stelle sichtbar ist — Besucher neben
Konten und Belegen.

**Zählen und Auswerten sind getrennt.** Zum Zählen genügen Adresse und
Domain; zum *Lesen* braucht es zusätzlich einen API-Schlüssel (in Plausible
unter Settings → API Keys). Fehlt er, zählt die Seite unverändert weiter —
nur die Auswertung im Adminbereich bleibt leer. Das ist der übliche Zustand
nach einer frischen Einrichtung und deshalb kein Fehler, sondern ein
Hinweis.

Die Fragen gehen an ``/api/v2/query``. Die ältere ``/api/v1/stats`` gibt es
noch, sie kann aber keine mehrfachen Kennzahlen in einem Aufruf.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
import zoneinfo

import httpx

from . import konten

protokoll = logging.getLogger("rechnungsblatt.statistik")


class StatistikFehler(Exception):
    """Abruf fehlgeschlagen — die Meldung ist für den Betreiber bestimmt."""


# Plausible erlaubt 600 Anfragen je Stunde. Die Übersicht stellt sechs
# Fragen auf einmal; ohne Zwischenspeicher wäre das Kontingent nach hundert
# Seitenaufrufen erschöpft.
_FRISCHE_S = 60
_zwischenspeicher: dict[str, tuple[float, dict]] = {}
_riegel = threading.Lock()

# Die Zeiträume, die die Oberfläche anbietet. Als Tage und nicht als
# Plausible-Kürzel („30d"): Deren Bedeutung schwankt zwischen den Fassungen
# — mal mit heutigem Tag, mal ohne.
ZEITRAEUME = {"7t": 7, "30t": 30, "90t": 90, "365t": 365}
_ZEITZONE = zoneinfo.ZoneInfo("Europe/Berlin")


def zugang() -> tuple[str, str, str] | None:
    """Adresse, Domain und Schlüssel — oder None, wenn etwas fehlt.

    Alles oder nichts: Mit halber Angabe liefe jede Abfrage in einen 401,
    und die Oberfläche zeigte „keine Daten" statt „nicht eingerichtet".
    """
    werte = konten.einstellungen(mit_geheimnissen=True)
    adresse = (werte.get("plausible_url") or "").strip().rstrip("/")
    domain = (werte.get("plausible_domain") or "").strip()
    schluessel = (werte.get("plausible_api_key") or "").strip()
    if not (adresse and domain and schluessel):
        return None
    return adresse, domain, schluessel


def _spanne(tage: int) -> list[str]:
    """Von-bis als zwei Datumsangaben.

    In deutscher Zeit gerechnet, nicht in UTC: Der Container läuft auf UTC,
    und bis zwei Uhr nachts endete der Verlauf sonst einen Tag zu früh.
    """
    heute = dt.datetime.now(_ZEITZONE).date()
    return [(heute - dt.timedelta(days=tage - 1)).isoformat(), heute.isoformat()]


def _frage(adresse: str, domain: str, schluessel: str,
           spanne: list[str], abfrage: dict) -> dict:
    """Eine Frage an die Stats-API, mit Zwischenspeicher."""
    koerper = {"site_id": domain, "date_range": spanne, **abfrage}
    kennung = json.dumps(koerper, sort_keys=True)

    with _riegel:
        bekannt = _zwischenspeicher.get(kennung)
        if bekannt and time.monotonic() - bekannt[0] < _FRISCHE_S:
            return bekannt[1]

    try:
        antwort = httpx.post(
            f"{adresse}/api/v2/query",
            headers={"Authorization": f"Bearer {schluessel}"},
            json=koerper,
            timeout=10.0,
        )
    except httpx.HTTPError as fehler:
        raise StatistikFehler(f"Plausible nicht erreichbar: {fehler}") from fehler
    if antwort.status_code == 401:
        raise StatistikFehler(
            "Plausible weist den Schlüssel ab (401). Stimmt der API-Schlüssel?"
        )
    if antwort.status_code >= 400:
        raise StatistikFehler(
            f"Plausible antwortet mit {antwort.status_code}: "
            f"{antwort.text[:200]}"
        )
    daten = antwort.json()

    with _riegel:
        # Ab hundert Einträgen die abgelaufenen wegräumen: Der Speicher
        # wächst sonst mit jeder neuen Frage-Signatur.
        if len(_zwischenspeicher) > 100:
            jetzt = time.monotonic()
            for alt in [k for k, (t, _) in _zwischenspeicher.items()
                        if jetzt - t >= _FRISCHE_S]:
                _zwischenspeicher.pop(alt, None)
        _zwischenspeicher[kennung] = (time.monotonic(), daten)
    return daten


def _zahl(wert) -> float:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return 0.0


def _liste(antwort: dict) -> list[dict]:
    """Eine Aufschlüsselung als Name/Zahl-Paare."""
    return [
        {"name": (zeile.get("dimensions") or [""])[0] or "—",
         "besucher": int(_zahl((zeile.get("metrics") or [0])[0]))}
        for zeile in antwort.get("results", [])
    ]


def _verlauf(antwort: dict) -> list[dict]:
    """Besucher je Tag — mit den Lücken, die Plausible auslässt.

    Die API liefert nur Tage mit Ereignissen. ``time_labels`` gibt das
    vollständige Raster; ohne sie hätte ein besucherloser Tag gar keinen
    Balken und der Verlauf wäre gestaucht.
    """
    gemessen = {
        (zeile.get("dimensions") or [""])[0]:
            int(_zahl((zeile.get("metrics") or [0])[0]))
        for zeile in antwort.get("results", [])
    }
    marken = (antwort.get("meta") or {}).get("time_labels")
    if marken:
        return [{"tag": tag, "besucher": gemessen.get(tag, 0)} for tag in marken]
    return [{"tag": tag, "besucher": zahl} for tag, zahl in gemessen.items()]


def auswertung(zeitraum: str = "30t") -> dict:
    """Die Zahlen für den Adminbereich. Wirft StatistikFehler."""
    daten = zugang()
    if daten is None:
        raise StatistikFehler(
            "Kein Plausible-Zugang hinterlegt (Adminbereich → Besucher)."
        )
    adresse, domain, schluessel = daten
    tage = ZEITRAEUME.get(zeitraum, 30)
    spanne = _spanne(tage)

    def frage(abfrage: dict) -> dict:
        return _frage(adresse, domain, schluessel, spanne, abfrage)

    gesamt = frage({
        "metrics": ["visitors", "pageviews", "bounce_rate", "visit_duration"],
    })
    verlauf = frage({
        "metrics": ["visitors"],
        "dimensions": ["time:day"],
        "include": {"time_labels": True},
        "pagination": {"limit": 400},
    })
    seiten = frage({
        "metrics": ["visitors"], "dimensions": ["event:page"],
        "order_by": [["visitors", "desc"]], "pagination": {"limit": 10},
    })
    quellen = frage({
        "metrics": ["visitors"], "dimensions": ["visit:source"],
        "order_by": [["visitors", "desc"]], "pagination": {"limit": 10},
    })
    laender = frage({
        "metrics": ["visitors"], "dimensions": ["visit:country_name"],
        "order_by": [["visitors", "desc"]], "pagination": {"limit": 10},
    })
    geraete = frage({
        "metrics": ["visitors"], "dimensions": ["visit:device"],
        "order_by": [["visitors", "desc"]], "pagination": {"limit": 5},
    })

    werte = (gesamt.get("results") or [{}])[0].get("metrics") or [0, 0, 0, 0]
    return {
        "zeitraum": zeitraum,
        "von": spanne[0],
        "bis": spanne[1],
        "besucher": int(_zahl(werte[0])),
        "aufrufe": int(_zahl(werte[1])),
        # Plausible nennt das „bounce rate". „Nur eine Seite gesehen" sagt
        # dasselbe, ohne Marketingvokabular.
        "nur_eine_seite": int(_zahl(werte[2])),
        "verweildauer_s": int(_zahl(werte[3])),
        "verlauf": _verlauf(verlauf),
        "seiten": _liste(seiten),
        "quellen": _liste(quellen),
        "laender": _liste(laender),
        "geraete": _liste(geraete),
    }
