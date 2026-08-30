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
from rechnungsblatt_kern.summen import rabatt_aus_prozent


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


# ---------------------------------------------------------------- Prozentrabatt

def test_prozentrabatt_wird_zu_betrag(rechnung):
    """10 % auf 200,00 € (8 Std. à 25,00) sind 20,00 €."""
    mit = dataclasses.replace(rechnung, rabatt_prozent=Decimal("10"))
    summen = berechne_summen(mit)
    assert summen.rabatt == Decimal("20.00")
    assert summen.steuerbasis == Decimal("180.00")
    assert summen.steuer == Decimal("34.20")


def test_prozentrabatt_rundet_kaufmaennisch(rechnung):
    """10 % auf 1.234,56 € = 123,456 → 123,46 €; die Summen bleiben exakt."""
    mit = dataclasses.replace(
        rechnung,
        positionen=(_position("1234.56"),),
        rabatt_prozent=Decimal("10"),
    )
    summen = berechne_summen(mit)
    assert summen.rabatt == Decimal("123.46")
    assert summen.steuerbasis + summen.rabatt == summen.zeilensumme


def test_rabatt_betrag_schlaegt_prozent(rechnung):
    """Sind beide gesetzt, gilt der Betrag — er ist die maßgebliche Größe."""
    mit = dataclasses.replace(
        rechnung, rabatt_betrag=Decimal("5.00"), rabatt_prozent=Decimal("10")
    )
    assert berechne_summen(mit).rabatt == Decimal("5.00")


def test_prozentrabatt_verteilt_sich_auf_koerbe(rechnung):
    """Bei gemischten Sätzen wird der errechnete Betrag anteilig verteilt."""
    mit = dataclasses.replace(
        rechnung,
        positionen=(
            _position("800.00"),
            _position("200.00", steuer=Steuerkategorie.UST_7),
        ),
        rabatt_prozent=Decimal("10"),
    )
    summen = berechne_summen(mit)
    assert summen.rabatt == Decimal("100.00")
    assert sum(korb.rabatt for korb in summen.koerbe) == Decimal("100.00")


def test_prozentrabatt_ueber_hundert_scheitert():
    with pytest.raises(ValueError, match="100"):
        rabatt_aus_prozent(Decimal("101"), Decimal("1000.00"))


def test_prozentrabatt_negativ_scheitert():
    with pytest.raises(ValueError, match="negativ"):
        rabatt_aus_prozent(Decimal("-1"), Decimal("1000.00"))
