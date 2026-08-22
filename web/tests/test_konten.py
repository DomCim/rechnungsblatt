"""Tests der Mandantenschicht: Anmeldung, Freigabe, Rollen, Kontingent, Trennung."""

import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main

from hilfen import lege_kunden_an, melde_an


STAMMDATEN = {
    "firmierung": "Muster & Partner GmbH",
    "anschrift": {"strasse": "Bahnhofstr. 12", "plz": "95119", "ort": "Naila"},
    "steuernummer": "223/456/78901",
    "iban": "DE14 7805 0000 0001 2345 67",
    "zahlungsziel_tage": 14,
}

RECHNUNG = {
    "nummer": "RE-2026-0001",
    "rechnungsdatum": "2026-08-21",
    "leistungsdatum": "2026-08-20",
    "empfaenger": {
        "name": "Beispielkunde GmbH",
        "anschrift": {"strasse": "Industriestr. 5", "plz": "95028", "ort": "Hof"},
    },
    "positionen": [
        {
            "bezeichnung": "Montagearbeiten",
            "menge": "8",
            "einheit": "HUR",
            "einzelpreis": "25,00",
            "steuer": "UST_19",
        }
    ],
}


def _richte_verzeichnis_ein(tmp_path, person):
    """Legt die drei Einrichtungsdateien an, ohne Ghostscript zu bemühen.

    Reicht, damit `_voraussetzungen` durchläuft — geprüft wird hier das
    Kontingent davor, nicht das Rendern danach.
    """
    import json

    wurzel = tmp_path / "nutzer" / str(person.id)
    wurzel.mkdir(parents=True, exist_ok=True)
    (wurzel / "briefpapier_norm.pdf").write_bytes(b"%PDF-1.7\n")
    (wurzel / "briefpapier.json").write_text('{"dateiname": "bogen.pdf"}', encoding="utf-8")
    (wurzel / "schreibzone.json").write_text(
        json.dumps({"kopf_ende_mm": 52.0, "fuss_beginn_mm": 25.0}), encoding="utf-8"
    )
    (wurzel / "stammdaten.json").write_text(
        json.dumps(STAMMDATEN, ensure_ascii=False), encoding="utf-8"
    )
    return wurzel


@pytest.fixture
def klient(tmp_path, monkeypatch, leere_konten):
    monkeypatch.setattr(main, "DATEN", tmp_path)
    return TestClient(main.app)


# ---------------------------------------------------------------- Registrierung

def test_registrierung_wartet_auf_freigabe(klient, leere_konten):
    antwort = klient.post(
        "/api/registrieren", json={"email": "neu@example.de", "passwort": "langgenug12"}
    )
    assert antwort.status_code == 201
    assert antwort.json()["status"] == leere_konten.STATUS_WARTET


def test_registrierung_prueft_eingaben(klient):
    kurz = klient.post(
        "/api/registrieren", json={"email": "a@example.de", "passwort": "kurz"}
    )
    assert kurz.status_code == 422
    assert "10 Zeichen" in kurz.json()["detail"]["grund"]

    keine_email = klient.post(
        "/api/registrieren", json={"email": "kein-at", "passwort": "langgenug12"}
    )
    assert keine_email.status_code == 422


def test_registrierung_lehnt_doppelte_email_ab(klient, leere_konten):
    lege_kunden_an(leere_konten, "doppelt@example.de", "langgenug12")
    antwort = klient.post(
        "/api/registrieren",
        json={"email": "Doppelt@Example.de", "passwort": "langgenug12"},
    )
    assert antwort.status_code == 422


# ---------------------------------------------------------------- Anmeldung

def test_falsches_passwort_wird_abgewiesen(klient, leere_konten):
    lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    antwort = klient.post(
        "/api/anmelden", json={"email": "kunde@example.de", "passwort": "falschfalsch"}
    )
    assert antwort.status_code == 401


def test_api_ohne_anmeldung_ist_401(klient):
    assert klient.get("/api/status").status_code == 401
    assert klient.get("/api/ablage").status_code == 401


def test_abmelden_beendet_die_sitzung(klient, leere_konten):
    lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    melde_an(klient, "kunde@example.de", "langgenug12")
    assert klient.get("/api/status").status_code == 200
    assert klient.post("/api/abmelden").status_code == 200
    assert klient.get("/api/status").status_code == 401


