"""Bestätigungsabfrage der USt-IdNr. über MIAS/VIES.

**Warum überhaupt.** Kein Muster der Welt beweist, dass es eine Nummer
gibt und sie dem Kunden gehört. Für Reverse Charge und
innergemeinschaftliche Lieferungen ist ihre **Gültigkeit** materielle
Voraussetzung; was den Rechnungssteller im Streitfall schützt, ist die
dokumentierte Abfrage, nicht ein Formatcheck.

**Die Falle, die diesen Weg gefährlich macht.** VIES antwortet auf eine
Anfrage, die es nicht beantworten konnte, mit ``isValid: false`` — genau
wie auf eine ungültige Nummer. Am 10.09.2026 gemessen:

    erfundene Nummer  DE123456789   isValid=false  userError=INVALID
    echte Nummer      FR53987550159 isValid=false  userError=MS_MAX_CONCURRENT_REQ

Frankreich drosselte in dem Moment. Wer nur ``isValid`` liest, erklärt
eine gültige Nummer für ungültig und schreckt einen Kunden davon ab, eine
richtige Rechnung zu schreiben. **Deshalb entscheidet hier ausschließlich
``userError``**, und alles, was nicht ausdrücklich ``VALID`` oder
``INVALID`` heißt, gilt als *unbekannt*.

**Blockieren darf das nie.** Der Dienst ist notorisch wackelig, und ein
Kunde, der freitagnachmittags nicht abrechnen kann, weil in Brüssel ein
Server hustet, hat ein schlimmeres Problem als eine ungeprüfte Nummer.
Die Abfrage läuft deshalb **auf Knopfdruck** und mit harter Zeitgrenze;
das Erzeugen einer Rechnung ruft sie **nicht** auf — es schreibt nur das
zuletzt gespeicherte Ergebnis ins Belegprotokoll.
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx

from rechnungsblatt_kern import laender

protokoll = logging.getLogger("rechnungsblatt.ustid")

#: Die Bestätigungsschnittstelle der Kommission.
ENDPUNKT = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{ms}/vat/{nummer}"

#: Harte Grenze. Lieber "unbekannt" nach sechs Sekunden als ein Kunde,
#: der auf einen fremden Server wartet.
ZEITGRENZE = 6.0

GUELTIG = "gueltig"
UNGUELTIG = "ungueltig"
UNBEKANNT = "unbekannt"


def zerlege(nummer: str, land: str) -> tuple[str, str] | None:
    """Zerlegt eine Nummer in Mitgliedstaat und Ziffernteil.

    VIES will beides getrennt und kennt Griechenland als ``EL``, nicht als
    ``GR`` — dieselbe Eigenheit wie in der Ländertabelle.
    """
    sauber = laender.normalisiere_nummer(nummer)
    erlaubt = laender.erlaubte_praefixe(land)
    if not sauber or len(sauber) < 3:
        return None
    praefix = sauber[:2]
    if erlaubt and praefix not in erlaubt:
        return None
    if not laender.ist_eu(land):
        # Drittländer führen keine USt-IdNr.; VIES kennt sie nicht.
        return None
    return praefix, sauber[2:]


def pruefe(nummer: str, land: str, zeitgrenze: float = ZEITGRENZE) -> dict:
    """Fragt VIES und liefert immer ein Ergebnis — auch wenn es schweigt."""
    zeitpunkt = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    zerlegt = zerlege(nummer, land)
    if zerlegt is None:
        return {
            "stand": UNBEKANNT,
            "grund": "keine EU-Nummer",
            "nummer": laender.normalisiere_nummer(nummer),
            "zeitpunkt": zeitpunkt,
        }
    ms, ziffern = zerlegt
    ergebnis = {
        "stand": UNBEKANNT,
        "grund": "",
        "nummer": ms + ziffern,
        "zeitpunkt": zeitpunkt,
        "name": "",
        "anschrift": "",
    }
    try:
        antwort = httpx.get(
            ENDPUNKT.format(ms=ms, nummer=ziffern),
            timeout=zeitgrenze,
            headers={"Accept": "application/json"},
        )
        antwort.raise_for_status()
        daten = antwort.json()
    except (httpx.HTTPError, ValueError) as fehler:
        protokoll.info("VIES nicht erreichbar: %s", fehler)
        ergebnis["grund"] = "nicht erreichbar"
        return ergebnis

    # NUR userError entscheidet -- siehe Modulkopf.
    kennung = (daten.get("userError") or "").strip().upper()
    if kennung == "VALID" or (not kennung and daten.get("isValid") is True):
        ergebnis["stand"] = GUELTIG
    elif kennung == "INVALID":
        ergebnis["stand"] = UNGUELTIG
    else:
        ergebnis["grund"] = kennung or "ohne Angabe"

    for feld, quelle in (("name", "name"), ("anschrift", "address")):
        wert = (daten.get(quelle) or "").strip()
        # VIES setzt "---", wo der Mitgliedstaat nichts herausgibt.
        ergebnis[feld] = "" if wert in ("", "---") else wert
    if daten.get("requestDate"):
        ergebnis["zeitpunkt"] = str(daten["requestDate"])
    return ergebnis
