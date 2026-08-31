"""Was alle Wege brauchen: Pfade, Sitzung, Zugangsprüfungen.

Bewusst ohne Endpunkte. Dieses Modul steht unter allen anderen und darf
deshalb nichts aus ihnen importieren — sonst entstünde ein Ring.

Die Zugangsprüfungen bauen aufeinander auf:

``angemeldet`` → gültige Sitzung
``freigegeben`` → zusätzlich freigeschaltetes Konto
``verwalter`` → zusätzlich Admin
``mandant`` → Datenverzeichnis samt Datenschlüssel dieser Anfrage
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, HTTPException, Request, Response

from . import konten
from .konten import Nutzer

protokoll = logging.getLogger("rechnungsblatt")

DATEN = Path(os.environ.get("DATEN_VERZEICHNIS", "/daten"))
_WEB_WURZEL = Path(__file__).resolve().parents[2]  # …/web
SEITEN = Path(__file__).resolve().parent / "seiten"
ZONEN_EDITOR = _WEB_WURZEL / "zonen-editor"

PLAUSIBLE_URL = os.environ.get("PLAUSIBLE_URL", "").rstrip("/")
PLAUSIBLE_DOMAIN = os.environ.get("PLAUSIBLE_DOMAIN", "")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SITZUNG_COOKIE = "rb_sitzung"
# Nur für die lokale Entwicklung: den Sitzungsschlüssel auch aus einer
# Kopfzeile lesen. iOS leert bei Web-Apps über HTTP den Cookie-Speicher
# beim Schließen — im Portainer-Stack (HTTPS) ist das nicht nötig und
# bleibt deshalb aus.
SITZUNG_KOPFZEILE = os.environ.get("SITZUNG_KOPFZEILE", "") == "1"

# Wiederherstellungscodes zwischen Registrierung und Bestätigung.
# Bewusst nur im Speicher: Der Code darf nirgends abgelegt werden, sonst
# wäre der ganze Aufwand umsonst. Startet der Dienst dazwischen neu, ist
# er weg — dann hilft „neuen Code erzeugen" im Konto.
SPAETER: dict[int, str] = {}


def sitzungsschluessel(anfrage: Request) -> str | None:
    """Der Sitzungsschlüssel aus Cookie oder Ersatzkopfzeile.

    Eine Stelle statt drei: Vorher stand dieselbe Abfrage in
    ``_angemeldeter``, in ``mandant`` und beim Abmelden — wer den
    Ersatzweg ändern wollte, musste alle drei finden.
    """
    schluessel = anfrage.cookies.get(SITZUNG_COOKIE)
    if not schluessel and SITZUNG_KOPFZEILE:
        # Ersatzweg, wenn der Browser das Cookie verworfen hat.
        schluessel = anfrage.headers.get("X-Rb-Sitzung")
    return schluessel


def angemeldeter(anfrage: Request) -> Nutzer | None:
    """Der angemeldete Nutzer — oder None. Wirft nicht."""
    return konten.nutzer_zu_sitzung(sitzungsschluessel(anfrage))


def angemeldet(anfrage: Request) -> Nutzer:
    """Abhängigkeit für JSON-Endpunkte: 401, wenn keine gültige Sitzung."""
    person = angemeldeter(anfrage)
    if person is None:
        raise HTTPException(401, detail={"grund": "Bitte zuerst anmelden."})
    return person


def freigegeben(person: Nutzer = Depends(angemeldet)) -> Nutzer:
    """Wie `angemeldet`, verlangt aber ein freigeschaltetes Konto."""
    if person.status == konten.STATUS_WARTET:
        raise HTTPException(
            403,
            detail={
                "code": "wartet_auf_freigabe",
                "grund": "Ihr Konto wartet noch auf die Freigabe.",
            },
        )
    if person.status == konten.STATUS_GESPERRT:
        raise HTTPException(
            403, detail={"code": "gesperrt", "grund": "Ihr Konto ist gesperrt."}
        )
    return person


def verwalter(person: Nutzer = Depends(angemeldet)) -> Nutzer:
    if not person.ist_admin:
        raise HTTPException(403, detail={"grund": "Dieser Bereich ist Admins vorbehalten."})
    return person


def datenverzeichnis() -> Path:
    """Wo die Mandantendaten liegen.

    Als Funktion und nicht als Konstante gelesen: Die Tests hängen
    ``DATEN`` zur Laufzeit auf ein Wegwerfverzeichnis um. Läse jedes Modul
    seine eigene importierte Kopie, ginge das Umhängen ins Leere — und die
    Tests schrieben in das echte Datenverzeichnis, ohne dass es auffällt.
    """
    from . import main                    # erst hier: main braucht basis

    return getattr(main, "DATEN", DATEN)


def wurzel_von(person: Nutzer) -> Path:
    """Datenverzeichnis eines Mandanten."""
    return datenverzeichnis() / "nutzer" / str(person.id)


def mandant(anfrage: Request, person: Nutzer = Depends(freigegeben)) -> Path:
    """Datenverzeichnis des Mandanten — und sein Schlüssel für diese Anfrage.

    Der Datenschlüssel liegt verpackt in der Sitzung und lässt sich nur mit
    dem Sitzungsschlüssel aus dem Cookie öffnen. Er hängt am gelieferten
    Pfadobjekt (siehe ``ablage.Mandantenpfad``), damit ihn jede
    Hilfsfunktion findet, ohne dass er durchgereicht werden muss.
    """
    from .ablage import Mandantenpfad     # erst hier: ablage braucht basis

    wurzel = Mandantenpfad(wurzel_von(person))
    wurzel.mkdir(parents=True, exist_ok=True)
    wurzel.schluessel = konten.datenschluessel_der_sitzung(
        sitzungsschluessel(anfrage))
    return wurzel


def setze_sitzungscookie(antwort: Response, schluessel: str,
                         anfrage: Request) -> None:
    antwort.set_cookie(
        SITZUNG_COOKIE,
        schluessel,
        max_age=konten.SITZUNG_TAGE * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=anfrage.url.scheme == "https",
        path="/",
    )


def oeffentliche_adresse(anfrage: Request) -> str:
    """Die Adresse, unter der die Seite von außen erreichbar ist.

    Zuerst der Eintrag aus der Verwaltung: Hinter einem Reverse Proxy
    stimmt das, was die Anfrage sagt, oft nicht mit dem überein, was der
    Kunde im Browser sieht — und ein Rücksetz-Link auf die falsche
    Adresse ist wertlos.
    """
    try:
        eingetragen = (konten.einstellungen().get("oeffentliche_adresse") or "").strip()
    except Exception:
        protokoll.exception("Öffentliche Adresse nicht lesbar")
        eingetragen = ""
    if eingetragen:
        return eingetragen.rstrip("/")
    return str(anfrage.base_url).rstrip("/")