def test_seiten_leiten_ohne_anmeldung_zur_anmeldung(klient):
    antwort = klient.get("/app/rechnung", follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/anmelden"


# ---------------------------------------------------------------- Freigabe

def test_wartendes_konto_kommt_nicht_in_den_arbeitsbereich(klient, leere_konten):
    leere_konten.registriere("wartet@example.de", "langgenug12")
    melde_an(klient, "wartet@example.de", "langgenug12")

    antwort = klient.get("/api/status")
    assert antwort.status_code == 403
    assert antwort.json()["detail"]["code"] == "wartet_auf_freigabe"

    seite = klient.get("/app/rechnung")
    assert "geprüft" in seite.text or "reviewed" in seite.text


def test_gesperrtes_konto_verliert_die_sitzung(klient, leere_konten):
    person = lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    melde_an(klient, "kunde@example.de", "langgenug12")
    assert klient.get("/api/status").status_code == 200

    leere_konten.setze_status(person.id, leere_konten.STATUS_GESPERRT)
    assert klient.get("/api/status").status_code == 401


# ---------------------------------------------------------------- Landung

def test_landung_fuehrt_zur_einrichtung_und_danach_zum_formular(
    klient, leere_konten, tmp_path
):
    """Kernfrage des Entwurfs: Formular als Startseite, sobald alles da ist."""
    lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    melde_an(klient, "kunde@example.de", "langgenug12")

    ohne = klient.get("/app", follow_redirects=False)
    assert ohne.headers["location"] == "/app/einrichtung"

    person = leere_konten.pruefe_anmeldung("kunde@example.de", "langgenug12")
    wurzel = tmp_path / "nutzer" / str(person.id)
    wurzel.mkdir(parents=True, exist_ok=True)
    for name in ("briefpapier.json", "schreibzone.json", "stammdaten.json"):
        (wurzel / name).write_text("{}", encoding="utf-8")

    # Leere Objekte gelten nicht als eingerichtet — erst mit Inhalt.
    assert klient.get("/app", follow_redirects=False).headers["location"] == "/app/einrichtung"
    for name in ("briefpapier.json", "schreibzone.json", "stammdaten.json"):
        (wurzel / name).write_text('{"gesetzt": true}', encoding="utf-8")

    mit = klient.get("/app", follow_redirects=False)
    assert mit.headers["location"] == "/app/rechnung"


# ---------------------------------------------------------------- Trennung

def test_mandanten_sehen_einander_nicht(klient, leere_konten, tmp_path):
    erste = lege_kunden_an(leere_konten, "eins@example.de", "langgenug12")
    zweite = lege_kunden_an(leere_konten, "zwei@example.de", "langgenug12")

    for person, nummer in ((erste, "RE-EINS"), (zweite, "RE-ZWEI")):
        ordner = tmp_path / "nutzer" / str(person.id) / "ablage" / nummer
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / "daten.json").write_text('{"typ": "RECHNUNG"}', encoding="utf-8")

    melde_an(klient, "eins@example.de", "langgenug12")
    nummern = {beleg["nummer"] for beleg in klient.get("/api/ablage").json()}
    assert nummern == {"RE-EINS"}

    # Die fremde Nummer ist auch bei direktem Zugriff nicht erreichbar.
    assert klient.get("/api/ablage/RE-ZWEI/daten").status_code == 404


# ---------------------------------------------------------------- Kontingent

def test_kontingent_blockt_und_guthaben_loest_wieder(leere_konten):
    person = lege_kunden_an(leere_konten, "knapp@example.de", "langgenug12", tarif="probe")
    kontingent = leere_konten.kontingent(person)
    assert kontingent.inklusiv == 3
    assert kontingent.darf_erzeugen is True

    for lauf in range(3):
        leere_konten.buche_rechnung(person, f"RE-{lauf}")

    with pytest.raises(leere_konten.KontingentErschoepft):
        leere_konten.buche_rechnung(person, "RE-zuviel")

    person = leere_konten.buche_guthaben(person.id, 1000)
    stand = leere_konten.buche_rechnung(person, "RE-bezahlt")
    assert stand.verbraucht == 4
    assert stand.guthaben_cent == 1000 - 290


def test_rechnung_ueber_kontingent_gibt_402(klient, leere_konten, tmp_path):
    """Das Kontingent greift, bevor überhaupt ein PDF gebaut wird."""
    person = lege_kunden_an(leere_konten, "knapp@example.de", "langgenug12", tarif="guthaben")
    assert leere_konten.kontingent(person).darf_erzeugen is False
    _richte_verzeichnis_ein(tmp_path, person)

    melde_an(klient, "knapp@example.de", "langgenug12")
    antwort = klient.post("/api/rechnung", json=RECHNUNG)
    assert antwort.status_code == 402
    assert antwort.json()["code"] == "kontingent"


# ---------------------------------------------------------------- Verwaltung

