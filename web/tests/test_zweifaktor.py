"""TOTP gegen die Prüfwerte der Norm.

Selbst gebaute Kryptografie ist nur zu verantworten, wenn sie gegen die
amtlichen Vektoren läuft. RFC 6238, Anhang B: Geheimnis ist die
ASCII-Folge „12345678901234567890“, SHA-1, achtstellige Codes.
"""

from __future__ import annotations

import base64
import time

import pytest

from rechnungsblatt_web import zweifaktor

# RFC 6238, Anhang B — die SHA-1-Zeilen der Tabelle.
RFC_GEHEIMNIS = base64.b32encode(b"12345678901234567890").decode("ascii")
RFC_VEKTOREN = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize("zeitpunkt,erwartet", RFC_VEKTOREN)
def test_rfc6238_pruefwerte(zeitpunkt, erwartet):
    zaehler = zeitpunkt // zweifaktor.SCHRITT
    assert zweifaktor._code_fuer(RFC_GEHEIMNIS, zaehler, stellen=8) == erwartet


# --- Verhalten --------------------------------------------------------

def test_eigener_code_wird_angenommen():
    geheimnis = zweifaktor.neues_geheimnis()
    assert zweifaktor.stimmt(geheimnis, zweifaktor.code_jetzt(geheimnis))


def test_falscher_code_wird_abgewiesen():
    geheimnis = zweifaktor.neues_geheimnis()
    richtig = zweifaktor.code_jetzt(geheimnis)
    falsch = "000000" if richtig != "000000" else "111111"
    assert not zweifaktor.stimmt(geheimnis, falsch)


def test_leerzeichen_stoeren_nicht():
    """Apps zeigen „123 456“ — daran soll niemand scheitern."""
    geheimnis = zweifaktor.neues_geheimnis()
    code = zweifaktor.code_jetzt(geheimnis)
    assert zweifaktor.stimmt(geheimnis, f"{code[:3]} {code[3:]}")


@pytest.mark.parametrize("eingabe", ["", "  ", "12345", "1234567", "abcdef", None])
def test_unsinn_wird_abgewiesen(eingabe):
    assert not zweifaktor.stimmt(zweifaktor.neues_geheimnis(), eingabe)


def test_uhrabweichung_von_einer_halben_minute_geht_durch():
    """Telefonuhren gehen vor und nach."""
    geheimnis = zweifaktor.neues_geheimnis()
    jetzt = time.time()
    for versatz in (-zweifaktor.SCHRITT, 0, zweifaktor.SCHRITT):
        code = zweifaktor.code_jetzt(geheimnis, jetzt + versatz)
        assert zweifaktor.stimmt(geheimnis, code, jetzt), f"Versatz {versatz}s"


def test_zwei_minuten_abweichung_nicht_mehr():
    """Das Fenster darf nicht beliebig weit sein — sonst lebt ein
    abgefangener Code zu lange."""
    geheimnis = zweifaktor.neues_geheimnis()
    jetzt = time.time()
    alt = zweifaktor.code_jetzt(geheimnis, jetzt - 120)
    assert not zweifaktor.stimmt(geheimnis, alt, jetzt)


def test_geheimnis_ist_base32_und_lang_genug():
    geheimnis = zweifaktor.neues_geheimnis()
    assert len(geheimnis) == 32                      # 160 Bit
    assert set(geheimnis) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def test_adresse_traegt_alles_was_die_app_braucht():
    adresse = zweifaktor.otpauth_adresse("kunde@example.de", "ABCDEFGH")

    assert adresse.startswith("otpauth://totp/")
    assert "secret=ABCDEFGH" in adresse
    assert "issuer=Rechnungsblatt" in adresse
    assert "digits=6" in adresse and "period=30" in adresse
    assert "kunde%40example.de" in adresse       # Adresse muss kodiert sein


def test_qr_ist_ein_svg_ohne_fremde_quelle():
    svg = zweifaktor.qr_svg(zweifaktor.otpauth_adresse("a@b.de", "ABCDEFGH"))

    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "<rect" in svg
    assert "http" not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")


def test_ersatzcodes_sind_verschieden_und_lesbar():
    codes = zweifaktor.neue_ersatzcodes()

    assert len(codes) == 8
    assert len(set(codes)) == 8
    for code in codes:
        assert len(code) == 11 and code[5] == "-"
