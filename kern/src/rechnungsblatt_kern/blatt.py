"""Blatt-Rendering: der Rechnungsinhalt, gerendert in die Schreibzone.

Das Blatt ist ein einseitiges A4-Overlay (reportlab), das später per pikepdf
über das normalisierte Briefpapier gelegt wird. Gerendert wird ausschließlich
zwischen Kopf-Ende und Fuß-Beginn der :class:`Schreibzone`.

Gestaltung (:class:`Blattgestaltung`): Schrift aus dem kuratierten Katalog,
Schriftgrad und eine von drei getesteten Layoutvarianten — bewusst keine
freie Positionierung. PDF/A verlangt eingebettete Schriften, darum sind
Base-14-Schriften tabu; der Katalog enthält nur mitgelieferte TTFs.
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

from .modell import (
    Blattgestaltung,
    Layoutvariante,
    Rechnung,
    Schreibzone,
    Stammdaten,
)
from .summen import Summen, zeilensumme

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


# ---------------------------------------------------------------- Katalog

@dataclass(frozen=True)
class Schriftart:
    """Eine kuratierte, mitgelieferte Schrift (Debian-Pakete, frei lizenziert)."""

    schluessel: str
    name: str
    normal_pfad: str
    fett_pfad: str

    @property
    def verfuegbar(self) -> bool:
        return Path(self.normal_pfad).exists() and Path(self.fett_pfad).exists()


_LIB = "/usr/share/fonts/truetype/liberation"
_DEJA = "/usr/share/fonts/truetype/dejavu"
_CROS = "/usr/share/fonts/truetype/crosextra"

SCHRIFTEN_KATALOG: tuple[Schriftart, ...] = (
    Schriftart(
        "liberation-sans",
        "Liberation Sans — serifenlos, neutral",
        f"{_LIB}/LiberationSans-Regular.ttf",
        f"{_LIB}/LiberationSans-Bold.ttf",
    ),
    Schriftart(
        "liberation-serif",
        "Liberation Serif — klassisch, mit Serifen",
        f"{_LIB}/LiberationSerif-Regular.ttf",
        f"{_LIB}/LiberationSerif-Bold.ttf",
    ),
    Schriftart(
        "carlito",
        "Carlito — freundlich, modern",
        f"{_CROS}/Carlito-Regular.ttf",
        f"{_CROS}/Carlito-Bold.ttf",
    ),
    Schriftart(
        "caladea",
        "Caladea — elegant, mit Serifen",
        f"{_CROS}/Caladea-Regular.ttf",
        f"{_CROS}/Caladea-Bold.ttf",
    ),
    Schriftart(
        "dejavu-sans",
        "DejaVu Sans — kräftig, technisch",
        f"{_DEJA}/DejaVuSans.ttf",
        f"{_DEJA}/DejaVuSans-Bold.ttf",
    ),
)


def verfuegbare_schriften() -> list[Schriftart]:
    """Die Katalog-Schriften, deren Dateien auf diesem System vorliegen."""
    return [schrift for schrift in SCHRIFTEN_KATALOG if schrift.verfuegbar]


def registriere_schriftart(schluessel: str) -> Schriften:
    """Registriert eine Katalog-Schrift bei reportlab (einbettbar, TTF)."""
    for schriftart in SCHRIFTEN_KATALOG:
        if schriftart.schluessel == schluessel:
            if not schriftart.verfuegbar:
                raise SchriftNichtGefunden(
                    f"Schrift {schluessel!r} ist auf diesem System nicht installiert "
                    f"({schriftart.normal_pfad})."
                )
            normal_name = f"RB:{schluessel}"
            fett_name = f"RB:{schluessel}:B"
            try:
                pdfmetrics.getFont(normal_name)
            except KeyError:
                pdfmetrics.registerFont(TTFont(normal_name, schriftart.normal_pfad))
                pdfmetrics.registerFont(TTFont(fett_name, schriftart.fett_pfad))
            return Schriften(normal=normal_name, fett=fett_name)
    raise SchriftNichtGefunden(
        f"Unbekannter Schrift-Schlüssel {schluessel!r}. Verfügbar: "
        + ", ".join(s.schluessel for s in SCHRIFTEN_KATALOG)
    )


def registriere_schriften(
    normal_pfad: str | None = None, fett_pfad: str | None = None
) -> Schriften:
    """Standard-Schriften registrieren (Katalog-Reihenfolge) bzw. eigene Pfade."""
    if normal_pfad and fett_pfad:
        if Path(normal_pfad).exists() and Path(fett_pfad).exists():
            pdfmetrics.registerFont(TTFont("RB", normal_pfad))
            pdfmetrics.registerFont(TTFont("RB-Bold", fett_pfad))
            return Schriften(normal="RB", fett="RB-Bold")
        raise SchriftNichtGefunden(f"Schriftdateien nicht gefunden: {normal_pfad}")
    for schriftart in SCHRIFTEN_KATALOG:
        if schriftart.verfuegbar:
            return registriere_schriftart(schriftart.schluessel)
    raise SchriftNichtGefunden(
        "Keine einbettbare TTF-Schrift gefunden (Liberation, Carlito, Caladea "
        "oder DejaVu erwartet). PDF/A verlangt eingebettete Schriften."
    )


# ---------------------------------------------------------------- Formatierung

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


# ---------------------------------------------------------------- Layoutmaße

@dataclass(frozen=True)
class _Masse:
    """Abgeleitete Maße einer Layoutvariante bei gegebenem Schriftgrad."""

    basis: float  # Grundschriftgröße in pt
    faktor: float  # Abstands-Multiplikator
    titel: float  # Titelgröße in pt
    meta_zeile: bool  # Belegdaten als Zeile unter dem Titel
    linie_grau: bool  # Tabellenlinien in Grau statt Schwarz
    titel_luft: float  # zusätzlicher Abstand um den Titel (mm)


def _masse(gestaltung: Blattgestaltung) -> _Masse:
    basis = gestaltung.schriftgrad.value
    if gestaltung.layout is Layoutvariante.KOMPAKT:
        return _Masse(
            basis=basis, faktor=0.85, titel=basis + 2,
            meta_zeile=True, linie_grau=False, titel_luft=0.0,
        )
    if gestaltung.layout is Layoutvariante.MODERN:
        return _Masse(
            basis=basis, faktor=1.1, titel=basis + 7,
            meta_zeile=gestaltung.belegdaten_als_zeile, linie_grau=True,
            titel_luft=3.0,
        )
    return _Masse(
        basis=basis, faktor=1.0, titel=basis + 4,
        meta_zeile=gestaltung.belegdaten_als_zeile, linie_grau=False,
        titel_luft=0.0,
    )


# ---------------------------------------------------------------- Rendering

def rendere_blatt(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    summen: Summen,
    zone: Schreibzone,
    schriften: Schriften | None = None,
    gestaltung: Blattgestaltung | None = None,
) -> bytes:
    """Rendert das einseitige Overlay-PDF und liefert es als Bytes."""
    gestaltung = gestaltung or Blattgestaltung()
    if schriften is None:
        schriften = registriere_schriftart(gestaltung.schrift)
    masse = _masse(gestaltung)
    basis = masse.basis
    hub = basis * 0.45 * masse.faktor * mm  # Zeilenhub: 4,5 mm bei 10 pt

    breite, hoehe = A4
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=A4)
    c.setFillColorRGB(0, 0, 0)

    oben = hoehe - zone.kopf_ende_mm * mm
    unten = zone.fuss_beginn_mm * mm
    rechts = breite - _RAND_RECHTS

    def linie(x1: float, y: float, x2: float, staerke: float = 0.6) -> None:
        if masse.linie_grau:
            c.setStrokeColorRGB(0.62, 0.62, 0.62)
        else:
            c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(staerke)
        c.line(x1, y, x2, y)

    y = oben - 6 * mm

    # Absenderzeile über dem Empfängerfeld (Fensterkuvert-Konvention)
    anschrift = stammdaten.anschrift
    c.setFont(schriften.normal, basis - 2)
    c.drawString(
        _RAND_LINKS,
        y,
        f"{stammdaten.firmierung} · {anschrift.strasse} · {anschrift.plz} {anschrift.ort}",
    )
    y -= 8 * mm

    # Empfängerblock links
    empfaenger = rechnung.empfaenger
    empfaenger_zeilen = [
        empfaenger.name,
        empfaenger.anschrift.strasse,
        f"{empfaenger.anschrift.plz} {empfaenger.anschrift.ort}",
    ]
    if empfaenger.anschrift.land != "DE":
        empfaenger_zeilen.append(empfaenger.anschrift.land)
    c.setFont(schriften.normal, basis)
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

    if not masse.meta_zeile:
        # Belegdaten als Block rechts neben dem Empfänger
        c.setFont(schriften.normal, basis - 1)
        daten_y = y
        for beschriftung, wert in belegdaten:
            c.drawString(120 * mm, daten_y, f"{beschriftung}:")
            c.drawRightString(rechts, daten_y, wert)
            daten_y -= 5 * mm
        y = min(block_y, daten_y) - 10 * mm
    else:
        y = block_y - 10 * mm

    # Titel
    _pruefe_platz(y, unten)
    y -= masse.titel_luft * mm
    c.setFont(schriften.fett, masse.titel)
    c.drawString(_RAND_LINKS, y, f"{rechnung.typ.titel} {rechnung.nummer}")
    y -= (6 + masse.titel_luft) * mm

    if masse.meta_zeile:
        # Belegdaten als Zeile(n) unter dem Titel — die Nummer steht im Titel
        c.setFont(schriften.normal, basis - 1)
        meta_text = " · ".join(
            f"{beschriftung} {wert}" for beschriftung, wert in belegdaten[1:]
        )
        for zeile in _umbrechen(meta_text, schriften.normal, basis - 1, rechts - _RAND_LINKS):
            _pruefe_platz(y, unten)
            c.drawString(_RAND_LINKS, y, zeile)
            y -= hub
        y -= 4 * mm

    # Positionstabelle
    spalten = {
        "pos": _RAND_LINKS,
        "bezeichnung": _RAND_LINKS + 10 * mm,
        "menge_r": 122 * mm,
        "einzel_r": 148 * mm,
        "steuer_r": 166 * mm,
        "summe_r": rechts,
    }
    c.setFont(schriften.fett, basis - 1)
    c.drawString(spalten["pos"], y, "Pos.")
    c.drawString(spalten["bezeichnung"], y, "Leistung")
    c.drawRightString(spalten["menge_r"], y, "Menge")
    c.drawRightString(spalten["einzel_r"], y, "Einzelpreis")
    c.drawRightString(spalten["steuer_r"], y, "USt.")
    c.drawRightString(spalten["summe_r"], y, "Betrag")
    y -= 2 * mm
    linie(_RAND_LINKS, y, rechts, 0.9)
    y -= 6 * mm * masse.faktor

    c.setFont(schriften.normal, basis - 1)
    bezeichnung_breite = spalten["menge_r"] - 6 * mm - spalten["bezeichnung"]

    for nummer, position in enumerate(rechnung.positionen, start=1):
        zeilen = _umbrechen(position.bezeichnung, schriften.normal, basis - 1, bezeichnung_breite)
        if position.beschreibung:
            zeilen += _umbrechen(position.beschreibung, schriften.normal, basis - 1, bezeichnung_breite)
        benoetigt = len(zeilen) * hub + 2.5 * mm * masse.faktor
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
            y -= hub
        y -= 2.5 * mm * masse.faktor

    y -= 2 * mm
    linie(110 * mm, y, rechts)
    y -= 6 * mm * masse.faktor

    # Summenblock
    def summenzeile(beschriftung: str, wert: Decimal, fett: bool = False) -> None:
        nonlocal y
        _pruefe_platz(y, unten)
        c.setFont(schriften.fett if fett else schriften.normal, basis if fett else basis - 1)
        c.drawRightString(166 * mm, y, beschriftung)
        c.drawRightString(spalten["summe_r"], y, format_betrag(wert, rechnung.waehrung))
        y -= 5 * mm * masse.faktor

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
    if masse.linie_grau:
        linie(110 * mm, y + 3.2 * mm, rechts, 1.1)
        y -= 1 * mm
    y -= 1 * mm
    summenzeile("Gesamtbetrag", summen.brutto, fett=True)
    y -= 6 * mm * masse.faktor

    # Hinweise: Steuerbefreiungen, Zahlungsziel, Bank, Freitext
    c.setFont(schriften.normal, basis - 1)
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
        for zeile in _umbrechen(hinweis, schriften.normal, basis - 1, text_breite):
            _pruefe_platz(y, unten)
            c.drawString(_RAND_LINKS, y, zeile)
            y -= hub
        y -= 1.5 * mm * masse.faktor

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
