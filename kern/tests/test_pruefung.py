import dataclasses
import datetime as dt
from decimal import Decimal

import pytest

from rechnungsblatt_kern import (
    Anschrift,
    Belegtyp,
    Empfaenger,
    Position,
    Profil,
    Steuerkategorie,
    UngueltigeRechnung,
    Zeitraum,
    erzwinge_paragraph14,
    pruefe_paragraph14,
)


def codes(befunde) -> set[str]:
    return {befund.code for befund in befunde}


def test_vollstaendige_rechnung_ohne_befund(rechnung, stammdaten):
    assert pruefe_paragraph14(rechnung, stammdaten) == []


def test_erzwingen_wirft_bei_befunden(rechnung, stammdaten):
    kaputt = dataclasses.replace(rechnung, nummer="")
    with pytest.raises(UngueltigeRechnung) as fehler:
        erzwinge_paragraph14(kaputt, stammdaten)
    assert "R1" in str(fehler.value)


def test_fehlende_rechnungsnummer(rechnung, stammdaten):
    kaputt = dataclasses.replace(rechnung, nummer="  ")
    assert "R1" in codes(pruefe_paragraph14(kaputt, stammdaten))


def test_leistungsdatum_oder_zeitraum_ist_pflicht(rechnung, stammdaten):
    ohne = dataclasses.replace(rechnung, leistungsdatum=None, leistungszeitraum=None)
    assert "R3" in codes(pruefe_paragraph14(ohne, stammdaten))


def test_steuernummer_oder_ustid_ist_pflicht(rechnung, stammdaten):
    ohne = dataclasses.replace(stammdaten, steuernummer=None, ust_idnr=None)
    assert "S3" in codes(pruefe_paragraph14(rechnung, ohne))


def test_nur_steuernummer_reicht(rechnung, stammdaten):
    nur_stnr = dataclasses.replace(stammdaten, ust_idnr=None)
    assert pruefe_paragraph14(rechnung, nur_stnr) == []


def test_unvollstaendige_empfaengeranschrift(rechnung, stammdaten):
    kaputt = dataclasses.replace(
        rechnung,
        empfaenger=Empfaenger(
            name="Kunde", anschrift=Anschrift(strasse="", plz="95028", ort="Hof")
        ),
    )
    assert "E2" in codes(pruefe_paragraph14(kaputt, stammdaten))


def test_iban_pruefsumme(rechnung, stammdaten):
    falsch = dataclasses.replace(stammdaten, iban="DE02780500000001234567")
    assert "S6" in codes(pruefe_paragraph14(rechnung, falsch))
    fehlt = dataclasses.replace(stammdaten, iban="")
    assert "S5" in codes(pruefe_paragraph14(rechnung, fehlt))


def test_iban_mit_leerzeichen_ist_ok(rechnung, stammdaten):
    assert stammdaten.iban == "DE14 7805 0000 0001 2345 67"
    assert pruefe_paragraph14(rechnung, stammdaten) == []


def test_position_ohne_bezeichnung_und_menge_null(rechnung, stammdaten):
    kaputt = dataclasses.replace(
        rechnung,
        positionen=(
            Position(
                bezeichnung=" ",
                menge=Decimal("0"),
                einheit="",
                einzelpreis=Decimal("-1"),
                steuer=Steuerkategorie.UST_19,
            ),
        ),
    )
    gefunden = codes(pruefe_paragraph14(kaputt, stammdaten))
    assert {"P1", "P2", "P3", "P4"} <= gefunden


def test_keine_positionen(rechnung, stammdaten):
    leer = dataclasses.replace(rechnung, positionen=())
    assert "P0" in codes(pruefe_paragraph14(leer, stammdaten))


def test_kleinunternehmer_darf_keine_ust_ausweisen(rechnung, stammdaten):
    klein = dataclasses.replace(stammdaten, kleinunternehmer=True)
    assert "K1" in codes(pruefe_paragraph14(rechnung, klein))


def test_kleinunternehmer_kategorie_nur_mit_stammdaten_flag(rechnung, stammdaten):
    kaputt = dataclasses.replace(
        rechnung,
        positionen=(
            dataclasses.replace(
                rechnung.positionen[0], steuer=Steuerkategorie.KLEINUNTERNEHMER
            ),
        ),
    )
    assert "K2" in codes(pruefe_paragraph14(kaputt, stammdaten))


def test_kleinunternehmer_stimmig_ohne_befund(rechnung, stammdaten):
    klein_stamm = dataclasses.replace(stammdaten, kleinunternehmer=True)
    klein_rechnung = dataclasses.replace(
        rechnung,
        positionen=(
            dataclasses.replace(
                rechnung.positionen[0], steuer=Steuerkategorie.KLEINUNTERNEHMER
            ),
        ),
    )
    assert pruefe_paragraph14(klein_rechnung, klein_stamm) == []


