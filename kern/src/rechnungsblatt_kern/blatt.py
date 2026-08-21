"""Blatt-Rendering: der Rechnungsinhalt, gerendert in die Schreibzone.

Das Blatt ist ein einseitiges A4-Overlay (reportlab), das später per pikepdf
über das normalisierte Briefpapier gelegt wird. Gerendert wird ausschließlich
zwischen Kopf-Ende und Fuß-Beginn der :class:`Schreibzone`.

PDF/A verlangt eingebettete Schriften — Base-14-Schriften (Helvetica & Co.)
sind darum tabu. Es werden TTF-Schriften (Liberation/DejaVu) registriert und
eingebettet; ohne auffindbare Schrift bricht das Rendering ab.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .modell import Rechnung, Schreibzone, Stammdaten
from .summen import Summen

_SCHRIFT_KANDIDATEN: tuple[tuple[str, str], ...] = (
    (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
)

_RAND_LINKS = 20 * mm
_RAND_RECHTS = 20 * mm

# Anzeige gängiger UN/ECE-Rec-20-Einheitencodes auf dem Blatt
EINHEITEN_ANZEIGE = {
    "C62": "Stk.",
    "HUR": "Std.",
    "DAY": "Tage",
    "MTR": "m",
    "MTK": "m²",
    "KGM": "kg",
    "LTR": "l",
    "P1": "%",
}


class BlattUeberlauf(Exception):
    """Der Inhalt passt nicht in die Schreibzone."""


class SchriftNichtGefunden(Exception):
    """Keine einbettbare TTF-Schrift gefunden."""


@dataclass(frozen=True)
class Schriften:
    normal: str
    fett: str


def registriere_schriften(
    normal_pfad: str | None = None, fett_pfad: str | None = None
) -> Schriften:
    """Registriert einbettbare TTF-Schriften; sucht bekannte Systempfade ab."""
    kandidaten = _SCHRIFT_KANDIDATEN
    if normal_pfad and fett_pfad:
        kandidaten = ((normal_pfad, fett_pfad),)
    for normal, fett in kandidaten:
        if Path(normal).exists() and Path(fett).exists():
            pdfmetrics.registerFont(TTFont("RB", normal))
            pdfmetrics.registerFont(TTFont("RB-Bold", fett))
            return Schriften(normal="RB", fett="RB-Bold")
    raise SchriftNichtGefunden(
        "Keine einbettbare TTF-Schrift gefunden (Liberation oder DejaVu erwartet). "
        "PDF/A verlangt eingebettete Schriften — Base-14 ist keine Option."
    )


def format_betrag(wert: Decimal, waehrung: str = "EUR") -> str:
    """Deutsches Zahlenformat: 1.234,56 €"""
    vorzeichen = "-" if wert < 0 else ""
    betrag = abs(wert)
    ganz, komma = f"{betrag:.2f}".split(".")
    gruppen = []
    while len(ganz) > 3:
        gruppen.insert(0, ganz[-3:])
        ganz = ganz[:-3]
    gruppen.insert(0, ganz)
    symbol = "€" if waehrung == "EUR" else waehrung
    return f"{vorzeichen}{'.'.join(gruppen)},{komma} {symbol}"


def format_menge(wert: Decimal) -> str:
    text = format(wert.normalize(), "f")
    return text.replace(".", ",")


def rendere_blatt(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    summen: Summen,
    zone: Schreibzone,
    schriften: Schriften | None = None,
) -> bytes:
    """Rendert das einseitige Overlay-PDF und liefert es als Bytes."""
    schriften = schriften or registriere_schriften()
    breite, hoehe = A4
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=A4)
    c.setFillColorRGB(0, 0, 0)

    oben = hoehe - zone.kopf_ende_mm * mm  # oberste beschreibbare Y-Koordinate
    unten = zone.fuss_beginn_mm * mm  # unterste beschreibbare Y-Koordinate
    rechts = breite - _RAND_RECHTS

    y = oben - 6 * mm

    # Absenderzeile über dem Empfängerfeld (Fensterkuvert-Konvention)
    anschrift = stammdaten.anschrift
    c.setFont(schriften.normal, 8)
    c.drawString(
        _RAND_LINKS,
        y,
        f"{stammdaten.firmierung} · {anschrift.strasse} · {anschrift.plz} {anschrift.ort}",
    )
    y -= 8 * mm

    # Empfängerblock links, Belegdaten rechts
    empfaenger = rechnung.empfaenger
    empfaenger_zeilen = [
        empfaenger.name,
        empfaenger.anschrift.strasse,
        f"{empfaenger.anschrift.plz} {empfaenger.anschrift.ort}",
    ]
    if empfaenger.anschrift.land != "DE":
        empfaenger_zeilen.append(empfaenger.anschrift.land)
    c.setFont(schriften.normal, 10)
    block_y = y
    for zeile in empfaenger_zeilen:
        c.drawString(_RAND_LINKS, block_y, zeile)
        block_y -= 5 * mm

    belegdaten = [
        ("Nummer", rechnung.nummer),
        ("Datum", rechnung.rechnungsdatum.strftime("%d.%m.%Y")),
    ]
    if rechnung.leistungsdatum:
        belegdaten.append(("Leistungsdatum", rechnung.leistungsdatum.strftime("%d.%m.%Y")))
    if rechnung.leistungszeitraum:
        zeitraum = rechnung.leistungszeitraum
        belegdaten.append(
            (
                "Leistungszeitraum",
                f"{zeitraum.von.strftime('%d.%m.%Y')} – {zeitraum.bis.strftime('%d.%m.%Y')}",
            )
        )
    if stammdaten.steuernummer:
        belegdaten.append(("Steuernummer", stammdaten.steuernummer))
    if stammdaten.ust_idnr:
        belegdaten.append(("USt-IdNr.", stammdaten.ust_idnr))
    if rechnung.bezugs_nummer:
        belegdaten.append(("Zu Rechnung", rechnung.bezugs_nummer))
    c.setFont(schriften.normal, 9)
    daten_y = y
    for beschriftung, wert in belegdaten:
        c.drawString(120 * mm, daten_y, f"{beschriftung}:")
        c.drawRightString(rechts, daten_y, wert)
        daten_y -= 5 * mm

    y = min(block_y, daten_y) - 10 * mm

    # Titel
    c.setFont(schriften.fett, 14)
    c.drawString(_RAND_LINKS, y, f"{rechnung.typ.titel} {rechnung.nummer}")
    y -= 10 * mm

    # Positionstabelle
    spalten = {
        "pos": _RAND_LINKS,
        "bezeichnung": _RAND_LINKS + 10 * mm,
        "menge_r": 122 * mm,
        "einzel_r": 148 * mm,
        "steuer_r": 166 * mm,
        "summe_r": rechts,
    }
    c.setFont(schriften.fett, 9)
    c.drawString(spalten["pos"], y, "Pos.")
    c.drawString(spalten["bezeichnung"], y, "Leistung")
    c.drawRightString(spalten["menge_r"], y, "Menge")
    c.drawRightString(spalten["einzel_r"], y, "Einzelpreis")
    c.drawRightString(spalten["steuer_r"], y, "USt.")
    c.drawRightString(spalten["summe_r"], y, "Betrag")
    y -= 2 * mm
    c.line(_RAND_LINKS, y, rechts, y)
    y -= 6 * mm

    c.setFont(schriften.normal, 9)
    bezeichnung_breite = spalten["menge_r"] - 6 * mm - spalten["bezeichnung"]
    from .summen import zeilensumme

    for nummer, position in enumerate(rechnung.positionen, start=1):
        zeilen = _umbrechen(position.bezeichnung, schriften.normal, 9, bezeichnung_breite)
        if position.beschreibung:
            zeilen += _umbrechen(position.beschreibung, schriften.normal, 9, bezeichnung_breite)
        benoetigt = len(zeilen) * 4.5 * mm + 2.5 * mm
        _pruefe_platz(y - benoetigt, unten)
        c.drawString(spalten["pos"], y, str(nummer))
        c.drawRightString(
            spalten["menge_r"],
            y,
            f"{format_menge(position.menge)} {EINHEITEN_ANZEIGE.get(position.einheit, position.einheit)}",
        )
        c.drawRightString(spalten["einzel_r"], y, format_betrag(position.einzelpreis, rechnung.waehrung))
        c.drawRightString(spalten["steuer_r"], y, f"{position.steuer.satz:.0f} %")
        c.drawRightString(spalten["summe_r"], y, format_betrag(zeilensumme(position), rechnung.waehrung))
        for zeile in zeilen:
            c.drawString(spalten["bezeichnung"], y, zeile)
            y -= 4.5 * mm
        y -= 2.5 * mm

    y -= 2 * mm
    c.line(110 * mm, y, rechts, y)
    y -= 6 * mm

    # Summenblock
    def summenzeile(beschriftung: str, wert: Decimal, fett: bool = False) -> None:
        nonlocal y
        _pruefe_platz(y, unten)
        c.setFont(schriften.fett if fett else schriften.normal, 10 if fett else 9)
        c.drawRightString(166 * mm, y, beschriftung)
        c.drawRightString(spalten["summe_r"], y, format_betrag(wert, rechnung.waehrung))
        y -= 5 * mm

    summenzeile("Zwischensumme (netto)", summen.zeilensumme)
    if summen.rabatt > 0:
        summenzeile(rechnung.rabatt_grund, -summen.rabatt)
        summenzeile("Nettobetrag", summen.steuerbasis)
    for korb in summen.koerbe:
        if not korb.kategorie.befreit:
            summenzeile(
                f"USt. {korb.kategorie.satz:.0f} % auf {format_betrag(korb.basis, rechnung.waehrung)}",
                korb.steuer,
            )
    y -= 1 * mm
    summenzeile("Gesamtbetrag", summen.brutto, fett=True)
    y -= 6 * mm

    # Hinweise: Steuerbefreiungen, Zahlungsziel, Freitext
    c.setFont(schriften.normal, 9)
    text_breite = rechts - _RAND_LINKS
    hinweise: list[str] = []
    for korb in summen.koerbe:
        if korb.kategorie.hinweis:
            hinweise.append(korb.kategorie.hinweis)
    if rechnung.faelligkeit:
        hinweise.append(f"Zahlbar ohne Abzug bis {rechnung.faelligkeit.strftime('%d.%m.%Y')}.")
    else:
        hinweise.append(
            f"Zahlbar innerhalb von {stammdaten.zahlungsziel_tage} Tagen ohne Abzug."
        )
    iban = _gruppiere_iban(stammdaten.iban)
    bankzeile = f"Bankverbindung: IBAN {iban}"
    if stammdaten.bic:
        bankzeile += f" · BIC {stammdaten.bic}"
    hinweise.append(bankzeile)
    if rechnung.freitext:
        hinweise.append(rechnung.freitext)

    for hinweis in hinweise:
        for zeile in _umbrechen(hinweis, schriften.normal, 9, text_breite):
            _pruefe_platz(y, unten)
            c.drawString(_RAND_LINKS, y, zeile)
            y -= 4.5 * mm
        y -= 1.5 * mm

    c.showPage()
    c.save()
    return puffer.getvalue()


def _pruefe_platz(y: float, unten: float) -> None:
    if y < unten:
        raise BlattUeberlauf(
            "Der Rechnungsinhalt passt nicht in die Schreibzone. "
            "Weniger Positionen, kürzere Texte oder eine größere Zone wählen."
        )


def _umbrechen(text: str, schrift: str, groesse: float, max_breite: float) -> list[str]:
    zeilen: list[str] = []
    for absatz in text.splitlines() or [""]:
        aktuelle = ""
        for wort in absatz.split():
            probe = f"{aktuelle} {wort}".strip()
            if stringWidth(probe, schrift, groesse) <= max_breite or not aktuelle:
                aktuelle = probe
            else:
                zeilen.append(aktuelle)
                aktuelle = wort
        zeilen.append(aktuelle)
    return zeilen or [""]


def _gruppiere_iban(iban: str) -> str:
    kompakt = iban.replace(" ", "")
    return " ".join(kompakt[i : i + 4] for i in range(0, len(kompakt), 4))
