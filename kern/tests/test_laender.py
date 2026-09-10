"""Die Ländertabelle — vor allem: dass sie niemanden fälschlich abweist.

**Warum jede Nummer einzeln geprüft wird.** Die Muster in ``laender.py``
sind der Teil, an dem ich mich irren kann, und ein zu enges Muster wäre
schlimmer als gar keines: Ein Kunde mit gültiger Nummer könnte dann nicht
mehr abrechnen. Deshalb steht hier für jeden der 27 Mitgliedstaaten eine
formgerechte Nummer — schlägt eines der Muster hier an, ist die Tabelle
kaputt und nicht der Kunde.
"""

from __future__ import annotations

import pytest

from rechnungsblatt_kern import laender

# Je Land eine formgerechte Nummer. Die Ziffern sind erfunden, die FORM ist
# es nicht — sie folgt der Beschreibung des jeweiligen Mitgliedstaats.
BEISPIELE = {
    "BE": "BE0123456789",
    "BG": "BG123456789",
    "CZ": "CZ12345678",
    "DK": "DK12345678",
    "DE": "DE123456789",
    "EE": "EE123456789",
    "IE": "IE1234567A",
    "GR": "EL123456789",          # Achtung: EL, nicht GR
    "ES": "ESA1234567A",
    "FR": "FR53987550159",
    "HR": "HR12345678901",
    "IT": "IT12345678901",
    "CY": "CY12345678L",
    "LV": "LV12345678901",
    "LT": "LT123456789",
    "LU": "LU12345678",
    "HU": "HU12345678",
    "MT": "MT12345678",
    "NL": "NL123456789B01",
    "AT": "ATU12345678",          # einziges Land mit Buchstabe hinterm Präfix
    "PL": "PL1234567890",
    "PT": "PT123456789",
    "RO": "RO1234567890",
    "SI": "SI12345678",
    "SK": "SK1234567890",
    "FI": "FI12345678",
    "SE": "SE123456789001",
}


def test_alle_mitgliedstaaten_sind_erfasst():
    assert len(laender.EU_LAENDER) == 27
    assert set(BEISPIELE) == set(laender.EU_LAENDER)


@pytest.mark.parametrize("land,nummer", sorted(BEISPIELE.items()))
def test_beispielnummer_wird_angenommen(land, nummer):
    """Kein Muster darf eine formgerechte Nummer seines Landes abweisen."""
    assert laender.praefix_passt(nummer, land) is True, "Präfix"
    assert laender.muster_passt(nummer, land) is True, "Muster"


@pytest.mark.parametrize("nummer", [
    "IE1234567A",       # alte Form: sieben Ziffern, ein Buchstabe
    "IE1A23456B",       # alte Form mit Buchstabe an zweiter Stelle
    "IE1234567AB",      # neue Form mit zwei Buchstaben
])
def test_irland_kennt_drei_formen(nummer):
    assert laender.muster_passt(nummer, "IE") is True


def test_zweitform_litauen():
    assert laender.muster_passt("LT123456789012", "LT") is True


# --- Die Fallen ------------------------------------------------------

def test_griechenland_traegt_el_nicht_gr():
    """Wer Präfix und Länderkennzeichen gleichsetzt, weist Griechenland ab."""
    assert laender.praefix_passt("EL123456789", "GR") is True
    assert laender.praefix_passt("GR123456789", "GR") is False


def test_leerzeichen_und_punkte_stoeren_nicht():
    """Kunden schreiben ihre Nummer, wie sie wollen."""
    assert laender.muster_passt("FR 53 987 550 159", "FR") is True
    assert laender.muster_passt("ATU 1234 5678", "AT") is True


def test_falsches_land_faellt_auf():
    assert laender.praefix_passt("FR53987550159", "DE") is False


# --- Drittland: schweigen statt raten --------------------------------

def test_schweiz_wird_nicht_beurteilt():
    """Die Schweiz führt eine UID, keine USt-IdNr.

    Sie steht nicht in der Tabelle, und deshalb sagt die Prüfung dazu
    nichts — statt eine Nummer abzulehnen, deren Form sie gar nicht kennt.
    """
    assert laender.ist_eu("CH") is False
    assert laender.erlaubte_praefixe("CH") == ()
    assert laender.praefix_passt("CHE-123.456.789 MWST", "CH") is None
    assert laender.muster_passt("CHE-123.456.789 MWST", "CH") is None


def test_nordirland_traegt_xi_liegt_aber_in_gb():
    """XI gilt nur für Waren; für sonstige Leistungen ist GB Drittland."""
    assert laender.ist_eu("GB") is False
    assert laender.praefix_passt("XI123456789", "GB") is True
    assert laender.praefix_passt("GB123456789", "GB") is True


def test_deutschland_ist_eu_aber_kein_eu_ausland():
    assert laender.ist_eu("DE") is True
    assert laender.ist_eu_ausland("DE") is False
    assert laender.ist_eu_ausland("FR") is True
