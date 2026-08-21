"""Briefpapier-Normalisierung — der entscheidende Schritt (Übergabe, §4).

PDF/A erlaubt genau eine Ausgabebedingung; echte Briefbögen mischen CMYK aus
der Druckvorstufe mit RGB aus dem Web. Ghostscript vereinheitlicht den
Farbraum auf sRGB und bettet fehlende Schriften ein (``-sFONTPATH`` ist nicht
optional — ohne ihn scheitern Bögen mit Base-14-Schriften).

Läuft einmalig beim Einrichten: Upload → normalisieren → Ampelprüfung →
normalisierte Fassung speichern, Original verwerfen.

Lizenzhinweis: Ghostscript ist AGPL. Vor kommerziellem Betrieb ist die
Artifex-Lizenzfrage zu klären (offenes Risiko Nr. 1 der Übergabe).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pikepdf

_FONTPFADE_STANDARD = (
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/dejavu",
)

_MEHRSEITIG_HINWEIS = (
    "Der Briefbogen hat mehrere Seiten. Unterstützt wird genau eine Seite "
    "(Übergabe §10: mehrseitige Bögen brauchen einen sauberen Ablehnungsweg)."
)


class NormalisierungAbgelehnt(Exception):
    """Der Upload wird bewusst abgelehnt statt eine kaputte Rechnung zu riskieren."""


class NormalisierungFehlgeschlagen(Exception):
    """Ghostscript konnte den Bogen nicht normalisieren."""


@dataclass(frozen=True)
class NormalisierungsErgebnis:
    pfad: Path
    schriften_ersetzt: bool  # für die Vorschau-Warnung „bitte prüfen"


def pruefe_upload(upload: str | Path) -> None:
    """Weist Uploads ab, die der bewiesene Weg nicht trägt."""
    try:
        with pikepdf.open(str(upload)) as pdf:
            if pdf.is_encrypted:
                raise NormalisierungAbgelehnt(
                    "Der Briefbogen ist verschlüsselt. Bitte eine unverschlüsselte "
                    "Fassung hochladen."
                )
            if len(pdf.pages) != 1:
                raise NormalisierungAbgelehnt(_MEHRSEITIG_HINWEIS)
    except pikepdf.PasswordError as fehler:
        raise NormalisierungAbgelehnt(
            "Der Briefbogen ist passwortgeschützt. Bitte eine ungeschützte "
            "Fassung hochladen."
        ) from fehler
    except pikepdf.PdfError as fehler:
        raise NormalisierungAbgelehnt(
            f"Die Datei ist kein lesbares PDF: {fehler}"
        ) from fehler


def normalisiere_briefpapier(
    upload: str | Path,
    ausgabe: str | Path,
    gs_programm: str = "gs",
    fontpfade: tuple[str, ...] = _FONTPFADE_STANDARD,
) -> NormalisierungsErgebnis:
    """Führt den bewiesenen Ghostscript-Aufruf aus (Übergabe, §4).

    Reihenfolge ist zwingend: Dieser Schritt läuft VOR jeder Überlagerung.
    """
    upload = Path(upload)
    ausgabe = Path(ausgabe)
    if shutil.which(gs_programm) is None:
        raise NormalisierungFehlgeschlagen(
            f"Ghostscript ({gs_programm!r}) ist nicht installiert."
        )
    pruefe_upload(upload)

    vorhandene_fontpfade = [pfad for pfad in fontpfade if Path(pfad).is_dir()]
    if not vorhandene_fontpfade:
        raise NormalisierungFehlgeschlagen(
            "Keiner der Ersatzschrift-Pfade existiert — ohne -sFONTPATH scheitern "
            f"Bögen mit Base-14-Schriften. Gesucht: {', '.join(fontpfade)}"
        )

    schriften_vorher = _unvollstaendige_schriften(upload)

    befehl = [
        gs_programm,
        "-dQUIET",
        "-dBATCH",
        "-dNOPAUSE",
        "-sDEVICE=pdfwrite",
        "-dColorConversionStrategy=/sRGB",
        "-dProcessColorModel=/DeviceRGB",
        "-dConvertCMYKImagesToRGB=true",
        "-dEmbedAllFonts=true",
        "-dSubsetFonts=true",
        "-dPDFSETTINGS=/prepress",
        "-dCompatibilityLevel=1.7",
        f"-sFONTPATH={':'.join(vorhandene_fontpfade)}",
        f"-sOutputFile={ausgabe}",
        str(upload),
    ]
    ergebnis = subprocess.run(befehl, capture_output=True, text=True)
    if ergebnis.returncode != 0 or not ausgabe.exists() or ausgabe.stat().st_size == 0:
        raise NormalisierungFehlgeschlagen(
            "Ghostscript-Normalisierung fehlgeschlagen "
            f"(Exit {ergebnis.returncode}): {ergebnis.stderr.strip() or ergebnis.stdout.strip()}"
        )

    return NormalisierungsErgebnis(
        pfad=ausgabe,
        schriften_ersetzt=bool(schriften_vorher),
    )


def _unvollstaendige_schriften(pdf_pfad: Path) -> list[str]:
    """Findet **benutzte** Schriften ohne eingebettetes Schriftprogramm.

    Nur Schriften, die der Inhaltsstrom per ``Tf`` tatsächlich auswählt,
    zählen — unbenutzte Einträge im Ressourcen-Wörterbuch (z. B. das
    Standard-Helvetica, das reportlab immer anlegt) sind für die
    PDF/A-Prüfung nachweislich unkritisch.
    """
    gefunden: list[str] = []
    with pikepdf.open(str(pdf_pfad)) as pdf:
        for seite in pdf.pages:
            for schrift, name in _benutzte_schriften(seite):
                if _ohne_schriftprogramm(schrift):
                    basis = str(schrift.get("/BaseFont", name))
                    if basis not in gefunden:
                        gefunden.append(basis)
    return gefunden


_TEXTZEIGER = {"Tj", "TJ", "'", '"'}


def _benutzte_schriften(traeger, tiefe: int = 0):
    """Liefert (Schrift, Name) für alle Schriften, mit denen tatsächlich Text
    gezeichnet wird — auch in eingebetteten Form-XObjects (begrenzte Tiefe).

    Eine Schrift gilt als benutzt, wenn sie beim Auftreten eines
    textzeigenden Operators (Tj, TJ, ', ") die aktive ist — nur solche
    prüft auch veraPDF auf Einbettung.
    """
    if tiefe > 4:
        return
    ressourcen = traeger.get("/Resources", None)
    schriften = ressourcen.get("/Font", None) if ressourcen is not None else None
    try:
        benutzt: set[str] | None = set()
        aktiv: str | None = None
        for operanden, operator in pikepdf.parse_content_stream(traeger):
            operator = str(operator)
            if operator == "Tf" and operanden:
                aktiv = str(operanden[0])
            elif operator in _TEXTZEIGER and aktiv is not None:
                benutzt.add(aktiv)
    except pikepdf.PdfError:
        benutzt = None  # Inhalt nicht lesbar → konservativ alle prüfen
    if schriften is not None:
        for name, schrift in schriften.items():
            if benutzt is None or str(name) in benutzt:
                yield schrift, str(name)
    xobjekte = ressourcen.get("/XObject", None) if ressourcen is not None else None
    if xobjekte is not None:
        for xobjekt in xobjekte.values():
            if xobjekt.get("/Subtype", None) == pikepdf.Name("/Form"):
                yield from _benutzte_schriften(xobjekt, tiefe + 1)


def _ohne_schriftprogramm(schrift) -> bool:
    untertyp = schrift.get("/Subtype", None)
    if untertyp == pikepdf.Name("/Type0"):
        nachkommen = schrift.get("/DescendantFonts", None)
        if nachkommen is not None and len(nachkommen) > 0:
            schrift = nachkommen[0]
    deskriptor = schrift.get("/FontDescriptor", None)
    if deskriptor is None:
        return True  # Base-14 ohne Deskriptor → nicht eingebettet
    return not any(
        schluessel in deskriptor
        for schluessel in ("/FontFile", "/FontFile2", "/FontFile3")
    )
