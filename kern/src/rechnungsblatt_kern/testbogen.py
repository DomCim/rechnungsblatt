"""Testbögen mit den realen Problemfällen — nur für Tests und CI-Referenzfälle.

Portiert aus ``prototyp/mk_briefpapier.py``: A4-Briefbogen mit CMYK-Flächen
(Druckvorstufe), halbtransparentem Zierbalken, Logo als PNG mit Alphakanal
und Producer „Adobe InDesign". Modus ``gut`` bettet Schriften ein (TTF),
``boese`` nutzt Base-14 ohne Einbettung — der Fall, den nur die
Normalisierung mit ``-sFONTPATH`` rettet.
"""

from __future__ import annotations

import io

from reportlab.lib.colors import CMYKColor, Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .blatt import registriere_schriften

_LIBERATION_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
_LIBERATION_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def _logo_png() -> ImageReader:
    from PIL import Image, ImageDraw  # Pillow ist Abhängigkeit von reportlab

    bild = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    zeichner = ImageDraw.Draw(bild)
    zeichner.ellipse((20, 20, 380, 380), fill=(200, 30, 40, 255))
    zeichner.ellipse((110, 110, 290, 290), fill=(255, 255, 255, 0))
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    puffer.seek(0)
    return ImageReader(puffer)


def erzeuge_testbogen(modus: str = "gut") -> bytes:
    """Erzeugt einen Testbogen. ``gut`` = TTF eingebettet, ``boese`` = Base-14."""
    if modus == "gut":
        try:
            pdfmetrics.getFont("TB")
        except KeyError:
            pdfmetrics.registerFont(TTFont("TR", _LIBERATION_REGULAR))
            pdfmetrics.registerFont(TTFont("TB", _LIBERATION_BOLD))
        fett, normal = "TB", "TR"
    elif modus == "boese":
        fett, normal = "Helvetica-Bold", "Helvetica"  # Base-14, NICHT eingebettet
    else:
        raise ValueError(f"Unbekannter Modus: {modus!r} (erwartet 'gut' oder 'boese')")

    breite, hoehe = A4
    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=A4)
    c.setProducer("Adobe InDesign 19.0 (Macintosh)")
    c.setFillColor(CMYKColor(0.85, 0.20, 0.0, 0.10))  # CMYK-Fläche
    c.rect(0, hoehe - 45 * mm, breite, 45 * mm, stroke=0, fill=1)
    c.saveState()
    c.setFillColor(Color(1, 1, 1, alpha=0.35))  # Transparenz
    c.rect(0, hoehe - 50 * mm, breite, 6 * mm, stroke=0, fill=1)
    c.restoreState()
    c.drawImage(  # Alphakanal-Bild
        _logo_png(), 150 * mm, hoehe - 40 * mm, 32 * mm, 32 * mm, mask="auto"
    )
    c.setFillColorRGB(1, 1, 1)
    c.setFont(fett, 20)
    c.drawString(20 * mm, hoehe - 28 * mm, "Muster & Partner GmbH")
    c.setFont(normal, 9)
    c.drawString(20 * mm, hoehe - 35 * mm, "Handwerk seit 1978")
    c.setFillColor(CMYKColor(0.85, 0.20, 0.0, 0.10))
    c.rect(0, 0, breite, 22 * mm, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont(normal, 7.5)
    for index, zeile in enumerate(
        [
            "Muster & Partner GmbH · Bahnhofstr. 12 · 95119 Naila",
            "Tel 09282 12345 · info@muster-partner.de · USt-IdNr. DE123456789",
            "Sparkasse Hochfranken · IBAN DE02 7805 0000 0001 2345 67",
        ]
    ):
        c.drawString(20 * mm, 15 * mm - index * 3.5 * mm, zeile)
    c.showPage()
    c.save()
    return puffer.getvalue()
