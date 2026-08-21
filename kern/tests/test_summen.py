import dataclasses
from decimal import Decimal

import pytest

from rechnungsblatt_kern import (
    Position,
    Steuerkategorie,
    berechne_summen,
    runden,
    zeilensumme,
)


def _position(preis: str, menge: str = "1", steuer=Steuerkategorie.UST_19) -> Position:
    return Position(
        bezeichnung="Leistung",
        menge=Decimal(menge),
        einheit="C62",
        einzelpreis=Decimal(preis),
        steuer=steuer,
    )


def test_runden_kaufmaennisch_half_up():
    assert runden(Decimal("0.005")) == Decimal("0.01")
    assert runden(Decimal("0.004")) == Decimal("0.00")
    assert runden(Decimal("2.675")) == Decimal("2.68")  # der Float-Klassiker
    assert runden(Decimal("19.994")) == Decimal("19.99")
    assert runden(Decimal("19.995")) == Decimal("20.00")


def test_zeilensumme_rundet_erst_nach_multiplikation():
    position = _position("0.333", menge="3")
    assert zeilensumme(position) == Decimal("1.00")  # 0.999 -> 1.00


def test_einfache_rechnung_19_prozent(rechnung):
    summen = berechne_summen(rechnung)
    assert summen.zeilensumme == Decimal("200.00")
    assert summen.steuerbasis == Decimal("200.00")
    assert summen.steuer == Decimal("38.00")
    assert summen.brutto == Decimal("238.00")
    assert len(summen.koerbe) == 1
    assert summen.koerbe[0].kategorie is Steuerkategorie.UST_19


def test_summen_je_steuersatz_aufgeschluesselt(rechnung):
    gemischt = dataclasses.replace(
        rechnung,
        positionen=(
            _position("100.00"),
            _position("50.00", steuer=Steuerkategorie.UST_7),
            _position("10.00", steuer=Steuerkategorie.UST_7),
        ),
    )
    summen = berechne_summen(gemischt)
    koerbe = {korb.kategorie: korb for korb in summen.koerbe}
    assert koerbe[Steuerkategorie.UST_19].basis == Decimal("100.00")
    assert koerbe[Steuerkategorie.UST_19].steuer == Decimal("19.00")
    assert koerbe[Steuerkategorie.UST_7].basis == Decimal("60.00")
    assert koerbe[Steuerkategorie.UST_7].steuer == Decimal("4.20")
    assert summen.brutto == Decimal("183.20")


def test_steuer_wird_je_korb_gerundet(rechnung):
    einzeln = dataclasses.replace(rechnung, positionen=(_position("0.13"),))
    summen = berechne_summen(einzeln)
    # 0.13 * 19 % = 0.0247 -> 0.02
    assert summen.steuer == Decimal("0.02")
    assert summen.brutto == Decimal("0.15")


def test_rabatt_wird_anteilig_und_rundungsfest_verteilt(rechnung):
    gemischt = dataclasses.replace(
        rechnung,
        rabatt_betrag=Decimal("10.00"),
        positionen=(
            _position("100.00"),
            _position("50.00", steuer=Steuerkategorie.UST_7),
        ),
    )
    summen = berechne_summen(gemischt)
    koerbe = {korb.kategorie: korb for korb in summen.koerbe}
    assert koerbe[Steuerkategorie.UST_19].rabatt == Decimal("6.67")
    assert koerbe[Steuerkategorie.UST_7].rabatt == Decimal("3.33")
    # Die Anteile ergeben exakt den Rabatt
    assert sum(korb.rabatt for korb in summen.koerbe) == Decimal("10.00")
    assert summen.steuerbasis == Decimal("140.00")


def test_rabatt_rundungsdifferenz_geht_in_groessten_korb(rechnung):
    drei = dataclasses.replace(
        rechnung,
        rabatt_betrag=Decimal("0.10"),
        positionen=(
            _position("100.00"),
            _position("100.00", steuer=Steuerkategorie.UST_7),
            _position("100.00", steuer=Steuerkategorie.UST_0),
        ),
    )
    summen = berechne_summen(drei)
    assert sum(korb.rabatt for korb in summen.koerbe) == Decimal("0.10")


def test_rabatt_groesser_als_summe_wird_abgelehnt(rechnung):
    zu_gross = dataclasses.replace(rechnung, rabatt_betrag=Decimal("500.00"))
    with pytest.raises(ValueError):
        berechne_summen(zu_gross)


def test_befreite_kategorien_ohne_steuer(rechnung):
    befreit = dataclasses.replace(
        rechnung, positionen=(_position("100.00", steuer=Steuerkategorie.REVERSE_CHARGE),)
    )
    summen = berechne_summen(befreit)
    assert summen.steuer == Decimal("0.00")
    assert summen.brutto == Decimal("100.00")


def test_keine_positionen_ist_fehler(rechnung):
    leer = dataclasses.replace(rechnung, positionen=())
    with pytest.raises(ValueError):
        berechne_summen(leer)
