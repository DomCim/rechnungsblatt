import dataclasses
import io
import re
from decimal import Decimal

import pikepdf
import pytest

from rechnungsblatt_kern import (
    BlattUeberlauf,
    Position,
    Schreibzone,
    Steuerkategorie,
    berechne_summen,
    format_betrag,
    rendere_blatt,
)


def test_format_betrag_deutsch():
    assert format_betrag(Decimal("1234.56")) == "1.234,56 €"
    assert format_betrag(Decimal("0.05")) == "0,05 €"
    assert format_betrag(Decimal("-12.30")) == "-12,30 €"
    assert format_betrag(Decimal("1000000.00")) == "1.000.000,00 €"


def test_schreibzone_validierung():
    with pytest.raises(ValueError):
        Schreibzone(kopf_ende_mm=150, fuss_beginn_mm=100)
    with pytest.raises(ValueError):
        Schreibzone(kopf_ende_mm=-1, fuss_beginn_mm=20)
    zone = Schreibzone(kopf_ende_mm=45, fuss_beginn_mm=25)
    assert zone.nutzhoehe_mm == pytest.approx(227.0)


def test_blatt_ist_einseitiges_pdf(rechnung, stammdaten):
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone())
    assert blatt.startswith(b"%PDF-")

    import pikepdf, io

    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) == 1


def test_blatt_bettet_benutzte_schriften_ein(rechnung, stammdaten):
    """PDF/A verlangt eingebettete Schriften — Base-14 wäre Fehlerklasse 3.

    Bewertet werden nur per ``Tf`` benutzte Schriften; das unbenutzte
    Standard-Helvetica, das reportlab immer anlegt, ist nachweislich
    unkritisch (Prototyp: 124 passedRules, 0 failed).
    """
    import io

    import pikepdf

    from rechnungsblatt_kern.normalisierung import _benutzte_schriften

    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        benutzte = list(_benutzte_schriften(pdf.pages[0]))
        assert len(benutzte) >= 2  # normal + fett
        for schrift, name in benutzte:
            deskriptor = schrift.get("/FontDescriptor", None)
            if deskriptor is None and "/DescendantFonts" in schrift:
                deskriptor = schrift.DescendantFonts[0].get("/FontDescriptor", None)
            assert deskriptor is not None, f"{name}: ohne FontDescriptor (Base-14?)"
            assert any(
                key in deskriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
            ), f"{name}: Schriftprogramm nicht eingebettet"


def _viele_positionen(rechnung, anzahl: int):
    return dataclasses.replace(
        rechnung,
        positionen=tuple(
            Position(
                bezeichnung=f"Position {i} mit einem sehr langen beschreibenden Text, "
                "der über mehrere Zeilen umbricht und Platz verbraucht",
                menge=Decimal("1"),
                einheit="C62",
                einzelpreis=Decimal("10.00"),
                steuer=Steuerkategorie.UST_19,
            )
            for i in range(anzahl)
        ),
    )


def test_viele_positionen_brechen_um(rechnung, stammdaten):
    """40 Positionen ergeben mehrere Seiten statt eines Überlauffehlers."""
    viele = _viele_positionen(rechnung, 40)
    summen = berechne_summen(viele)
    blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) > 1


def test_umbruch_auch_bei_hoher_fussleiste(rechnung, stammdaten):
    """Eine hohe Fußleiste verkleinert die Zone — es muss trotzdem gehen."""
    viele = _viele_positionen(rechnung, 25)
    summen = berechne_summen(viele)
    eng = Schreibzone(kopf_ende_mm=50, fuss_beginn_mm=60)
    blatt = rendere_blatt(viele, stammdaten, summen, eng)
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) > 2  # enge Zone braucht mehr Seiten


def _seitentext(pdf, nummer: int) -> str:
    """Sichtbaren Text einer Seite aus den Content-Streams lesen.

    pikepdf bringt keine Textextraktion mit; für die Prüfung genügen die
    Zeichenketten in Klammern, die der Textoperator ausgibt.
    """
    roh = pikepdf.Page(pdf.pages[nummer]).obj.Contents.read_bytes()
    stuecke = re.findall(rb"\(([^()]*)\)", roh)
    return b" ".join(stuecke).decode("latin-1", "replace")


def test_uebertrag_und_seitenzahl_stehen_auf_dem_blatt(rechnung, stammdaten):
    viele = _viele_positionen(rechnung, 40)
    summen = berechne_summen(viele)
    blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        gesamt = len(pdf.pages)
        erste = _seitentext(pdf, 0)
        letzte = _seitentext(pdf, gesamt - 1)
    assert "bertrag" in erste  # „Übertrag“, Umlaut je nach Kodierung
    assert f"Seite 1 von {gesamt}" in erste
    assert f"Seite {gesamt} von {gesamt}" in letzte


def test_einseitig_ohne_seitenzahl(rechnung, stammdaten):
    """Eine Seite bleibt eine Seite — ohne Fußzeile und ohne Übertrag."""
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) == 1
        text = _seitentext(pdf, 0)
    assert "Seite 1 von" not in text
    assert "bertrag" not in text
