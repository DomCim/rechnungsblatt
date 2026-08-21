import dataclasses
from decimal import Decimal

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


def test_ueberlauf_wird_erkannt(rechnung, stammdaten):
    viele = dataclasses.replace(
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
            for i in range(40)
        ),
    )
    summen = berechne_summen(viele)
    with pytest.raises(BlattUeberlauf):
        rendere_blatt(viele, stammdaten, summen, Schreibzone())