def test_reverse_charge_braucht_beide_ustidnr(rechnung, stammdaten):
    rc = dataclasses.replace(
        rechnung,
        positionen=(
            dataclasses.replace(
                rechnung.positionen[0], steuer=Steuerkategorie.REVERSE_CHARGE
            ),
        ),
    )
    assert "RC1" in codes(pruefe_paragraph14(rc, stammdaten))
    ohne_eigene = dataclasses.replace(stammdaten, ust_idnr=None)
    assert "RC2" in codes(pruefe_paragraph14(rc, ohne_eigene))
    mit_kunde = dataclasses.replace(
        rc,
        empfaenger=dataclasses.replace(rc.empfaenger, ust_idnr="ATU12345678"),
    )
    assert pruefe_paragraph14(mit_kunde, stammdaten) == []


def test_gutschrift_braucht_bezug(rechnung, stammdaten):
    gutschrift = dataclasses.replace(rechnung, typ=Belegtyp.GUTSCHRIFT)
    assert "G1" in codes(pruefe_paragraph14(gutschrift, stammdaten))
    mit_bezug = dataclasses.replace(
        gutschrift, bezugs_nummer="RE-2026-0041", bezugs_datum=dt.date(2026, 8, 1)
    )
    assert pruefe_paragraph14(mit_bezug, stammdaten) == []


def test_korrektur_braucht_bezug(rechnung, stammdaten):
    korrektur = dataclasses.replace(rechnung, typ=Belegtyp.KORREKTUR)
    assert "G1" in codes(pruefe_paragraph14(korrektur, stammdaten))


def test_zeitraum_rueckwaerts(rechnung, stammdaten):
    kaputt = dataclasses.replace(
        rechnung,
        leistungsdatum=None,
        leistungszeitraum=Zeitraum(von=dt.date(2026, 8, 31), bis=dt.date(2026, 8, 1)),
    )
    assert "R4" in codes(pruefe_paragraph14(kaputt, stammdaten))


def test_xrechnung_verlangt_leitweg_id_kontakt_und_email(rechnung, stammdaten):
    befunde = codes(pruefe_paragraph14(rechnung, stammdaten, Profil.XRECHNUNG))
    assert "X1" in befunde  # keine Leitweg-ID
    assert "X3" in befunde  # keine Empfänger-E-Mail

    ohne_kontakt = dataclasses.replace(stammdaten, kontakt_telefon=None)
    befunde = codes(pruefe_paragraph14(rechnung, ohne_kontakt, Profil.XRECHNUNG))
    assert "X2" in befunde

    behoerde = dataclasses.replace(
        rechnung,
        empfaenger=dataclasses.replace(
            rechnung.empfaenger,
            leitweg_id="04011000-1234512345-06",
            email="rechnungseingang@behoerde.example.de",
        ),
    )
    assert pruefe_paragraph14(behoerde, stammdaten, Profil.XRECHNUNG) == []


def test_en16931_verlangt_keine_leitweg_id(rechnung, stammdaten):
    assert pruefe_paragraph14(rechnung, stammdaten, Profil.EN16931) == []


def test_einzelpreis_mit_drei_nachkommastellen_wird_beanstandet(rechnung, stammdaten):
    """Sonst widersprechen sich Einzelpreis und Positionsbetrag im XML.

    Der Preis wird im XML auf zwei Stellen ausgewiesen, der Betrag aber
    aus dem ungerundeten Wert gerechnet. Bei 0,333 € × 3 rechnet ein
    Prüfer 0,33 × 3 = 0,99 gegen einen ausgewiesenen Betrag von 1,00 —
    und beanstandet die Rechnung.
    """
    krumm = dataclasses.replace(
        rechnung,
        positionen=(
            Position(bezeichnung="Stunden", menge=Decimal("3"), einheit="HUR",
                     einzelpreis=Decimal("0.333"),
                     steuer=Steuerkategorie.UST_19),
        ),
    )
    assert "P5" in codes(pruefe_paragraph14(krumm, stammdaten))

    # Zwei Stellen bleiben erlaubt — auch als glatte Zahl.
    glatt = dataclasses.replace(
        rechnung,
        positionen=(
            Position(bezeichnung="Stunden", menge=Decimal("3"), einheit="HUR",
                     einzelpreis=Decimal("0.33"),
                     steuer=Steuerkategorie.UST_19),
        ),
    )
    assert "P5" not in codes(pruefe_paragraph14(glatt, stammdaten))
