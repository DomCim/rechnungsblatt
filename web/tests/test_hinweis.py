"""Der Hinweis des Betreibers — und die Drossel dahinter.

Die Karte im Konto ist harmlos: Wer sie sehen will, muss dorthin gehen.
Nach einem erzeugten Beleg erscheint sie ungefragt — deshalb hängt nur
dieser Ort an einem Abstand, und der ist von Haus aus zu. Genau das prüfen
die Tests hier: dass ein Update niemandem ungefragt Werbung einschaltet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main

from hilfen import lege_kunden_an, melde_an

VOLLSTAENDIG = {
    "werbung_an": "1",
    "werbung_titel": "Von der Stange passt selten",
    "werbung_text": "Rechnungsblatt macht **eine Sache** und die richtig.",
    "werbung_knopf": "Mehr über DiD0m",
    "werbung_ziel": "https://did0m.dev",
    "werbung_abstand_tage": "0",
}


@pytest.fixture
def klient(tmp_path, monkeypatch, leere_konten):
    monkeypatch.setattr(main, "DATEN", tmp_path)
    # Einstellungen überleben `leere_konten` — sie sind Stammdaten. Ohne
    # diese Zeile entschiede die Reihenfolge der Tests über das Ergebnis.
    leere_konten.setze_einstellungen(dict(VOLLSTAENDIG, werbung_an="0"))
    return TestClient(main.app)


@pytest.fixture
def angemeldet(klient, leere_konten):
    person = lege_kunden_an(leere_konten, "leser@example.de", "langgenug12")
    melde_an(klient, "leser@example.de", "langgenug12")
    return person


def stelle_ein(konten, **abweichung):
    konten.setze_einstellungen(dict(VOLLSTAENDIG, **abweichung))


def zurueckdatieren(konten, nutzer_id, tage):
    with konten.verbindung() as verbindung:
        verbindung.execute(
            "UPDATE nutzer SET hinweis_gesehen = now() - make_interval(days => %s) "
            "WHERE id = %s",
            (tage, nutzer_id),
        )


# --- Ob überhaupt ----------------------------------------------------

def test_ohne_anmeldung_kein_hinweis(klient):
    assert klient.get("/api/hinweis").status_code == 401


def test_ausgeschaltet_bleibt_verborgen(klient, angemeldet, leere_konten):
    stelle_ein(leere_konten, werbung_an="0")
    assert klient.get("/api/hinweis").json() == {"an": False}


def test_ohne_ziel_bleibt_verborgen(klient, angemeldet, leere_konten):
    """Titel ohne Ziel wäre eine Karte mit einem Knopf ins Nichts."""
    stelle_ein(leere_konten, werbung_ziel="")
    assert klient.get("/api/hinweis").json() == {"an": False}


# --- Die Drossel -----------------------------------------------------

def test_ohne_abstand_nur_im_konto(klient, angemeldet, leere_konten):
    """Der wichtigste Fall: Ein Update schaltet niemandem Werbung ein.

    Der Abstand ist von Haus aus 0. Die Karte steht dann wie bisher im
    Konto und erscheint nach einem Beleg gar nicht.
    """
    stelle_ein(leere_konten, werbung_abstand_tage="0")
    daten = klient.get("/api/hinweis").json()

    assert daten["an"] is True
    assert daten["nach_beleg"] is False


def test_mit_abstand_erscheint_er_einmal(klient, angemeldet, leere_konten):
    stelle_ein(leere_konten, werbung_abstand_tage="30")
    assert klient.get("/api/hinweis").json()["nach_beleg"] is True

    klient.post("/api/hinweis/gesehen")
    assert klient.get("/api/hinweis").json()["nach_beleg"] is False


def test_nach_dem_abstand_wieder(klient, angemeldet, leere_konten):
    stelle_ein(leere_konten, werbung_abstand_tage="30")
    klient.post("/api/hinweis/gesehen")

    zurueckdatieren(leere_konten, angemeldet.id, 29)
    assert klient.get("/api/hinweis").json()["nach_beleg"] is False

    zurueckdatieren(leere_konten, angemeldet.id, 31)
    assert klient.get("/api/hinweis").json()["nach_beleg"] is True


def test_die_drossel_gilt_je_konto(klient, angemeldet, leere_konten):
    """Was der eine gesehen hat, hat der andere nicht gesehen."""
    stelle_ein(leere_konten, werbung_abstand_tage="30")
    klient.post("/api/hinweis/gesehen")
    assert klient.get("/api/hinweis").json()["nach_beleg"] is False

    lege_kunden_an(leere_konten, "zweite@example.de", "langgenug12")
    klient.post("/api/abmelden")
    melde_an(klient, "zweite@example.de", "langgenug12")

    assert klient.get("/api/hinweis").json()["nach_beleg"] is True


def test_unlesbarer_abstand_zeigt_nichts(klient, angemeldet, leere_konten):
    """Ein Tippfehler im Feld darf nicht in Dauerwerbung umschlagen."""
    stelle_ein(leere_konten, werbung_abstand_tage="dreißig")
    assert klient.get("/api/hinweis").json()["nach_beleg"] is False


def test_konto_karte_bleibt_von_der_drossel_unberuehrt(
    klient, angemeldet, leere_konten
):
    """Auch nach dem Anzeigen steht die Karte im Konto weiter.

    Sie ist der Ort, den der Kunde selbst aufsucht — dort gibt es nichts
    zu drosseln.
    """
    stelle_ein(leere_konten, werbung_abstand_tage="30")
    klient.post("/api/hinweis/gesehen")

    daten = klient.get("/api/hinweis").json()
    assert daten["an"] is True
    assert daten["titel"] == "Von der Stange passt selten"
