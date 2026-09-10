"""Der zweite Faktor von außen: Einschalten, Anmelden, Aussperren, Zurück.

Die Leitfrage dieser Tests ist nicht „funktioniert TOTP" — das prüft
`test_zweifaktor.py` gegen die Prüfwerte der Norm. Hier geht es darum,
dass der zweite Faktor **niemanden endgültig aussperrt** und dass er sich
nicht mit einer offenen Sitzung allein abschalten lässt.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main
from rechnungsblatt_web import zweifaktor

from hilfen import lege_kunden_an, melde_an

ZUGANG = ("kundin@example.de", "langgenug12")


@pytest.fixture
def klient(tmp_path, monkeypatch, leere_konten):
    monkeypatch.setattr(main, "DATEN", tmp_path)
    return TestClient(main.app)


@pytest.fixture
def kundin(klient, leere_konten):
    person = lege_kunden_an(leere_konten, *ZUGANG)
    melde_an(klient, *ZUGANG)
    return person


def schalte_ein(klient, leere_konten, nutzer_id):
    """Den ganzen Weg gehen: Geheimnis holen, Code vorzeigen, scharf."""
    start = klient.post("/api/ich/mfa/start")
    assert start.status_code == 200, start.text
    geheimnis = start.json()["geheimnis"]

    ein = klient.post("/api/ich/mfa/ein",
                      json={"code": zweifaktor.code_jetzt(geheimnis)})
    assert ein.status_code == 200, ein.text
    return geheimnis, ein.json()["ersatzcodes"]


# --- Einschalten -----------------------------------------------------

def test_start_liefert_geheimnis_und_bild(klient, kundin):
    daten = klient.post("/api/ich/mfa/start").json()

    assert len(daten["geheimnis"]) == 32
    assert daten["adresse"].startswith("otpauth://totp/")
    assert daten["qr"].startswith("<svg")


def test_ohne_richtigen_code_wird_nicht_scharf(klient, kundin, leere_konten):
    klient.post("/api/ich/mfa/start")
    antwort = klient.post("/api/ich/mfa/ein", json={"code": "000000"})

    assert antwort.status_code == 422
    assert antwort.json()["detail"]["code"] == "code_falsch"
    # Und das Konto bleibt offen — sonst wäre der Kunde ausgesperrt, weil
    # seine App den QR-Code nicht sauber gelesen hat.
    assert klient.get("/api/status").status_code == 200


def test_einschalten_gibt_ersatzcodes_heraus(klient, kundin, leere_konten):
    _, codes = schalte_ein(klient, leere_konten, kundin.id)

    assert len(codes) == 8
    assert klient.get("/api/status").json()["konto"]["mfa_aktiv"] is True
    assert klient.get("/api/status").json()["konto"]["mfa_ersatzcodes_offen"] == 8


# --- Anmelden --------------------------------------------------------

def test_ohne_code_keine_anmeldung(klient, kundin, leere_konten):
    schalte_ein(klient, leere_konten, kundin.id)
    klient.post("/api/abmelden")

    antwort = klient.post("/api/anmelden",
                          json={"email": ZUGANG[0], "passwort": ZUGANG[1]})

    assert antwort.status_code == 401
    assert antwort.json()["detail"]["code"] == "mfa_noetig"


def test_mit_code_geht_es(klient, kundin, leere_konten):
    geheimnis, _ = schalte_ein(klient, leere_konten, kundin.id)
    klient.post("/api/abmelden")

    antwort = klient.post("/api/anmelden", json={
        "email": ZUGANG[0], "passwort": ZUGANG[1],
        "code": zweifaktor.code_jetzt(geheimnis),
    })

    assert antwort.status_code == 200, antwort.text


def test_falsches_passwort_bleibt_falsch(klient, kundin, leere_konten):
    """Der Code rettet kein falsches Passwort."""
    geheimnis, _ = schalte_ein(klient, leere_konten, kundin.id)
    klient.post("/api/abmelden")

    antwort = klient.post("/api/anmelden", json={
        "email": ZUGANG[0], "passwort": "ganzfalsch99",
        "code": zweifaktor.code_jetzt(geheimnis),
    })
    assert antwort.status_code == 401


# --- Ersatzcodes -----------------------------------------------------

def test_ersatzcode_traegt_einmal(klient, kundin, leere_konten):
    _, codes = schalte_ein(klient, leere_konten, kundin.id)
    klient.post("/api/abmelden")

    erste = klient.post("/api/anmelden", json={
        "email": ZUGANG[0], "passwort": ZUGANG[1], "code": codes[0],
    })
    assert erste.status_code == 200, "der Ersatzcode muss hereinlassen"
    assert erste.json()["mfa_ersatzcodes_offen"] == 7

    klient.post("/api/abmelden")
    zweite = klient.post("/api/anmelden", json={
        "email": ZUGANG[0], "passwort": ZUGANG[1], "code": codes[0],
    })
    assert zweite.status_code == 401, "und danach nie wieder"


# --- Abschalten ------------------------------------------------------

def test_abschalten_verlangt_das_passwort(klient, kundin, leere_konten):
    """Eine offene Sitzung allein darf nicht genügen.

    Sonst reichte ein unbeaufsichtigter Rechner, um den zweiten Faktor
    loszuwerden — und er wäre seinen Zweck los.
    """
    schalte_ein(klient, leere_konten, kundin.id)

    assert klient.post("/api/ich/mfa/aus", json={"passwort": "falsch"}).status_code == 422
    assert klient.get("/api/status").json()["konto"]["mfa_aktiv"] is True

    assert klient.post("/api/ich/mfa/aus", json={"passwort": ZUGANG[1]}).status_code == 200
    assert klient.get("/api/status").json()["konto"]["mfa_aktiv"] is False


def test_betreiber_kann_zuruecksetzen_ohne_an_daten_zu_kommen(
    klient, kundin, leere_konten
):
    """Der Kundendienstfall: Telefon weg, Ersatzcodes weg.

    Der Betreiber setzt zurück — und sieht trotzdem keine Rechnung, denn
    der Datenschlüssel hängt am Passwort und nicht am zweiten Faktor.
    """
    schalte_ein(klient, leere_konten, kundin.id)
    klient.post("/api/abmelden")

    lege_kunden_an(leere_konten, "chef@example.de", "langgenug12")
    verwalter = leere_konten.nutzer_zu_email("chef@example.de")
    leere_konten.setze_rolle(verwalter.id, leere_konten.ROLLE_ADMIN)
    melde_an(klient, "chef@example.de", "langgenug12")

    antwort = klient.post(f"/api/verwaltung/nutzer/{kundin.id}/mfa-aus")
    assert antwort.status_code == 200, antwort.text

    klient.post("/api/abmelden")
    wieder = klient.post("/api/anmelden",
                         json={"email": ZUGANG[0], "passwort": ZUGANG[1]})
    assert wieder.status_code == 200, "ohne zweiten Faktor wieder herein"
