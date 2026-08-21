"""Zusammenbau zu PDF/A-3B: Briefpapier + Blatt + CII-XML + XMP.

Portiert aus dem validierten Prototyp (``prototyp/mk_zugferd.py``). Jeder
Schritt hier ist nötig, keiner ist entbehrlich (Übergabe, §5):

- Overlay des Blatts über das **normalisierte** Briefpapier,
- genau ein OutputIntent (sRGB, ICC eingebettet),
- ``factur-x.xml`` als eingebetteter Anhang mit ``AFRelationship /Alternative``
  und Subtype ``Name("/text/xml")`` (Fehlerklasse 1 des Prototyps),
- XMP mit ``pdfaid:part=3``/``conformance=B`` und Factur-X-Extension-Schema.

Eingabe muss das **normalisierte** Briefpapier sein — ein roher Upload
scheitert an gemischten Farbräumen (Fehlerklasse 2).
"""

from __future__ import annotations

import datetime as _dt
import io
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, Stream, String

from .xmp import erzeuge_xmp

ANHANG_NAME = "factur-x.xml"

_ICC_KANDIDATEN = (
    "/usr/share/color/icc/ghostscript/srgb.icc",
    "/usr/share/color/icc/sRGB.icc",
    "/usr/share/color/icc/colord/sRGB.icc",
    "/usr/share/texlive/texmf-dist/tex/generic/colorprofiles/sRGB.icc",
)


class IccProfilNichtGefunden(Exception):
    pass


def lade_srgb_icc(pfad: str | Path | None = None) -> bytes:
    """Lädt das sRGB-ICC-Profil für den OutputIntent."""
    kandidaten = (str(pfad),) if pfad else _ICC_KANDIDATEN
    for kandidat in kandidaten:
        datei = Path(kandidat)
        if datei.exists():
            return datei.read_bytes()
    raise IccProfilNichtGefunden(
        "Kein sRGB-ICC-Profil gefunden. Ghostscript installieren oder Pfad "
        "explizit angeben (gesucht: " + ", ".join(_ICC_KANDIDATEN) + ")."
    )


def baue_pdfa3(
    briefpapier_norm: bytes | str | Path,
    blatt: bytes,
    xml: bytes,
    titel: str,
    zeitpunkt: _dt.datetime,
    icc: bytes | None = None,
) -> bytes:
    """Setzt die fertige ZUGFeRD-Rechnung als PDF/A-3B zusammen."""
    if zeitpunkt.tzinfo is None:
        raise ValueError("zeitpunkt braucht eine Zeitzone (tzinfo).")
    icc = icc if icc is not None else lade_srgb_icc()

    quelle = (
        io.BytesIO(briefpapier_norm)
        if isinstance(briefpapier_norm, bytes)
        else str(briefpapier_norm)
    )
    with pikepdf.open(quelle) as pdf, pikepdf.open(io.BytesIO(blatt)) as overlay:
        pdf.pages[0].add_overlay(overlay.pages[0])

        # OutputIntent: genau eine Ausgabebedingung (sRGB), ICC eingebettet
        icc_stream = Stream(pdf, icc)
        icc_stream.N = 3
        icc_stream.Alternate = Name.DeviceRGB
        pdf.Root.OutputIntents = Array(
            [
                Dictionary(
                    Type=Name.OutputIntent,
                    S=Name.GTS_PDFA1,
                    OutputConditionIdentifier=String("sRGB IEC61966-2.1"),
                    Info=String("sRGB IEC61966-2.1"),
                    DestOutputProfile=icc_stream,
                )
            ]
        )

        # CII-XML als eingebetteter Anhang
        datei_stream = Stream(pdf, xml)
        datei_stream.Type = Name.EmbeddedFile
        datei_stream.Subtype = Name("/text/xml")  # Fehlerklasse 1: korrekt kodiert
        datei_stream.Params = Dictionary(
            ModDate=String(_pdf_datum(zeitpunkt)), Size=len(xml)
        )
        spec = pdf.make_indirect(
            Dictionary(
                Type=Name.Filespec,
                F=String(ANHANG_NAME),
                UF=String(ANHANG_NAME),
                Desc=String("Factur-X/ZUGFeRD Invoice"),
                AFRelationship=Name.Alternative,  # zwingend für ZUGFeRD
                EF=Dictionary(F=datei_stream, UF=datei_stream),
            )
        )
        pdf.Root.AF = Array([spec])
        pdf.Root.Names = Dictionary(
            EmbeddedFiles=Dictionary(Names=Array([String(ANHANG_NAME), spec]))
        )
        pdf.Root.MarkInfo = Dictionary(Marked=True)
        if Name.Lang not in pdf.Root:
            pdf.Root.Lang = String("de-DE")

        # XMP-Metadaten (unkomprimierter Metadata-Stream)
        xmp_stream = Stream(pdf, erzeuge_xmp(titel, zeitpunkt))
        xmp_stream.Type = Name.Metadata
        xmp_stream.Subtype = Name.XML
        pdf.Root.Metadata = pdf.make_indirect(xmp_stream)

        ausgabe = io.BytesIO()
        pdf.save(ausgabe)
        return ausgabe.getvalue()


def _pdf_datum(zeitpunkt: _dt.datetime) -> str:
    """PDF-Datumsformat: D:YYYYMMDDHHmmSS+HH'mm'"""
    offset = zeitpunkt.utcoffset() or _dt.timedelta(0)
    minuten_gesamt = int(offset.total_seconds() // 60)
    vorzeichen = "+" if minuten_gesamt >= 0 else "-"
    stunden, minuten = divmod(abs(minuten_gesamt), 60)
    return (
        "D:"
        + zeitpunkt.strftime("%Y%m%d%H%M%S")
        + f"{vorzeichen}{stunden:02d}'{minuten:02d}'"
    )
