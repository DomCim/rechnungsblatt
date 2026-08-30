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


# ---------------------------------------------------------------- Farben

def _farbe(hex_wert: str) -> tuple[float, float, float]:
    """Wandelt ``#rrggbb`` in RGB-Anteile von 0 bis 1.

    Unbrauchbare Werte fallen auf ein neutrales Dunkelgrau zurück statt zu
    scheitern — eine Rechnung darf an einer Farbangabe nicht hängenbleiben.
    """
    text = (hex_wert or "").strip().lstrip("#")
    if len(text) == 3:  # Kurzform #abc
        text = "".join(zeichen * 2 for zeichen in text)
    if len(text) != 6:
        return (0.2, 0.2, 0.2)
    try:
        werte = tuple(int(text[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.2, 0.2, 0.2)
    return werte  # type: ignore[return-value]


def _mische(farbe: tuple[float, float, float], anteil: float) -> tuple[float, float, float]:
    """Mischt eine Farbe mit Weiß — ``anteil`` 0 ergibt Weiß, 1 die Farbe."""
    return tuple(1 - (1 - kanal) * anteil for kanal in farbe)  # type: ignore[return-value]


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
    ohne_linien: bool = False  # gar keine Trennlinien (LUFTIG)
    zebra: bool = False  # getönte Wechselzeilen statt Linien (ZEBRA)
    farbige_linien: bool = False  # Linien in der Akzentfarbe (AKZENT)
    meta_zweispaltig: bool = False  # Belegdatenzeile in zwei Spalten (DOPPELT)


def _masse(gestaltung: Blattgestaltung) -> _Masse:
    basis = gestaltung.schriftgrad.value
    farbig = gestaltung.akzent_an
    if gestaltung.layout is Layoutvariante.KOMPAKT:
        return _Masse(
            basis=basis, faktor=0.85, titel=basis + 2,
            meta_zeile=True, linie_grau=False, titel_luft=0.0,
            farbige_linien=farbig,
        )
    if gestaltung.layout is Layoutvariante.MODERN:
        return _Masse(
            basis=basis, faktor=1.1, titel=basis + 7,
            meta_zeile=gestaltung.belegdaten_als_zeile, linie_grau=True,
            titel_luft=3.0, farbige_linien=farbig,
        )
    if gestaltung.layout is Layoutvariante.ZEBRA:
        return _Masse(
            basis=basis, faktor=1.0, titel=basis + 4,
            meta_zeile=gestaltung.belegdaten_als_zeile, linie_grau=True,
            titel_luft=0.0, zebra=True, farbige_linien=farbig,
        )
    if gestaltung.layout is Layoutvariante.LUFTIG:
        return _Masse(
            # 1.25 lief bei vier Positionen samt GiroCode über die Zone —
            # luftig soll wirken, nicht die zweite Seite erzwingen.
            basis=basis, faktor=1.12, titel=basis + 7,
            meta_zeile=gestaltung.belegdaten_als_zeile, linie_grau=True,
            titel_luft=4.0, ohne_linien=True, farbige_linien=farbig,
        )
    if gestaltung.layout is Layoutvariante.DOPPELT:
        return _Masse(
            basis=basis, faktor=0.78, titel=basis + 1,
            meta_zeile=True, linie_grau=False, titel_luft=0.0,
            meta_zweispaltig=True, farbige_linien=farbig,
        )
    return _Masse(
        basis=basis, faktor=1.0, titel=basis + 4,
        meta_zeile=gestaltung.belegdaten_als_zeile, linie_grau=False,
        titel_luft=0.0, farbige_linien=farbig,
    )


# ---------------------------------------------------------------- Rendering

def rendere_blatt(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    summen: Summen,
    zone: Schreibzone,
    schriften: Schriften | None = None,
    gestaltung: Blattgestaltung | None = None,
    girocode: bool = True,
) -> bytes:
    """Rendert das Overlay-PDF und liefert es als Bytes.

    Passt der Inhalt nicht auf eine Seite, wird umbrochen: die Seite endet
    mit „Übertrag“, die nächste beginnt damit und wiederholt den
    Tabellenkopf. Weil die Fußzeile „Seite x von y“ die Gesamtzahl braucht,
    diese aber erst nach dem Zeichnen feststeht, läuft das Rendern zweimal —
    einmal zum Zählen, einmal endgültig.
    """
    erster = _rendere(
        rechnung, stammdaten, summen, zone, schriften, gestaltung, girocode,
        gesamtseiten=None,
    )
    if erster.seiten == 1:
        return erster.daten   # einseitig: keine Fußzeile, kein zweiter Lauf
    return _rendere(
        rechnung, stammdaten, summen, zone, schriften, gestaltung, girocode,
        gesamtseiten=erster.seiten,
    ).daten


@dataclass(frozen=True)
class _Blattergebnis:
    daten: bytes
    seiten: int


def _rendere(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    summen: Summen,
    zone: Schreibzone,
    schriften: Schriften | None,
    gestaltung: Blattgestaltung | None,
    girocode: bool,
    gesamtseiten: int | None,
) -> _Blattergebnis:
    """Ein Durchlauf. ``gesamtseiten`` None = Zähllauf ohne Fußzeile."""
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
    # Sobald umbrochen wird, steht unten die Seitenzahl. Der Zähllauf weiß
    # noch nicht, ob es mehrseitig wird, und muss denselben Platz freihalten
    # wie der zweite Lauf — sonst zählt er zu wenige Seiten und die Fußzeile
    # kollidiert. Deshalb pauschal in beiden Läufen.
    unten += 5 * mm
    rechts = breite - _RAND_RECHTS

    akzent = _farbe(gestaltung.akzentfarbe)

    def linie(x1: float, y: float, x2: float, staerke: float = 0.6) -> None:
        if masse.ohne_linien:
            return
        if masse.farbige_linien:
            c.setStrokeColorRGB(*akzent)
            staerke = max(staerke, 1.2)   # farbig darf kräftiger sein
        elif masse.linie_grau:
            c.setStrokeColorRGB(0.62, 0.62, 0.62)
        else:
            c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(staerke)
        c.line(x1, y, x2, y)
        c.setStrokeColorRGB(0, 0, 0)

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
    if masse.farbige_linien:
        c.setFillColorRGB(*akzent)
    c.drawString(_RAND_LINKS, y, f"{rechnung.typ.titel} {rechnung.nummer}")
    c.setFillColorRGB(0, 0, 0)
    if masse.farbige_linien:
        # Kräftiger Strich unter dem Titel — das Erkennungsmerkmal.
        y -= 2.5 * mm
        linie(_RAND_LINKS, y, rechts, 1.6)
    y -= (6 + masse.titel_luft) * mm

    if masse.meta_zeile and masse.meta_zweispaltig:
        # Zwei Spalten: spart bei vielen Belegdaten mehrere Zeilen Höhe.
        c.setFont(schriften.normal, basis - 1)
        rest = belegdaten[1:]
        mitte = (len(rest) + 1) // 2
        spalte_zwei = _RAND_LINKS + (rechts - _RAND_LINKS) / 2
        for index in range(mitte):
            _pruefe_platz(y, unten)
            beschriftung, wert = rest[index]
            c.drawString(_RAND_LINKS, y, f"{beschriftung}: {wert}")
            if index + mitte < len(rest):
                zwei_b, zwei_w = rest[index + mitte]
                c.drawString(spalte_zwei, y, f"{zwei_b}: {zwei_w}")
            y -= hub
        y -= 3 * mm
    elif masse.meta_zeile:
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
    def tabellenkopf() -> None:
        """Spaltenüberschriften — auf jeder Seite erneut."""
        nonlocal y
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

    tabellenkopf()
    bezeichnung_breite = spalten["menge_r"] - 6 * mm - spalten["bezeichnung"]

    # --- Seitenumbruch --------------------------------------------------
    # Reißt der Platz in der Positionsliste, wird die Seite mit einem
    # Übertrag geschlossen und auf der nächsten mit demselben Übertrag und
    # wiederholtem Tabellenkopf fortgesetzt. Das Briefpapier legt später
    # zusammenbau.baue_pdfa3() unter JEDE Seite.
    seiten = 1

    def seitenfuss() -> None:
        """„Seite x von y“ unten rechts — nur im zweiten Lauf."""
        if gesamtseiten is None:
            return
        c.setFont(schriften.normal, basis - 2)
        c.setFillColorRGB(0.45, 0.45, 0.45)
        # INNERHALB der Schreibzone: unterhalb davon liegt die Fußleiste des
        # Briefbogens, dort würde die Zahl in fremde Gestaltung geraten.
        c.drawRightString(
            rechts, unten + 1.5 * mm, f"Seite {seiten} von {gesamtseiten}"
        )
        c.setFillColorRGB(0, 0, 0)
        c.setFont(schriften.normal, basis - 1)

    def uebertragszeile(text: str, wert: Decimal) -> None:
        nonlocal y
        c.setFont(schriften.fett, basis - 1)
        c.drawRightString(166 * mm, y, text)
        c.drawRightString(spalten["summe_r"], y, format_betrag(wert, rechnung.waehrung))
        c.setFont(schriften.normal, basis - 1)
        y -= 5 * mm * masse.faktor

    def neue_seite(bisher: Decimal) -> None:
        """Schließt die Seite mit „Übertrag“ und öffnet die nächste."""
        nonlocal y, seiten
        y -= 1 * mm
        linie(110 * mm, y, rechts)
        y -= 5 * mm * masse.faktor
        uebertragszeile("Übertrag", bisher)
        seitenfuss()
        c.showPage()
        seiten += 1
        # Schriften gelten je Seite neu; y beginnt wieder oben in der Zone.
        c.setFillColorRGB(0, 0, 0)
        y = oben - 6 * mm
        c.setFont(schriften.normal, basis - 1)
        uebertragszeile("Übertrag", bisher)
        y -= 2 * mm
        tabellenkopf()

    laufende_summe = Decimal("0.00")
    for nummer, position in enumerate(rechnung.positionen, start=1):
        # Artikelnummer als eigene Zeile über der Bezeichnung: so bleibt das
        # Spaltenraster gleich, auch wenn nur einzelne Positionen eine haben.
        zeilen = []
        if position.artikelnummer:
            zeilen += _umbrechen(
                f"Art.-Nr. {position.artikelnummer}",
                schriften.normal,
                basis - 1,
                bezeichnung_breite,
            )
        zeilen += _umbrechen(position.bezeichnung, schriften.normal, basis - 1, bezeichnung_breite)
        if position.beschreibung:
            zeilen += _umbrechen(position.beschreibung, schriften.normal, basis - 1, bezeichnung_breite)
        benoetigt = len(zeilen) * hub + 2.5 * mm * masse.faktor
        # Platz für die Zeile UND die Übertragszeile darunter vorhalten,
        # sonst steht der Übertrag im Fußbereich.
        if y - benoetigt - 10 * mm * masse.faktor < unten:
            neue_seite(laufende_summe)
        _pruefe_platz(y - benoetigt, unten)
        if masse.zebra and nummer % 2 == 1:
            # Tönung hinter die Zeile legen, bevor der Text kommt.
            # Ohne Akzentfarbe grau tönen statt farbig.
            grundton = akzent if masse.farbige_linien else (0.35, 0.35, 0.35)
            c.setFillColorRGB(*_mische(grundton, 0.08))
            c.rect(
                _RAND_LINKS - 2 * mm,
                y - benoetigt + hub - 1.5 * mm,
                rechts - _RAND_LINKS + 4 * mm,
                benoetigt,
                stroke=0,
                fill=1,
            )
            c.setFillColorRGB(0, 0, 0)
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
        laufende_summe += zeilensumme(position)

    # Summenblock, Freitext und GiroCode gehören zusammen und dürfen nicht
    # getrennt werden — reicht der Rest der Seite nicht, kommen sie
    # geschlossen auf die nächste (ohne Übertrag, die Liste ist ja fertig).
    # Grob, aber großzügig: Summenzeilen (je 5 mm) + Zahlungshinweise und
    # Freitext (je Zeile ~5 mm) + GiroCode (26 mm plus Abstand). Lieber eine
    # Seite zu früh umbrechen als mitten im Summenblock abreißen.
    zeilen_schluss = 3 + len(summen.koerbe)          # Zwischensumme, USt., Gesamt
    if summen.rabatt > 0:
        zeilen_schluss += 2
    hinweis_zeilen = 3 + (2 if rechnung.freitext else 0)
    benoetigt_schluss = (
        (6 + 5 * zeilen_schluss + 5 * hinweis_zeilen) * mm * masse.faktor
        + (32 * mm if girocode and stammdaten.iban.strip() else 0)
    )
    if y - benoetigt_schluss < unten:
        seitenfuss()
        c.showPage()
        seiten += 1
        c.setFillColorRGB(0, 0, 0)
        y = oben - 6 * mm
        c.setFont(schriften.normal, basis - 1)

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
        # Bei Prozentrabatt den Satz mit ausweisen: "Treuerabatt (10 %)".
        beschriftung = rechnung.rabatt_grund
        if rechnung.rabatt_prozent is not None:
            beschriftung = f"{beschriftung} ({rechnung.rabatt_prozent:.10g} %)"
        summenzeile(beschriftung, -summen.rabatt)
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
    if rechnung.verwendungszweck:
        hinweise.append(f"Verwendungszweck: {rechnung.verwendungszweck}")
    if rechnung.freitext:
        hinweise.append(rechnung.freitext)

    for hinweis in hinweise:
        for zeile in _umbrechen(hinweis, schriften.normal, basis - 1, text_breite):
            _pruefe_platz(y, unten)
            c.drawString(_RAND_LINKS, y, zeile)
            y -= hub
        y -= 1.5 * mm * masse.faktor

    # GiroCode: nur wenn der Empfänger tatsächlich etwas überweisen soll
    from .modell import Belegtyp

    if (
        girocode
        and rechnung.typ is not Belegtyp.GUTSCHRIFT
        and summen.brutto > 0
        and stammdaten.iban.strip()
    ):
        from .girocode import erzeuge_epc_daten, zeichne_girocode

        qr_mm = 26.0
        y -= 3 * mm
        _pruefe_platz(y - qr_mm * mm, unten)
        daten = erzeuge_epc_daten(
            name=stammdaten.firmierung,
            iban=stammdaten.iban,
            betrag=summen.brutto,
            bic=stammdaten.bic,
            verwendungszweck=rechnung.verwendungszweck or rechnung.nummer,
        )
        zeichne_girocode(c, daten, _RAND_LINKS + 1 * mm, y - qr_mm * mm, qr_mm)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(schriften.fett, basis - 1)
        text_x = _RAND_LINKS + (qr_mm + 7) * mm
        c.drawString(text_x, y - 5 * mm, "Bezahlen per Banking-App: GiroCode scannen")
        c.setFont(schriften.normal, basis - 2)
        for versatz, zeile in enumerate(
            _umbrechen(
                "Empfänger, IBAN, Betrag und Verwendungszweck werden automatisch übernommen.",
                schriften.normal,
                basis - 2,
                rechts - text_x,
            )
        ):
            c.drawString(text_x, y - (10 + versatz * 4.2) * mm, zeile)

    seitenfuss()
    c.showPage()
    c.save()
    return _Blattergebnis(daten=puffer.getvalue(), seiten=seiten)


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
