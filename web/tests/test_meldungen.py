"""Meldungen aus dem Konto — Formular, Bilder, Veröffentlichung.

Die Tests hier prüfen vor allem, was NICHT passieren darf: dass eine
Meldung verschwindet, weil GitHub nicht antwortet; dass die E-Mail-Adresse
im Issue landet; dass über den Bildweg eine fremde Datei ausgeliefert wird.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main
from rechnungsblatt_web import meldungen

from hilfen import lege_kunden_an, melde_an


# Das kleinste gültige PNG: 1×1 Pixel, transparent.
EIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100ffff0300000600"
    "0557bfabd40000000049454e44ae426082"
)


@pytest.fixture
def klient(tmp_path, monkeypatch, leere_konten):
    monkeypatch.setattr(main, "DATEN", tmp_path)
    # `leere_konten` leert Konten, Sitzungen und Verbrauch — die
    # Einstellungen bleiben stehen, sie sind Stammdaten. Ohne diese Zeile
    # entschiede die Reihenfolge der Tests darüber, ob ein GitHub-Zugang
    # eingetragen ist: Ein Lauf allein wäre grün, im Verbund mit dem Test
    # weiter unten rot. Genau so ist es passiert.
    leere_konten.setze_einstellungen({"github_repo": "", "github_token": ""})
    return TestClient(main.app)


@pytest.fixture
def angemeldet(klient, leere_konten):
    person = lege_kunden_an(leere_konten, "melder@example.de", "langgenug12")
    melde_an(klient, "melder@example.de", "langgenug12")
    return person


def schicke(klient, **abweichung):
    daten = {"art": "fehler", "titel": "Knopf tut nichts",
             "text": "Auf Speichern passiert nichts.", "seite": "/app/rechnung"}
    daten.update(abweichung)
    return klient.post("/api/meldung", data=daten)


# --- Annahme ---------------------------------------------------------

def test_ohne_anmeldung_keine_meldung(klient):
    assert schicke(klient).status_code == 401


def test_meldung_wird_gespeichert_auch_ohne_github(klient, angemeldet, leere_konten):
    """Kein GitHub-Zugang eingetragen — die Meldung darf trotzdem nicht weg.

    Das ist der Normalzustand eines frisch aufgesetzten Stacks. Ginge die
    Schilderung dabei verloren, merkte es niemand: Der Kunde bekäme eine
    Bestätigung, und im Adminbereich stünde nichts.
    """
    antwort = schicke(klient)

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["veroeffentlicht"] is False
    gespeichert = leere_konten.meldungen()
    assert len(gespeichert) == 1
    assert gespeichert[0]["titel"] == "Knopf tut nichts"
    # Warum es nicht hinausging, steht am Datensatz — sonst wäre eine
    # misslungene Veröffentlichung von einer gelungenen nicht zu
    # unterscheiden.
    assert gespeichert[0]["issue_fehler"]


def test_unbekannte_art_wird_abgewiesen(klient, angemeldet):
    assert schicke(klient, art="erfunden").status_code == 422


def test_ohne_titel_oder_text_keine_meldung(klient, angemeldet):
    assert schicke(klient, titel="  ").status_code == 422
    assert schicke(klient, text="").status_code == 422


def test_drossel_greift(klient, angemeldet):
    for _ in range(meldungen.MELDUNGEN_JE_STUNDE):
        assert schicke(klient).status_code == 200
    zuviel = schicke(klient)
    assert zuviel.status_code == 429
    assert zuviel.json()["detail"]["code"] == "zu_viele"


# --- Bilder ----------------------------------------------------------

def test_bild_wird_abgelegt_und_ohne_anmeldung_ausgeliefert(
    klient, angemeldet, leere_konten
):
    """Der Bildweg muss offen sein — sonst sieht GitHub nichts.

    Der Bildproxy holt die Datei über das offene Netz, auch bei einem
    privaten Repository. Geschützt ist sie allein durch ihren Zufallsnamen.
    """
    antwort = klient.post(
        "/api/meldung",
        data={"art": "fehler", "titel": "Mit Bild", "text": "Siehe Bild."},
        files=[("bilder", ("schirm.png", EIN_PNG, "image/png"))],
    )
    assert antwort.status_code == 200, antwort.text

    namen = [n for n in leere_konten.meldungen()[0]["bilder"].split("\n") if n]
    assert len(namen) == 1

    klient.post("/api/abmelden")
    bild = klient.get(f"/meldungen/bilder/{namen[0]}")
    assert bild.status_code == 200
    assert bild.headers["content-type"] == "image/png"
    assert bild.content == EIN_PNG


def test_was_kein_bild_ist_wird_abgewiesen(klient, angemeldet, leere_konten):
    antwort = klient.post(
        "/api/meldung",
        data={"art": "fehler", "titel": "Mit Anhang", "text": "Siehe Anhang."},
        files=[("bilder", ("liste.csv", b"Nummer;Betrag\n1;100", "text/csv"))],
    )
    assert antwort.status_code == 422
    # Nichts halb Angelegtes: Die Meldung darf nicht ohne ihr Bild stehen
    # bleiben, sonst fehlte genau das, worum es ging.
    assert leere_konten.meldungen() == []


@pytest.mark.parametrize("name", [
    "../../etc/passwd",
    "..%2f..%2fetc%2fpasswd",
    "gibtesnicht.png",
    "brief.pdf",
])
def test_fremde_pfade_liefern_nichts(klient, name):
    antwort = klient.get(f"/meldungen/bilder/{name}")
    assert antwort.status_code == 404


def test_geloeschtes_konto_nimmt_seine_bilder_mit(
    klient, angemeldet, leere_konten, tmp_path
):
    """„Konto weg, Daten weg" gilt auch für Bildschirmfotos.

    Sie liegen außerhalb des Mandantenverzeichnisses (öffentlich, damit
    GitHub sie einbetten kann) und fallen über ON DELETE CASCADE nur aus
    der Datenbank — die Dateien müssen einzeln weg.
    """
    klient.post(
        "/api/meldung",
        data={"art": "fehler", "titel": "Mit Bild", "text": "Siehe Bild."},
        files=[("bilder", ("schirm.png", EIN_PNG, "image/png"))],
    )
    namen = [n for n in leere_konten.meldungen()[0]["bilder"].split("\n") if n]
    assert (tmp_path / "meldungen" / namen[0]).exists()

    verwalterin = lege_kunden_an(leere_konten, "chefin@example.de", "langgenug12")
    leere_konten.setze_rolle(verwalterin.id, leere_konten.ROLLE_ADMIN)
    klient.post("/api/abmelden")
    melde_an(klient, "chefin@example.de", "langgenug12")

    weg = klient.delete(f"/api/verwaltung/nutzer/{angemeldet.id}")
    assert weg.status_code == 200, weg.text
    assert not (tmp_path / "meldungen" / namen[0]).exists()


# --- Was im Issue steht ----------------------------------------------

def test_im_issue_steht_die_kontonummer_und_nicht_die_adresse():
    koerper = meldungen.baue_koerper(
        "fehler", "Der Knopf tut nichts.", 42, "/app/rechnung",
        "Mozilla/5.0", "sha-abc1234", [],
    )
    assert "#42" in koerper
    assert "@" not in koerper.split("Die E-Mail-Adresse")[0]


def test_bilder_stehen_als_bild_im_issue():
    koerper = meldungen.baue_koerper(
        "gestaltung", "Schief", 7, "", "", "",
        ["https://rechnungsblatt.de/meldungen/bilder/abc.png"],
    )
    assert "![Bild 1](https://rechnungsblatt.de/meldungen/bilder/abc.png)" in koerper


def test_ohne_zugang_sagt_die_ausnahme_wo_er_hingehoert(klient, leere_konten):
    with pytest.raises(meldungen.MeldungFehler) as fehler:
        meldungen.lege_issue_an("Titel", "Text", "fehler")
    assert "Adminbereich" in str(fehler.value)


def test_veroeffentlichung_traegt_die_nummer_nach(
    klient, angemeldet, leere_konten, monkeypatch
):
    """Klappt es, steht die Issue-Nummer am Datensatz.

    Der Aufruf selbst wird ersetzt: Ein Test, der wirklich bei GitHub ein
    Issue anlegt, wäre nach dem zehnten Lauf ein Ärgernis für alle.
    """
    leere_konten.setze_einstellungen({
        "github_repo": "DomCim/rechnungsblatt", "github_token": "gh_test",
    })
    gesehen = {}

    def statt_echt(titel, koerper, label):
        gesehen["titel"] = titel
        gesehen["label"] = label
        return 123, "https://github.com/DomCim/rechnungsblatt/issues/123"

    monkeypatch.setattr(meldungen, "lege_issue_an", statt_echt)

    antwort = schicke(klient, art="beleg", titel="XML abgelehnt")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["issue"]["nummer"] == 123
    # Die Art steht im Titel und als Label — im Verzeichnis sieht man sonst
    # erst beim Öffnen, worum es geht.
    assert gesehen["titel"].startswith("[Rechnung stimmt nicht]")
    assert gesehen["label"] == "beleg"
    assert leere_konten.meldungen()[0]["issue_nummer"] == 123