@pytest.fixture
def admin_klient(klient, leere_konten):
    person = lege_kunden_an(leere_konten, "chef@example.de", "langgenug12")
    leere_konten.setze_rolle(person.id, leere_konten.ROLLE_ADMIN)
    melde_an(klient, "chef@example.de", "langgenug12")
    return klient


def test_verwaltung_ist_kunden_verwehrt(klient, leere_konten):
    lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    melde_an(klient, "kunde@example.de", "langgenug12")
    assert klient.get("/api/verwaltung/nutzer").status_code == 403

    seite = klient.get("/app/verwaltung", follow_redirects=False)
    assert seite.status_code == 303
    assert seite.headers["location"] == "/app"


def test_admin_gibt_konto_frei(admin_klient, leere_konten):
    wartend = leere_konten.registriere("neu@example.de", "langgenug12")

    liste = admin_klient.get("/api/verwaltung/nutzer").json()
    assert {eintrag["email"] for eintrag in liste} == {"chef@example.de", "neu@example.de"}

    antwort = admin_klient.post(
        f"/api/verwaltung/nutzer/{wartend.id}/status",
        json={"status": leere_konten.STATUS_FREI},
    )
    assert antwort.status_code == 200
    assert antwort.json()["status"] == leere_konten.STATUS_FREI


def test_admin_bucht_guthaben_und_setzt_tarif(admin_klient, leere_konten):
    kunde = lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12", tarif="probe")

    guthaben = admin_klient.post(
        f"/api/verwaltung/nutzer/{kunde.id}/guthaben", json={"cent": 2500}
    )
    assert guthaben.json()["guthaben_cent"] == 2500

    tarif = admin_klient.post(
        f"/api/verwaltung/nutzer/{kunde.id}/tarif", json={"tarif": "monat"}
    )
    assert tarif.json()["tarif"] == "monat"

    unbekannt = admin_klient.post(
        f"/api/verwaltung/nutzer/{kunde.id}/tarif", json={"tarif": "gibtsnicht"}
    )
    assert unbekannt.status_code == 422


def test_letzter_admin_ist_geschuetzt(admin_klient, leere_konten):
    chef = leere_konten.pruefe_anmeldung("chef@example.de", "langgenug12")

    rolle = admin_klient.post(
        f"/api/verwaltung/nutzer/{chef.id}/rolle", json={"rolle": leere_konten.ROLLE_KUNDE}
    )
    assert rolle.status_code == 422
    assert "letzte Admin" in rolle.json()["detail"]["grund"]

    geloescht = admin_klient.delete(f"/api/verwaltung/nutzer/{chef.id}")
    assert geloescht.status_code == 422


def test_admin_pflegt_tarife_und_die_startseite_zeigt_sie(admin_klient):
    antwort = admin_klient.put(
        "/api/verwaltung/tarife/monat",
        json={
            "name": "Monatlich neu",
            "beschreibung": "Geänderte Beschreibung.",
            "monatsbeitrag_cent": 1200,
            "inklusiv_rechnungen": 15,
            "preis_je_rechnung_cent": 150,
            "reihenfolge": 30,
            "sichtbar": True,
        },
    )
    assert antwort.status_code == 200
    assert antwort.json()["monatsbeitrag_cent"] == 1200

    oeffentlich = admin_klient.get("/api/tarife").json()
    monat = next(tarif for tarif in oeffentlich if tarif["schluessel"] == "monat")
    assert monat["name"] == "Monatlich neu"
    assert monat["inklusiv_rechnungen"] == 15


def test_unsichtbarer_tarif_fehlt_auf_der_startseite(klient):
    schluessel = {tarif["schluessel"] for tarif in klient.get("/api/tarife").json()}
    assert "unbegrenzt" not in schluessel  # als nicht sichtbar ausgeliefert


# ---------------------------------------------------------------- Passwort

def test_passwort_wechseln(klient, leere_konten):
    lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    melde_an(klient, "kunde@example.de", "langgenug12")

    falsch = klient.post(
        "/api/ich/passwort", json={"alt": "stimmtnicht", "neu": "nochlaenger123"}
    )
    assert falsch.status_code == 422

    richtig = klient.post(
        "/api/ich/passwort", json={"alt": "langgenug12", "neu": "nochlaenger123"}
    )
    assert richtig.status_code == 200

    klient.post("/api/abmelden")
    melde_an(klient, "kunde@example.de", "nochlaenger123")


def test_passwort_hash_ist_gesalzen(leere_konten):
    erster = leere_konten.hashe_passwort("dasselbe123")
    zweiter = leere_konten.hashe_passwort("dasselbe123")
    assert erster != zweiter  # eigenes Salz je Hash
    assert leere_konten.passwort_stimmt("dasselbe123", erster)
    assert not leere_konten.passwort_stimmt("etwasanderes", erster)
