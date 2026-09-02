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


# ---------------------------------------------------------------------------
# Managed Payments
# ---------------------------------------------------------------------------
#
# Am 02.09.2026 scheiterte jede Aufladung im Produktivbetrieb:
#
#     Invalid line_items[0]: the product tax code is missing. … Product tax
#     code is required for Managed Payments, which is enabled by default on
#     your account.
#
# Stripe hatte "Managed Payments" auf dem Konto als Vorgabe aktiviert. Dabei
# wird Stripe Merchant of Record: Es berechnet Umsatzsteuer und versendet
# eigene Rechnungen. Für einen Kleinunternehmer nach § 19 UStG ist das
# ausgeschlossen — er weist keine Umsatzsteuer aus.
#
# Diese Tests halten fest, dass beide Zahlungswege es ausdrücklich
# abschalten. Sich auf die Kontoeinstellung zu verlassen wäre zu wenig:
# Sie hat sich schon einmal von selbst geändert.


class _Person:
    id = 2
    email = "kunde@example.de"
    tarif = "kostenlos"


class _Tarif:
    schluessel = "werkstatt"
    name = "Werkstatt"
    sichtbar = True
    stripe_preis = "price_test"


@pytest.fixture
def gesendet(monkeypatch):
    """Fängt ab, was an Stripe gehen würde."""
    felder: dict = {}

    class Sitzung:
        id = "cs_test"
        url = "https://checkout.stripe.com/test"

    def abfangen(**gesehen):
        felder.clear()
        felder.update(gesehen)
        return Sitzung()

    monkeypatch.setattr(bezahlen.stripe.checkout.Session, "create",
                        staticmethod(abfangen))
    monkeypatch.setattr(bezahlen, "_schluessel", lambda: "sk_test_x")
    monkeypatch.setattr(bezahlen, "_kunde", lambda person: "cus_test")
    monkeypatch.setattr(bezahlen, "aufladungen", lambda: [1000])
    monkeypatch.setattr(bezahlen, "frei_erlaubt", lambda: False)
    return felder


def test_guthaben_schaltet_managed_payments_aus(gesendet):
    """Sonst berechnet Stripe Umsatzsteuer, die es nicht geben darf."""
    bezahlen.sitzung_guthaben(_Person(), 1000, "https://rechnungsblatt.de")

    assert gesendet["managed_payments"] == {"enabled": False}


def test_guthaben_traegt_einen_steuercode(gesendet):
    """Ohne ihn wies Stripe die ganze Sitzung ab (400)."""
    bezahlen.sitzung_guthaben(_Person(), 1000, "https://rechnungsblatt.de")

    produkt = gesendet["line_items"][0]["price_data"]["product_data"]
    assert produkt["tax_code"] == bezahlen.STEUERCODE
    assert produkt["tax_code"].startswith("txcd_")


def test_abo_schaltet_managed_payments_aus(gesendet, monkeypatch):
    monkeypatch.setattr(bezahlen.konten, "tarif", lambda s: _Tarif())

    bezahlen.sitzung_abo(_Person(), "werkstatt", "https://rechnungsblatt.de")

    assert gesendet["managed_payments"] == {"enabled": False}


def test_managed_payments_ist_wirklich_aus():
    """Ein Vertipper in der Konstante fällt sonst niemandem auf.

    ``{"enabled": True}`` sähe im Diff harmlos aus und hätte teure
    Folgen — 3,5 % Aufschlag und Umsatzsteuer auf jeder Zahlung.
    """
    assert bezahlen.MANAGED_PAYMENTS == {"enabled": False}


# ---------------------------------------------------------------------------
# Kündigung
# ---------------------------------------------------------------------------
#
# Am 02.09.2026 fiel auf: Ein in Stripe gekündigtes Abo hinterließ im
# System keine Spur. Der Grund ist Stripes Ablauf — es beendet ein Abo
# nicht sofort, sondern setzt `cancel_at_period_end` und lässt es bis zum
# Periodenende laufen. `customer.subscription.deleted` kommt erst dann,
# im Beispielfall vier Wochen später.
#
# Gemeldet wird die Kündigung sofort, aber als
# `customer.subscription.updated` — und dieses Ereignis wurde nicht
# behandelt. Im Konto stand weiter „läuft", und der Kunde musste glauben,
# seine Kündigung sei nicht angekommen.


def _kuendigungs_ereignis(endet_bei: int | None, kunde: str = "cus_test") -> dict:
    """Ein `customer.subscription.updated` wie Stripe es schickt."""
    return {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_test",
            "customer": kunde,
            "cancel_at": endet_bei,
            "cancel_at_period_end": endet_bei is not None,
            "current_period_end": endet_bei,
        }},
    }


@pytest.fixture
def gemerkt(monkeypatch):
    """Fängt ab, was in der Datenbank landen würde."""
    aufrufe: list = []
    monkeypatch.setattr(bezahlen.konten, "merke_kuendigung",
                        lambda nutzer_id, endet: aufrufe.append((nutzer_id, endet)))
    monkeypatch.setattr(bezahlen, "_nutzer_aus_ereignis", lambda objekt: _Person())
    return aufrufe


def test_kuendigung_wird_vorgemerkt(gemerkt):
    """Der Fall aus dem Betrieb: gekündigt, läuft aber noch."""
    # 02.10.2026, 08:39 UTC — wie im Stripe-Dashboard des Falls,
    # der das hier ausgelöst hat.
    endet = 1790930340

    bezahlen.verarbeite(_kuendigungs_ereignis(endet))

    assert len(gemerkt) == 1
    nutzer_id, zeitpunkt = gemerkt[0]
    assert nutzer_id == 2
    assert zeitpunkt is not None
    # Mit Zeitzone, sonst ist der Zeitpunkt beim Anzeigen wertlos.
    assert zeitpunkt.tzinfo is not None
    assert zeitpunkt.year == 2026 and zeitpunkt.month == 10


def test_zuruecknahme_loescht_den_vermerk(gemerkt):
    """In Stripe lässt sich eine Kündigung bis zum Periodenende widerrufen.

    Bliebe der Vermerk stehen, zeigte das Konto ein Abo als gekündigt,
    das längst weiterläuft.
    """
    bezahlen.verarbeite(_kuendigungs_ereignis(None))

    assert gemerkt == [(2, None)]


def test_gewoehnliche_aenderung_setzt_keinen_vermerk(gemerkt):
    """Nicht jede Änderung ist eine Kündigung."""
    ereignis = _kuendigungs_ereignis(None)
    ereignis["data"]["object"]["cancel_at_period_end"] = False
    ereignis["data"]["object"]["current_period_end"] = 1790930340

    bezahlen.verarbeite(ereignis)

    assert gemerkt == [(2, None)]


def test_kuendigung_ohne_zuordenbares_konto(monkeypatch):
    """Ein Ereignis zu einem fremden Kunden darf nichts anrichten."""
    monkeypatch.setattr(bezahlen, "_nutzer_aus_ereignis", lambda objekt: None)
    gerufen = []
    monkeypatch.setattr(bezahlen.konten, "merke_kuendigung",
                        lambda *a: gerufen.append(a))

    ergebnis = bezahlen.verarbeite(_kuendigungs_ereignis(1790930340))

    assert gerufen == []
    assert "kein Konto" in ergebnis
