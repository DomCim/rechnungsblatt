"""Der Aufladebetrag — vorgegeben oder frei, aber nie beliebig.

**Warum das geprüft wird.** Der Betrag kommt aus dem Browser. Ohne
Sperre könnte ein gebastelter Aufruf ein Guthaben von einem Cent kaufen
— oder mit einer negativen Zahl Stripe mit Unsinn füttern.

Bis September 2026 war das eine Zeile: ``betrag_cent not in
aufladungen()``. Mit dem freien Betrag ist die Prüfung länger geworden,
also gehört sie unter Test.
"""

from __future__ import annotations

import pytest

from rechnungsblatt_web import bezahlen


@pytest.fixture
def vorgaben(monkeypatch):
    """Drei feste Beträge, freier Betrag aus — der Stand vor der Änderung."""
    monkeypatch.setattr(bezahlen, "aufladungen", lambda: [1000, 2000, 3000])
    monkeypatch.setattr(bezahlen, "frei_erlaubt", lambda: False)


@pytest.fixture
def mit_frei(monkeypatch):
    monkeypatch.setattr(bezahlen, "aufladungen", lambda: [1000, 2000, 3000])
    monkeypatch.setattr(bezahlen, "frei_erlaubt", lambda: True)


def test_vorgegebener_betrag_geht(vorgaben):
    for cent in (1000, 2000, 3000):
        bezahlen.pruefe_betrag(cent)          # wirft nicht


def test_ohne_freigabe_nur_die_vorgaben(vorgaben):
    """Der Stand vor der Änderung darf sich nicht verschoben haben."""
    for cent in (1, 500, 1500, 999_999):
        with pytest.raises(bezahlen.BezahlFehler):
            bezahlen.pruefe_betrag(cent)


def test_ein_cent_wird_abgewiesen(mit_frei):
    """Der eigentliche Angriff: Guthaben für einen Cent kaufen."""
    with pytest.raises(bezahlen.BezahlFehler):
        bezahlen.pruefe_betrag(1)


def test_negativer_betrag_wird_abgewiesen(mit_frei):
    """Ein negativer Betrag würde Stripe mit Unsinn füttern."""
    with pytest.raises(bezahlen.BezahlFehler):
        bezahlen.pruefe_betrag(-5000)


def test_null_wird_abgewiesen(mit_frei):
    with pytest.raises(bezahlen.BezahlFehler):
        bezahlen.pruefe_betrag(0)


def test_freier_betrag_in_den_grenzen(mit_frei):
    bezahlen.pruefe_betrag(bezahlen.FREI_MINDESTENS)
    bezahlen.pruefe_betrag(5000)
    bezahlen.pruefe_betrag(bezahlen.FREI_HOECHSTENS)


def test_knapp_unter_der_untergrenze(mit_frei):
    """Die Grenze selbst gilt, ein Cent darunter nicht mehr."""
    with pytest.raises(bezahlen.BezahlFehler) as fehler:
        bezahlen.pruefe_betrag(bezahlen.FREI_MINDESTENS - 1)
    # Die Meldung soll sagen, warum — nicht nur „ungültig".
    assert "Zahlungsgebühr" in str(fehler.value)


def test_ueber_der_obergrenze(mit_frei):
    """Schutz vor dem Vertipper: 50000 statt 50,00."""
    with pytest.raises(bezahlen.BezahlFehler):
        bezahlen.pruefe_betrag(bezahlen.FREI_HOECHSTENS + 1)


def test_vorgabe_gilt_auch_unter_der_untergrenze(monkeypatch):
    """Ein bewusst gesetzter Kleinbetrag bleibt erlaubt.

    Trägt der Betreiber 2 € in die Liste ein, ist das seine Entscheidung
    — die Untergrenze gilt nur für das freie Feld.
    """
    monkeypatch.setattr(bezahlen, "aufladungen", lambda: [200])
    monkeypatch.setattr(bezahlen, "frei_erlaubt", lambda: True)

    bezahlen.pruefe_betrag(200)               # wirft nicht


def test_grenzen_sind_plausibel():
    """Ein Vertipper in den Konstanten fällt sonst niemandem auf."""
    assert 0 < bezahlen.FREI_MINDESTENS < bezahlen.FREI_HOECHSTENS
    # Unter 25 Cent Stripe-Grundgebühr wäre jede Aufladung ein Verlust.
    assert bezahlen.FREI_MINDESTENS >= 100


@pytest.mark.parametrize("wert,erwartet", [
    ("1", True), ("ja", True), ("true", True), ("an", True),
    ("JA", True), (" 1 ", True),
    ("0", False), ("", False), ("nein", False), ("aus", False),
])
def test_freigabe_wird_aus_der_einstellung_gelesen(monkeypatch, wert, erwartet):
    """Der Schalter schreibt "1" oder "0" — beides muss stimmen.

    Leer heißt in der Verwaltung „entfernen"; deshalb schreibt die
    Oberfläche "0" und nicht "". Ein leerer Wert muss trotzdem als aus
    gelten, sonst wäre ein gelöschtes Feld plötzlich an.
    """
    monkeypatch.setattr(bezahlen, "_zugang",
                        lambda: {"stripe_freier_betrag": wert})

    assert bezahlen.frei_erlaubt() is erwartet
