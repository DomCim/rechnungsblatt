"""Rechnungen ins Ausland: Land, Nummer, Kategorie.

Der Leitgedanke dieser Tests: **widersprechen, wo es unmöglich ist —
nachfragen, wo es nur ungewöhnlich ist.** Ein Befund, der bei einer
legitimen Rechnung anschlägt, ist schlimmer als keiner; danach klickt man
alle weg. Deshalb steht hier zu jeder blockierenden Regel auch der Fall,
in dem sie schweigen muss.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from rechnungsblatt_kern import (
    Anschrift,
    Empfaenger,
    Position,
    Steuerkategorie,
    pruefe_paragraph14,
)


def codes(befunde) -> set[str]:
    return {b.code for b in befunde}


def blockierend(befunde) -> set[str]:
    return {b.code for b in befunde if b.blockierend}


def mit_empfaenger(rechnung, *, land, ust_idnr=None, kategorie=None):
    """Rechnung mit Empfänger in einem bestimmten Land."""
    empfaenger = Empfaenger(
        name="Next-Concept SAS",
        anschrift=Anschrift(
            strasse="24 avenue Georges Clemenceau",
            plz="67630",
            ort="Lauterbourg",
            land=land,
        ),
        ust_idnr=ust_idnr,
    )
    geaendert = dataclasses.replace(rechnung, empfaenger=empfaenger)
    if kategorie is not None:
        geaendert = dataclasses.replace(
            geaendert,
            positionen=[
                dataclasses.replace(p, steuer=kategorie) for p in rechnung.positionen
            ],
        )
    return geaendert


# --- Länderkennzeichen (E3) ------------------------------------------

def test_ausgeschriebenes_land_blockiert(rechnung, stammdaten):
    """„Frankreich“ landet sonst als CountryID im XML und macht es ungültig."""
    kaputt = mit_empfaenger(rechnung, land="Frankreich")
    assert "E3" in blockierend(pruefe_paragraph14(kaputt, stammdaten))


def test_gueltiges_kennzeichen_schweigt(rechnung, stammdaten):
    for land in ("DE", "FR", "CH", "US"):
        gut = mit_empfaenger(rechnung, land=land)
        assert "E3" not in codes(pruefe_paragraph14(gut, stammdaten)), land


# --- Präfix gegen Land (E4, blockierend) -----------------------------

def test_franzoesische_nummer_an_deutscher_anschrift(rechnung, stammdaten):
    kaputt = mit_empfaenger(rechnung, land="DE", ust_idnr="FR53987550159")
    befunde = pruefe_paragraph14(kaputt, stammdaten)
    assert "E4" in blockierend(befunde)


def test_griechische_nummer_wird_nicht_abgewiesen(rechnung, stammdaten):
    """EL an einer GR-Anschrift ist richtig — die häufigste Fehlmeldung."""
    gut = mit_empfaenger(rechnung, land="GR", ust_idnr="EL123456789")
    assert "E4" not in codes(pruefe_paragraph14(gut, stammdaten))


def test_ohne_nummer_kein_befund(rechnung, stammdaten):
    gut = mit_empfaenger(rechnung, land="FR", ust_idnr=None)
    assert not {"E4", "E5"} & codes(pruefe_paragraph14(gut, stammdaten))


def test_schweizer_uid_wird_nicht_beurteilt(rechnung, stammdaten):
    """Die Schweiz führt eine UID; ihre Form kennt die Tabelle nicht.

    Sie darf deshalb weder beanstandet noch stillschweigend als USt-IdNr.
    behandelt werden.
    """
    gut = mit_empfaenger(rechnung, land="CH", ust_idnr="CHE-123.456.789 MWST")
    assert not {"E4", "E5"} & codes(pruefe_paragraph14(gut, stammdaten))


# --- Muster (E5, nur Hinweis) ----------------------------------------

def test_ungewoehnliche_nummer_ist_nur_ein_hinweis(rechnung, stammdaten):
    """Die Mustertabelle könnte zu eng sein — sie darf niemanden aussperren."""
    seltsam = mit_empfaenger(rechnung, land="FR", ust_idnr="FR1")
    befunde = pruefe_paragraph14(seltsam, stammdaten)

    assert "E5" in codes(befunde)
    assert "E5" not in blockierend(befunde)


def test_hinweis_haelt_die_erzeugung_nicht_auf(rechnung, stammdaten):
    from rechnungsblatt_kern import erzwinge_paragraph14

    seltsam = mit_empfaenger(rechnung, land="FR", ust_idnr="FR1")
    erzwinge_paragraph14(seltsam, stammdaten)      # darf nicht werfen


# --- Kategorie gegen Land (RC3, O1) ----------------------------------

def test_reverse_charge_in_die_schweiz_blockiert(rechnung, stammdaten):
    """Art. 196 MwStSystRL gilt nur im Gemeinschaftsgebiet."""
    kaputt = mit_empfaenger(
        rechnung, land="CH", ust_idnr=None,
        kategorie=Steuerkategorie.REVERSE_CHARGE,
    )
    befunde = pruefe_paragraph14(kaputt, stammdaten)

    assert "RC3" in blockierend(befunde)
    text = next(b.text for b in befunde if b.code == "RC3")
    assert "Nicht steuerbar" in text and "Ausfuhr" in text


def test_reverse_charge_nach_frankreich_ist_richtig(rechnung, stammdaten):
    gut = mit_empfaenger(
        rechnung, land="FR", ust_idnr="FR53987550159",
        kategorie=Steuerkategorie.REVERSE_CHARGE,
    )
    assert "RC3" not in codes(pruefe_paragraph14(gut, stammdaten))


def test_inlaendisches_reverse_charge_bleibt_erlaubt(rechnung, stammdaten):
    """§ 13b UStG: Bauleistungen im Inland tragen denselben Code AE."""
    gut = mit_empfaenger(
        rechnung, land="DE", ust_idnr="DE123456789",
        kategorie=Steuerkategorie.REVERSE_CHARGE,
    )
    assert "RC3" not in codes(pruefe_paragraph14(gut, stammdaten))


def test_nicht_steuerbar_laesst_sich_nicht_mischen(rechnung, stammdaten):
    """EN 16931 verbietet O neben anderen Kategorien im selben Beleg."""
    gemischt = mit_empfaenger(rechnung, land="CH")
    gemischt = dataclasses.replace(
        gemischt,
        positionen=[
            dataclasses.replace(
                gemischt.positionen[0], steuer=Steuerkategorie.NICHT_STEUERBAR
            ),
            Position(
                bezeichnung="Material",
                menge=Decimal("1"),
                einheit="C62",
                einzelpreis=Decimal("100.00"),
                steuer=Steuerkategorie.UST_19,
            ),
        ],
    )
    assert "O1" in blockierend(pruefe_paragraph14(gemischt, stammdaten))


def test_nicht_steuerbar_allein_geht_durch(rechnung, stammdaten):
    """Der Regelfall Schweiz: Dienstleistung, nicht steuerbar, ohne Nummer."""
    gut = mit_empfaenger(
        rechnung, land="CH", ust_idnr=None,
        kategorie=Steuerkategorie.NICHT_STEUERBAR,
    )
    assert pruefe_paragraph14(gut, stammdaten) == []


def test_nicht_steuerbar_im_inland_wird_nicht_beanstandet(rechnung, stammdaten):
    """§ 3a Abs. 3: Ein Grundstück in Wien, abgerechnet an einen Deutschen.

    Der Leistungsort liegt dann im Ausland, obwohl der Empfänger im Inland
    sitzt. Wer das blockierte, läge falsch.
    """
    gut = mit_empfaenger(
        rechnung, land="DE", ust_idnr=None,
        kategorie=Steuerkategorie.NICHT_STEUERBAR,
    )
    assert pruefe_paragraph14(gut, stammdaten) == []


def test_kategorie_o_traegt_den_code_und_einen_grund():
    """BR-O-10 verlangt einen Befreiungsgrund — ohne ihn ist das XML ungültig."""
    kategorie = Steuerkategorie.NICHT_STEUERBAR
    assert kategorie.code == "O"
    assert kategorie.satz == Decimal("0")
    assert kategorie.hinweis and "3a" in kategorie.hinweis
