"""Tests der Mandantenschicht: Anmeldung, Freigabe, Rollen, Kontingent, Trennung."""

import dataclasses

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
    person, _ = leere_konten.registriere("wartet@example.de", "langgenug12")
    # Adresse bestätigen: Hier geht es um die ADMIN-Freigabe, nicht um die
    # E-Mail-Bestätigung — die hat ihren eigenen Test.
    leere_konten.bestaetige_email(person.id)
    melde_an(klient, "wartet@example.de", "langgenug12")

    antwort = klient.get("/api/status")
    assert antwort.status_code == 403
    assert antwort.json()["detail"]["code"] == "wartet_auf_freigabe"

    seite = klient.get("/app/rechnung")
    assert "geprüft" in seite.text or "reviewed" in seite.text


def test_ohne_bestaetigte_adresse_keine_anmeldung(klient, leere_konten):
    """Die E-Mail-Bestätigung ist Bedingung, nicht Empfehlung.

    Ohne sie darf keine Sitzung entstehen — sonst wäre der Code eine
    Formalität, die man überspringen kann.
    """
    leere_konten.registriere("frisch@example.de", "langgenug12")
    antwort = klient.post(
        "/api/anmelden",
        json={"email": "frisch@example.de", "passwort": "langgenug12"},
    )
    assert antwort.status_code == 403
    assert antwort.json()["detail"]["code"] == "email_offen"


def test_bestaetigungscode_wird_nach_fuenf_versuchen_verbraucht(klient, leere_konten):
    """Sechs Ziffern tragen nur mit Begrenzung.

    Eine Million Möglichkeiten sind ohne Sperre in Minuten durchprobiert.
    """
    person, _ = leere_konten.registriere("raten@example.de", "langgenug12")
    leere_konten.lege_nachweis_an(person.id, leere_konten.ZWECK_EMAIL)

    for _ in range(leere_konten.MAX_VERSUCHE):
        antwort = klient.post(
            "/api/email/bestaetigen",
            json={"email": "raten@example.de", "code": "000000"},
        )
        assert antwort.status_code == 422

    # Nachweis ist verbraucht — auch der richtige Code zöge jetzt nicht mehr.
    with leere_konten.verbindung() as verbindung:
        uebrig = verbindung.execute(
            "SELECT count(*) AS anzahl FROM nachweise WHERE nutzer = %s",
            (person.id,),
        ).fetchone()
    assert uebrig["anzahl"] == 0


def test_ruecksetzmarke_gilt_nur_einmal(klient, leere_konten):
    """Ein verbrauchter Link darf kein zweites Mal wirken."""
    person = lege_kunden_an(leere_konten, "reset@example.de", "langgenug12")
    marke = leere_konten.lege_nachweis_an(person.id, leere_konten.ZWECK_RUECKSETZEN)

    erste = klient.post(
        "/api/passwort/neu", json={"marke": marke, "passwort": "ganzneues123"}
    )
    assert erste.status_code == 200
    # Ohne Wiederherstellungscode bleiben die Daten zu — ehrlich gemeldet.
    assert erste.json()["daten_erhalten"] is False

    zweite = klient.post(
        "/api/passwort/neu", json={"marke": marke, "passwort": "nochmalneu12"}
    )
    assert zweite.status_code == 422


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

    person, _ = leere_konten.pruefe_anmeldung("kunde@example.de", "langgenug12")
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
    wartend, _ = leere_konten.registriere("neu@example.de", "langgenug12")

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
    chef, _ = leere_konten.pruefe_anmeldung("chef@example.de", "langgenug12")

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


def test_hervorgehobener_tarif_kommt_auf_der_startseite_an(admin_klient, klient):
    """Die Empfehlung steht in der Datenbank, nicht im Code.

    Der Weg geht durch sieben Stellen (Schema, Dataclass, Zeilenleser,
    JSON, PUT, Verwaltung, Renderer). Wird eine vergessen, verschwindet
    das Feld stillschweigend — genau das prüft dieser Test.
    """
    antwort = admin_klient.put(
        "/api/verwaltung/tarife/guthaben",
        json={
            "name": "Guthaben",
            "beschreibung": "Bezahlt wird je Rechnung.",
            "monatsbeitrag_cent": 0,
            "inklusiv_rechnungen": 0,
            "preis_je_rechnung_cent": 249,
            "reihenfolge": 20,
            "sichtbar": True,
            "hervorheben": True,
        },
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["hervorheben"] is True

    # Auch ohne Anmeldung: die öffentliche Seite liest denselben Endpunkt.
    tarife = {t["schluessel"]: t for t in klient.get("/api/tarife").json()}
    assert tarife["guthaben"]["hervorheben"] is True
    # Kein hervorgehobener Tarif ist ein gültiger Zustand, keine Ausnahme.
    assert tarife["probe"]["hervorheben"] is False


def test_wallet_muster_passwortwechsel_und_wiederherstellung(leere_konten):
    """Der Datenschlüssel überlebt Passwortwechsel und Wiederherstellung.

    Das ist der Kern des Wallet-Musters: Das Passwort ist nicht der
    Schlüssel, es öffnet nur die Hülle. Ginge der Schlüssel dabei
    verloren, wären alle Dateien des Kontos unlesbar.
    """
    person, code = leere_konten.registriere("wallet@example.de", "erstespasswort1")
    _, erster = leere_konten.pruefe_anmeldung("wallet@example.de", "erstespasswort1")
    assert erster is not None

    leere_konten.wechsle_passwort(person.id, "erstespasswort1", "zweitespasswort2")
    _, nach_wechsel = leere_konten.pruefe_anmeldung(
        "wallet@example.de", "zweitespasswort2"
    )
    assert nach_wechsel == erster, "Passwortwechsel hat den Datenschlüssel verloren"

    leere_konten.stelle_mit_code_wieder_her(
        "wallet@example.de", code, "drittespasswort3"
    )
    _, nach_code = leere_konten.pruefe_anmeldung(
        "wallet@example.de", "drittespasswort3"
    )
    assert nach_code == erster, "Wiederherstellung hat den Datenschlüssel verloren"

    with pytest.raises(leere_konten.KontoFehler):
        leere_konten.stelle_mit_code_wieder_her(
            "wallet@example.de", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", "viertespasswort4"
        )


def test_betreiber_kommt_nicht_an_die_huelle(leere_konten):
    """Was in der Datenbank steht, reicht nicht zum Öffnen.

    Der Sinn der Übung: Wer Datenbank und Dateien in der Hand hält — also
    der Betreiber — kommt an die Nutzdaten trotzdem nicht heran.
    """
    from rechnungsblatt_web import tresor

    person, _ = leere_konten.registriere("still@example.de", "langgenug12")
    with leere_konten.verbindung() as verbindung:
        zeile = verbindung.execute(
            "SELECT huelle_passwort, passwort_hash FROM nutzer WHERE id = %s",
            (person.id,),
        ).fetchone()

    # Der gespeicherte Hash öffnet die Hülle nicht.
    with pytest.raises(tresor.TresorFehler):
        tresor.oeffne(bytes(zeile["huelle_passwort"]), zeile["passwort_hash"])
    # Das echte Passwort schon — das kennt nur der Kunde.
    assert tresor.oeffne(bytes(zeile["huelle_passwort"]), "langgenug12")


def test_nutzdaten_liegen_verschluesselt_auf_der_platte(klient, leere_konten, tmp_path):
    """Ende zu Ende: geschrieben wird Geheimtext, gelesen wird Klartext."""
    lege_kunden_an(leere_konten, "kunde@example.de", "langgenug12")
    melde_an(klient, "kunde@example.de", "langgenug12")

    antwort = klient.put("/api/kunden", json=[{"name": "Streng Geheim GmbH"}])
    assert antwort.status_code == 200, antwort.text

    datei = next(tmp_path.glob("nutzer/*/kunden.json"))
    roh = datei.read_bytes()
    assert roh.startswith(b"RBV1"), "Datei ist nicht verschlüsselt"
    assert b"Streng Geheim" not in roh, "Klartext steht in der Datei"

    # Über die API kommt sie trotzdem lesbar zurück.
    assert klient.get("/api/kunden").json()[0]["name"] == "Streng Geheim GmbH"


def test_steuer_index_normalisiert_und_bleibt_unlesbar(leere_konten):
    """Blind Index: vergleichbar, aber nicht rückrechenbar.

    Steuernummern werden je Finanzamt unterschiedlich geschrieben — ohne
    Normalisierung fände der Vergleich dieselbe Nummer nicht wieder.
    """
    gleich = (
        leere_konten.steuer_index("DE123456789", None),
        leere_konten.steuer_index("de 123 456 789", None),
        leere_konten.steuer_index("DE-123456789", None),
    )
    assert len(set(gleich)) == 1, "Schreibweise ändert den Abdruck"

    # Steuernummer mit und ohne Schrägstriche.
    assert (leere_konten.steuer_index(None, "123/456/78901")
            == leere_konten.steuer_index(None, "12345678901"))

    # Verschiedene Nummern bleiben verschieden.
    assert (leere_konten.steuer_index("DE111111111", None)
            != leere_konten.steuer_index("DE999999999", None))

    # Die USt-IdNr. hat Vorrang; Kleinunternehmer ohne sie werden über die
    # Steuernummer erfasst (Befund S3 verlangt eines von beidem).
    assert (leere_konten.steuer_index("DE111111111", "999")
            == leere_konten.steuer_index("DE111111111", None))
    assert leere_konten.steuer_index(None, None) is None

    # Die Nummer darf im Abdruck nicht auftauchen.
    abdruck = leere_konten.steuer_index("DE123456789", None)
    assert "123456789" not in abdruck


def test_doppeltes_steuermerkmal_wird_gemeldet(admin_klient, klient, leere_konten):
    """Zwei Konten mit derselben Nummer tauchen im Adminbereich auf.

    Gemeldet, nicht gesperrt: Betriebsübergabe und Steuernummernwechsel
    sehen genauso aus wie ein zweites Konto für die freien Rechnungen.
    """
    einer = lege_kunden_an(leere_konten, "einer@example.de", "langgenug12")
    zwei = lege_kunden_an(leere_konten, "zwei@example.de", "langgenug12")
    abdruck = leere_konten.steuer_index("DE123456789", None)
    leere_konten.setze_steuer_index(einer.id, abdruck)
    leere_konten.setze_steuer_index(zwei.id, abdruck)

    treffer = admin_klient.get("/api/verwaltung/dubletten").json()
    assert len(treffer) == 1
    assert set(treffer[0]["konten"]) == {"einer@example.de", "zwei@example.de"}
    # Der Abdruck selbst geht nicht nach draußen.
    assert "steuer_index" not in treffer[0]

    # Ein einzelnes Konto meldet nichts.
    leere_konten.setze_steuer_index(zwei.id, None)
    assert admin_klient.get("/api/verwaltung/dubletten").json() == []


def test_zahlung_wird_genau_einmal_gebucht(leere_konten):
    """Doppelzustellung darf kein zweites Mal Guthaben geben.

    Stripe sichert Webhook-Zustellungen ausdrücklich MEHRFACH zu — bei
    Zustellproblemen wird wiederholt. Ohne Sperre bekäme derselbe Kauf
    mehrfach Guthaben gutgeschrieben.
    """
    person = lege_kunden_an(leere_konten, "zahler@example.de", "langgenug12")

    assert leere_konten.verbuche_zahlung("cs_1", person.id, "guthaben", 2500) is True
    # Zweite Zustellung derselben Zahlung.
    assert leere_konten.verbuche_zahlung("cs_1", person.id, "guthaben", 2500) is False

    stand = leere_konten.nutzer(person.id)
    assert stand.guthaben_cent == 2500, "doppelt gebucht"

    # Eine andere Zahlung geht durch.
    assert leere_konten.verbuche_zahlung("cs_2", person.id, "guthaben", 1000) is True
    assert leere_konten.nutzer(person.id).guthaben_cent == 3500


def test_abo_ende_setzt_tarif_zurueck_ohne_guthaben_zu_loeschen(leere_konten):
    """Ein gekündigtes Abo nimmt kein bezahltes Guthaben mit."""
    person = lege_kunden_an(leere_konten, "abo@example.de", "langgenug12")
    leere_konten.verbuche_zahlung("cs_g", person.id, "guthaben", 2000)
    leere_konten.setze_abo(person.id, "sub_1", "monat")
    assert leere_konten.nutzer(person.id).tarif == "monat"

    leere_konten.setze_abo(person.id, None, leere_konten.STANDARD_TARIF)
    danach = leere_konten.nutzer(person.id)
    assert danach.tarif == leere_konten.STANDARD_TARIF
    assert danach.guthaben_cent == 2000, "Guthaben beim Abo-Ende verloren"


def test_loeschen_entfernt_auch_die_nutzdaten(admin_klient, leere_konten, tmp_path):
    """Konto weg heißt Daten weg — nicht nur die Zeile in der Datenbank.

    Vorher blieb ``DATEN/nutzer/<id>/`` nach dem Löschen vollständig
    liegen. Zwei Folgen: Die Daten eines gelöschten Kunden lagen weiter auf
    der Platte, und eine spätere Nutzer-ID konnte dasselbe Verzeichnis
    erben und fremde Belege sehen.
    """
    opfer = lege_kunden_an(leere_konten, "weg@example.de", "langgenug12")
    seins = tmp_path / "nutzer" / str(opfer.id)
    (seins / "ablage" / "RE-1").mkdir(parents=True)
    (seins / "kunden.json").write_text('[{"name": "Geheim"}]', encoding="utf-8")
    (seins / "ablage" / "RE-1" / "rechnung.pdf").write_bytes(b"%PDF-")

    # Ein zweites Konto, das unberührt bleiben muss.
    anderer = lege_kunden_an(leere_konten, "bleibt@example.de", "langgenug12")
    seins_auch = tmp_path / "nutzer" / str(anderer.id)
    seins_auch.mkdir(parents=True)
    (seins_auch / "kunden.json").write_text("[]", encoding="utf-8")

    antwort = admin_klient.delete(f"/api/verwaltung/nutzer/{opfer.id}")
    assert antwort.status_code == 200, antwort.text

    assert not seins.exists(), "Nutzdaten des gelöschten Kontos liegen noch da"
    assert seins_auch.exists(), "fremdes Verzeichnis wurde mitgelöscht"


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


# ------------------------------------------------------------ Abo-Tarife

def test_tarif_traegt_eigene_stripe_preis_id(leere_konten):
    """Die Preis-ID gehört zum Tarif, nicht in eine globale Einstellung.

    Nur so lassen sich mehrere Abos nebeneinander anbieten — vorher konnte
    genau ein Tarif als Abo gebucht werden.
    """
    konten = leere_konten
    vorher = konten.tarif("monat")
    konten.speichere_tarif(dataclasses.replace(vorher, stripe_preis="price_A"))
    try:
        assert konten.tarif("monat").stripe_preis == "price_A"
        # Der zweite Tarif bekommt eine andere ID; sie dürfen sich nicht
        # gegenseitig überschreiben.
        zweiter = konten.tarif("unbegrenzt")
        konten.speichere_tarif(dataclasses.replace(zweiter, stripe_preis="price_B"))
        assert konten.tarif("monat").stripe_preis == "price_A"
        assert konten.tarif("unbegrenzt").stripe_preis == "price_B"
    finally:
        konten.speichere_tarif(vorher)
        konten.speichere_tarif(zweiter)


def test_tarif_ohne_preis_id_bleibt_leer(leere_konten):
    """Ein Tarif ohne Abo trägt keine ID — und das ist ein gültiger Zustand."""
    assert leere_konten.tarif("probe").stripe_preis == ""


def test_angebot_zeigt_nur_buchbare_abos(leere_konten):
    """Buchbar ist ein Tarif erst mit Preis-ID — und nur wenn er sichtbar ist."""
    konten = leere_konten
    lege_kunden_an(konten, "abo@example.org", "geheim-genug-123", tarif="probe")
    monat = konten.tarif("monat")
    unbegrenzt = konten.tarif("unbegrenzt")
    konten.speichere_tarif(dataclasses.replace(
        monat, stripe_preis="price_M", sichtbar=True))
    konten.speichere_tarif(dataclasses.replace(
        unbegrenzt, stripe_preis="price_U", sichtbar=False))
    konten.setze_einstellungen({"stripe_secret": "sk_test_x"})
    try:
        klient = TestClient(main.app)
        melde_an(klient, "abo@example.org", "geheim-genug-123")
        angebot = klient.get("/api/bezahlen/angebot").json()
        schluessel = [a["schluessel"] for a in angebot["abos"]]
        # „monat" ist buchbar, „unbegrenzt" zurückgezogen, „guthaben" und
        # „probe" haben keine Preis-ID.
        assert schluessel == ["monat"]
    finally:
        konten.speichere_tarif(monat)
        konten.speichere_tarif(unbegrenzt)
        konten.setze_einstellungen({"stripe_secret": ""})


def test_zurueckgezogener_tarif_ist_nicht_zu_erschleichen(leere_konten):
    """Ein unsichtbarer Tarif darf auch über einen direkten Aufruf nicht gehen.

    Sonst ließe sich ein zurückgenommenes Angebot weiter buchen, indem man
    den Schlüssel von Hand einsetzt.
    """
    konten = leere_konten
    lege_kunden_an(konten, "schlau@example.org", "geheim-genug-123", tarif="probe")
    unbegrenzt = konten.tarif("unbegrenzt")
    konten.speichere_tarif(dataclasses.replace(
        unbegrenzt, stripe_preis="price_U", sichtbar=False))
    konten.setze_einstellungen({"stripe_secret": "sk_test_x"})
    try:
        klient = TestClient(main.app)
        melde_an(klient, "schlau@example.org", "geheim-genug-123")
        antwort = klient.post("/api/bezahlen/abo", json={"tarif": "unbegrenzt"})
        assert antwort.status_code == 422
        assert "nicht angeboten" in antwort.json()["detail"]["grund"]
    finally:
        konten.speichere_tarif(unbegrenzt)
        konten.setze_einstellungen({"stripe_secret": ""})


def test_webhook_bucht_den_gewaehlten_tarif(leere_konten):
    """Der Tarif kommt aus den Metadaten der Sitzung, nicht aus einer Vorgabe.

    Vorher setzte der Webhook für jedes Abo denselben Tarif — bei mehreren
    Abo-Tarifen hätte das jedem Kunden das falsche Kontingent gegeben.
    """
    from rechnungsblatt_web import bezahlen

    konten = leere_konten
    person = lege_kunden_an(konten, "hook@example.org", "geheim-genug-123",
                            tarif="probe")
    ereignis = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "subscription": "sub_1",
            "metadata": {"nutzer_id": str(person.id), "tarif": "unbegrenzt"},
        }},
    }
    bezahlen.verarbeite(ereignis)
    assert konten.nutzer(person.id).tarif == "unbegrenzt"


def test_webhook_findet_den_tarif_ueber_die_preis_id(leere_konten):
    """Ohne Metadaten hilft die Preis-ID — etwa bei einem Abo aus Stripe."""
    from rechnungsblatt_web import bezahlen

    konten = leere_konten
    person = lege_kunden_an(konten, "direkt@example.org", "geheim-genug-123",
                            tarif="probe")
    monat = konten.tarif("monat")
    konten.speichere_tarif(dataclasses.replace(monat, stripe_preis="price_M"))
    try:
        ereignis = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "mode": "subscription",
                "subscription": "sub_2",
                "metadata": {"nutzer_id": str(person.id)},
                "items": {"data": [{"price": {"id": "price_M"}}]},
            }},
        }
        bezahlen.verarbeite(ereignis)
        assert konten.nutzer(person.id).tarif == "monat"
    finally:
        konten.speichere_tarif(monat)


# ------------------------------------------------------------ Besucher

def test_besucher_ohne_schluessel_ist_kein_fehler(leere_konten):
    """Ohne API-Schlüssel bleibt die Auswertung leer — gezählt wird trotzdem.

    Der Unterschied zählt: „nicht eingerichtet" ist ein Zustand, den der
    Betreiber selbst beheben kann; ein Fehler sähe nach einem Defekt aus.
    """
    from rechnungsblatt_web import statistik

    konten = leere_konten
    konten.setze_einstellungen({
        "plausible_url": "https://plausible.example.org",
        "plausible_domain": "beispiel.de",
        "plausible_api_key": "",
    })
    try:
        assert statistik.zugang() is None
        lege_kunden_an(konten, "chef@example.org", "geheim-genug-123")
        konten.setze_rolle(konten.nutzer_zu_email("chef@example.org").id, "admin")
        klient = TestClient(main.app)
        melde_an(klient, "chef@example.org", "geheim-genug-123")
        antwort = klient.get("/api/verwaltung/besucher")
        assert antwort.status_code == 200
        assert antwort.json() == {"eingerichtet": False}
    finally:
        konten.setze_einstellungen({
            "plausible_url": "", "plausible_domain": "", "plausible_api_key": "",
        })


def test_besucher_weist_erfundenen_zeitraum_ab(leere_konten):
    """Ein unbekannter Zeitraum wird abgewiesen, nicht stillschweigend ersetzt.

    Mit einer Vorgabe käme bei ``?zeitraum=constructor`` klaglos die
    30-Tage-Auswertung zurück — und niemand merkte den Tippfehler.
    """
    konten = leere_konten
    lege_kunden_an(konten, "chef2@example.org", "geheim-genug-123")
    konten.setze_rolle(konten.nutzer_zu_email("chef2@example.org").id, "admin")
    klient = TestClient(main.app)
    melde_an(klient, "chef2@example.org", "geheim-genug-123")
    assert klient.get("/api/verwaltung/besucher?zeitraum=constructor").status_code == 422


def test_plausible_schluessel_wird_verschluesselt_abgelegt(
        leere_konten, mit_serverschluessel):
    """Der Schlüssel liest zwar nur — aber die Zahlen aller Seiten des Kontos."""
    konten = leere_konten
    konten.setze_einstellungen({"plausible_api_key": "geheimer-lese-schluessel"})
    try:
        with konten.verbindung() as verb:
            roh = verb.execute(
                "SELECT wert FROM einstellungen WHERE schluessel = 'plausible_api_key'"
            ).fetchone()["wert"]
        assert "geheimer-lese-schluessel" not in roh
        assert roh.startswith("v1:")
        # Für die Anwendung ist er trotzdem lesbar.
        werte = konten.einstellungen(mit_geheimnissen=True)
        assert werte["plausible_api_key"] == "geheimer-lese-schluessel"
        # Ohne ausdrücklichen Wunsch nicht.
        assert "geheim" not in konten.einstellungen()["plausible_api_key"]
    finally:
        konten.setze_einstellungen({"plausible_api_key": ""})


def test_verlauf_fuellt_die_tage_die_plausible_auslaesst():
    """Plausible liefert nur Tage mit Ereignissen — die Lücken fehlen sonst.

    Ohne das Auffüllen wäre ein besucherloser Tag gar kein Balken, und der
    Verlauf sähe kürzer aus, als er ist.
    """
    from rechnungsblatt_web import statistik

    antwort = {
        "results": [
            {"metrics": [12], "dimensions": ["2026-08-01"]},
            {"metrics": [7], "dimensions": ["2026-08-03"]},
        ],
        "meta": {"time_labels": ["2026-08-01", "2026-08-02", "2026-08-03"]},
    }
    assert statistik._verlauf(antwort) == [
        {"tag": "2026-08-01", "besucher": 12},
        {"tag": "2026-08-02", "besucher": 0},
        {"tag": "2026-08-03", "besucher": 7},
    ]


def test_geheimnis_laesst_sich_wieder_entfernen(leere_konten):
    """Leer heißt entfernen, Punkte heißen unverändert.

    Ohne den Unterschied ließe sich ein einmal gesetzter Zugang über die
    Oberfläche nie wieder abschalten: Sie schickt die Maskierung zurück,
    die sie angezeigt bekommen hat.
    """
    konten = leere_konten
    konten.setze_einstellungen({"stripe_secret": "sk_test_abc"})
    assert konten.einstellungen(mit_geheimnissen=True)["stripe_secret"] == "sk_test_abc"

    # Punkte: bleibt stehen
    konten.setze_einstellungen({"stripe_secret": "••••••"})
    assert konten.einstellungen(mit_geheimnissen=True)["stripe_secret"] == "sk_test_abc"

    # Leer: weg
    konten.setze_einstellungen({"stripe_secret": ""})
    assert konten.einstellungen(mit_geheimnissen=True)["stripe_secret"] == ""


# ------------------------------------------------------------ DKIM

def test_dkim_unterschrift_haelt_der_pruefung_stand():
    """Die Signatur wird von einer fremden Umsetzung der Norm anerkannt.

    Ein Selbsttest wäre wertlos — dieselbe Rechnung zweimal ergibt immer
    dasselbe. Hier prüft ``dkimpy`` nach, sofern es installiert ist.
    """
    fremd = pytest.importorskip("dkim", reason="dkimpy nicht installiert")

    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid

    from rechnungsblatt_web import dkim as eigen

    pem = eigen.erzeuge_schluesselpaar()
    eintrag = eigen.dns_eintrag(pem, "rb", "rechnungsblatt.de")

    def baue(betreff: str):
        n = EmailMessage()
        n["From"] = "Rechnungsblatt <no-reply@rechnungsblatt.de>"
        n["To"] = "kunde@example.org"
        n["Subject"] = betreff
        n["Date"] = formatdate(localtime=True)
        n["Message-ID"] = make_msgid(domain="rechnungsblatt.de")
        n.set_content("Ihr Code lautet 481920.\n")
        return n

    def dns(_name, timeout=5):
        return eintrag["wert"].encode()

    # Der Umlaut ist kein Sonderfall, sondern der Normalfall: „Ihr
    # Bestätigungscode" steht auf jeder Registrierungsmail. Python kodiert
    # ihn als =?utf-8?q?…; signiert werden muss diese Form, nicht der
    # Klartext, den get() liefert.
    for betreff in ("Testnachricht", "Ihr Bestätigungscode"):
        roh = eigen.unterschreibe(baue(betreff), "rechnungsblatt.de", "rb", pem)
        assert fremd.verify(roh, dnsfunc=dns) is True, betreff
        # Die Signaturzeile darf nicht selbst kodiert werden.
        assert b"=?utf-8?" not in roh.split(b"From:")[0]

    # Gegenproben: eine veränderte Nachricht darf nicht bestehen.
    roh = eigen.unterschreibe(baue("Test"), "rechnungsblatt.de", "rb", pem)
    assert fremd.verify(roh.replace(b"481920", b"999999"), dnsfunc=dns) is False
    assert fremd.verify(
        roh.replace(b"kunde@example.org", b"opfer@example.org"), dnsfunc=dns
    ) is False

    # Und mit einem fremden Schlüssel im DNS ebenfalls nicht.
    anderer = eigen.dns_eintrag(eigen.erzeuge_schluesselpaar(), "rb",
                                "rechnungsblatt.de")
    assert fremd.verify(
        roh, dnsfunc=lambda _n, timeout=5: anderer["wert"].encode()
    ) is False


def test_dkim_alignment_folgt_dmarc():
    """Nur passende Domains: Unterdomain zählt, umgekehrt nicht.

    Mit dem Schlüssel von example.org im Namen von rechnungsblatt.de zu
    unterschreiben, bestünde zwar die DKIM-Prüfung — DMARC verlangt aber,
    dass Absender und signierende Domain zusammengehören.
    """
    from rechnungsblatt_web import dkim

    assert dkim.passt("rechnungsblatt.de", "no-reply@rechnungsblatt.de")
    assert dkim.passt("rechnungsblatt.de", "no-reply@post.rechnungsblatt.de")
    assert dkim.passt("rechnungsblatt.de", "Name <no-reply@RECHNUNGSBLATT.DE>")
    assert not dkim.passt("post.rechnungsblatt.de", "no-reply@rechnungsblatt.de")
    assert not dkim.passt("rechnungsblatt.de", "no-reply@example.org")
    assert not dkim.passt("", "no-reply@rechnungsblatt.de")
    assert not dkim.passt("rechnungsblatt.de", "")


def test_dkim_schluessel_wird_verschluesselt_abgelegt(
        leere_konten, mit_serverschluessel):
    """Wer den privaten Schlüssel hat, verschickt Post in fremdem Namen."""
    from rechnungsblatt_web import dkim

    konten = leere_konten
    pem = dkim.erzeuge_schluesselpaar()
    konten.setze_einstellungen({"dkim_schluessel": pem})
    try:
        with konten.verbindung() as verb:
            roh = verb.execute(
                "SELECT wert FROM einstellungen WHERE schluessel = 'dkim_schluessel'"
            ).fetchone()["wert"]
        assert "BEGIN PRIVATE KEY" not in roh
        assert roh.startswith("v1:")
        assert konten.einstellungen(mit_geheimnissen=True)["dkim_schluessel"] == pem
    finally:
        konten.setze_einstellungen({"dkim_schluessel": ""})


def test_unlesbarer_dkim_schluessel_verhindert_den_versand_nicht(leere_konten):
    """Eine unsignierte Nachricht kommt vielleicht an, eine nicht verschickte nie."""
    from email.message import EmailMessage

    from rechnungsblatt_web import post

    nachricht = EmailMessage()
    nachricht["From"] = "no-reply@rechnungsblatt.de"
    nachricht["To"] = "kunde@example.org"
    nachricht["Subject"] = "Test"
    nachricht.set_content("Hallo\n")

    roh = post._unterschreibe(nachricht, "no-reply@rechnungsblatt.de", {
        "dkim_domain": "rechnungsblatt.de",
        "dkim_selektor": "rb",
        "dkim_schluessel": "kein gueltiger schluessel",
    })
    assert b"DKIM-Signature" not in roh
    assert b"Hallo" in roh


def test_ohne_serverschluessel_warnt_die_ablage(leere_konten, caplog):
    """Ohne RECHNUNGSBLATT_SCHLUESSEL liegt das Geheimnis im Klartext.

    Der Rückfall bleibt — sonst startete ein frisch aufgesetzter Stack ohne
    die Variable gar nicht. Aber er darf nicht stillschweigend passieren:
    Genau so fiel in der CI auf, dass dort nichts verschlüsselt wird.
    """
    konten = leere_konten
    vorher = konten.SERVERSCHLUESSEL
    konten.SERVERSCHLUESSEL = ""
    try:
        with caplog.at_level("WARNING"):
            konten.setze_einstellungen({"stripe_secret": "sk_test_klartext"})
        assert "RECHNUNGSBLATT_SCHLUESSEL" in caplog.text
        with konten.verbindung() as verb:
            roh = verb.execute(
                "SELECT wert FROM einstellungen WHERE schluessel = 'stripe_secret'"
            ).fetchone()["wert"]
        # Klartext — dokumentiert, nicht behauptet.
        assert roh == "sk_test_klartext"
    finally:
        konten.SERVERSCHLUESSEL = vorher
        konten.setze_einstellungen({"stripe_secret": ""})


# ------------------------------------------------------------ Tarife pflegen

def test_neuer_tarif_ueber_die_api(leere_konten):
    """Ein Tarif lässt sich anlegen — vorher gab es dafür keinen Weg.

    Das PUT konnte es schon (INSERT … ON CONFLICT), aber die Oberfläche
    lief nur über bestehende Zeilen; ein fünfter Tarif war damit nicht
    erreichbar.
    """
    konten = leere_konten
    lege_kunden_an(konten, "admin2@example.org", "geheim-genug-123")
    konten.setze_rolle(konten.nutzer_zu_email("admin2@example.org").id, "admin")
    klient = TestClient(main.app)
    melde_an(klient, "admin2@example.org", "geheim-genug-123")
    try:
        antwort = klient.put("/api/verwaltung/tarife/jahr", json={
            "name": "Jährlich", "beschreibung": "", "monatsbeitrag_cent": 0,
            "inklusiv_rechnungen": 0, "preis_je_rechnung_cent": 0,
            "reihenfolge": 50, "sichtbar": False, "hervorheben": False,
            "stripe_preis": "",
        })
        assert antwort.status_code == 200, antwort.text
        assert konten.tarif("jahr").name == "Jährlich"
    finally:
        with konten.verbindung() as verb:
            verb.execute("DELETE FROM tarife WHERE schluessel = 'jahr'")


def test_unbrauchbarer_tarifschluessel_wird_abgewiesen(leere_konten):
    """Der Schlüssel steht in der Adresse und haftet an jedem Konto.

    Ein Leerzeichen oder Umlaut darin fiele erst auf, wenn ein Konto ihn
    schon trägt — dann ist er nicht mehr zu ändern.
    """
    konten = leere_konten
    lege_kunden_an(konten, "admin3@example.org", "geheim-genug-123")
    konten.setze_rolle(konten.nutzer_zu_email("admin3@example.org").id, "admin")
    klient = TestClient(main.app)
    melde_an(klient, "admin3@example.org", "geheim-genug-123")
    daten = {
        "name": "X", "beschreibung": "", "monatsbeitrag_cent": 0,
        "inklusiv_rechnungen": 0, "preis_je_rechnung_cent": 0,
        "reihenfolge": 50, "sichtbar": False, "hervorheben": False,
        "stripe_preis": "",
    }
    for schluessel in ("Mein Tarif", "jähr", "A", "x" * 33):
        antwort = klient.put(f"/api/verwaltung/tarife/{schluessel}", json=daten)
        assert antwort.status_code == 422, f"{schluessel}: {antwort.status_code}"


def test_tarif_mit_konten_darauf_bleibt_stehen(leere_konten):
    """Löschen darf keinen Fremdschlüsselfehler auslösen.

    `nutzer.tarif` verweist auf `tarife`; ohne die Prüfung schlüge das
    Löschen mit einer Datenbankmeldung fehl, die niemand lesen kann.
    """
    konten = leere_konten
    konten.speichere_tarif(konten.Tarif(
        schluessel="weg", name="Weg", beschreibung="",
        monatsbeitrag_cent=0, inklusiv_rechnungen=0,
        preis_je_rechnung_cent=0, reihenfolge=99, sichtbar=False,
    ))
    lege_kunden_an(konten, "drauf@example.org", "geheim-genug-123", tarif="weg")
    try:
        with pytest.raises(konten.KontoFehler) as fehler:
            konten.loesche_tarif("weg")
        assert "noch ein Konto" in str(fehler.value)
        # Nach dem Umstellen geht es.
        person = konten.nutzer_zu_email("drauf@example.org")
        konten.setze_tarif(person.id, "probe")
        konten.loesche_tarif("weg")
        with pytest.raises(konten.KontoFehler):
            konten.tarif("weg")
    finally:
        with konten.verbindung() as verb:
            verb.execute("DELETE FROM tarife WHERE schluessel = 'weg'")


def test_standardtarif_laesst_sich_nicht_loeschen(leere_konten):
    """Auf ihn fallen Konten zurück, deren Abo endet."""
    konten = leere_konten
    with pytest.raises(konten.KontoFehler) as fehler:
        konten.loesche_tarif(konten.STANDARD_TARIF)
    assert "Standardtarif" in str(fehler.value)


def test_absender_ohne_klammeraffe_ist_keine_adresse():
    """Ohne @ ist es kein Absender — der Mailserver weist ihn ab.

    Aus dem Betrieb: Im Absenderfeld stand „Rechnungsblatt.de". Strato
    antwortete darauf mit `553 Missing '@' in e-mail address`, und die
    Fehlermeldung nannte danach den Empfänger — was die Suche in die
    falsche Richtung schickte.

    `rpartition("@")` allein lieferte für diesen Text die „Domain"
    rechnungsblatt.de, die Alignment-Prüfung ging durch, und nichts
    warnte.
    """
    from rechnungsblatt_web import dkim

    assert dkim.domain_von("Rechnungsblatt.de") == ""
    assert dkim.domain_von("Firma Müller") == ""
    assert dkim.domain_von("@nur-domain.de") == ""
    assert dkim.domain_von("no-reply@rechnungsblatt.de") == "rechnungsblatt.de"
    assert dkim.domain_von("Name <no-reply@rechnungsblatt.de>") == "rechnungsblatt.de"
    # Und damit greift auch die Alignment-Prüfung nicht mehr fälschlich.
    assert not dkim.passt("rechnungsblatt.de", "Rechnungsblatt.de")


def test_smtp_fehler_bekommen_eine_erklaerung():
    """Die Rohmeldung des Servers sagt nicht, was zu tun ist.

    „The read operation timed out" auf Port 465 heißt fast immer: Der Port
    ist unterwegs gesperrt, nicht falsch eingestellt. Das gehört dazu,
    sonst sucht man den Fehler bei Passwort und Server.
    """
    import smtplib

    from rechnungsblatt_web import post

    hilfe = post._hilfe_zum_fehler(
        TimeoutError("The read operation timed out"), "smtp.example.de", 465, True)
    assert "587" in hilfe

    hilfe = post._hilfe_zum_fehler(
        smtplib.SMTPRecipientsRefused({"x@y.de": (550, b"No such mailbox")}),
        "smtp.example.de", 587, False)
    assert "Empfänger" in hilfe

    hilfe = post._hilfe_zum_fehler(
        smtplib.SMTPSenderRefused(553, b"Missing '@'", "Rechnungsblatt.de"),
        "smtp.example.de", 587, False)
    assert "Absenderadresse" in hilfe

    # Ein unbekannter Fehler bekommt keinen erfundenen Rat.
    assert post._hilfe_zum_fehler(
        smtplib.SMTPException("irgendwas"), "smtp.example.de", 587, False) == ""


def test_nachricht_ist_crlf_terminiert():
    """SMTP verlangt CRLF am Zeilenende — ein nacktes LF ist ein Protokollfehler.

    Aus dem Betrieb: „554 SMTP protocol violation: A header line must be
    terminated by CRLF". `send_message` hat das früher selbst erledigt;
    seit hier `sendmail` mit fertigen Bytes verschickt — nötig, damit die
    DKIM-Signatur unangetastet bleibt — muss die Nachricht es mitbringen.
    """
    from email.message import EmailMessage

    from rechnungsblatt_web import dkim, post

    def nackte_lf(roh: bytes) -> int:
        return sum(1 for i, b in enumerate(roh)
                   if b == 0x0A and (i == 0 or roh[i - 1] != 0x0D))

    # Wie post.sende sie baut.
    from email import policy
    nachricht = EmailMessage(policy=policy.SMTP)
    nachricht["From"] = "Rechnungsblatt <no-reply@rechnungsblatt.de>"
    nachricht["To"] = "kunde@example.org"
    nachricht["Subject"] = "Ihr Bestätigungscode"
    nachricht.set_content("Ihr Code lautet 481920.\n\nRechnungsblatt\n")

    assert nackte_lf(nachricht.as_bytes()) == 0

    # Auch mit vorangestellter Signatur.
    pem = dkim.erzeuge_schluesselpaar()
    roh = dkim.unterschreibe(nachricht, "rechnungsblatt.de", "rb", pem)
    assert nackte_lf(roh) == 0

    # Und ohne DKIM, über den Weg in post.
    ohne = post._unterschreibe(nachricht, "no-reply@rechnungsblatt.de", {})
    assert nackte_lf(ohne) == 0


# ------------------------------------------------- Nachweise: Kontobindung

def test_fremder_bestaetigungscode_trifft_nicht_das_eigene_konto(leere_konten):
    """Ein Code gehört zu genau einem Konto — auch wenn er zufällig stimmt.

    Ohne die Bindung suchte die Abfrage allein über den Code-Hash. Ein
    sechsstelliger Code, gegen ein *eigenes* Wegwerfkonto geraten, traf
    dann irgendein offenes Konto: Der Fehlversuchszähler lief beim eigenen
    mit, die Grenze von fünf Versuchen war wirkungslos, und ein Treffer
    gab den Wiederherstellungscode des Fremden heraus — der öffnet dessen
    Datenschlüssel.
    """
    konten = leere_konten
    opfer, _ = konten.registriere("opfer@example.org", "geheim-genug-123")
    taeter, _ = konten.registriere("taeter@example.org", "geheim-genug-123")
    code_opfer = konten.lege_nachweis_an(opfer.id, konten.ZWECK_EMAIL)

    # Der Täter schickt den Code des Opfers, nennt aber sein eigenes Konto.
    with pytest.raises(konten.KontoFehler):
        konten.loese_nachweis_ein(code_opfer, konten.ZWECK_EMAIL,
                                  nutzer_id=taeter.id)

    # Der Nachweis des Opfers ist dabei nicht verbraucht worden.
    assert konten.loese_nachweis_ein(code_opfer, konten.ZWECK_EMAIL,
                                     nutzer_id=opfer.id) == opfer.id


def test_bestaetigen_ueber_die_api_bindet_an_die_genannte_adresse(leere_konten):
    """Derselbe Schutz über den Endpunkt, nicht nur in der Kontenschicht."""
    konten = leere_konten
    opfer, _ = konten.registriere("opfer2@example.org", "geheim-genug-123")
    konten.registriere("taeter2@example.org", "geheim-genug-123")
    code_opfer = konten.lege_nachweis_an(opfer.id, konten.ZWECK_EMAIL)

    klient = TestClient(main.app)
    antwort = klient.post("/api/email/bestaetigen", json={
        "email": "taeter2@example.org", "code": code_opfer,
    })
    assert antwort.status_code == 422
    # Und das Opfer ist weiterhin unbestätigt.
    assert konten.nutzer(opfer.id).email_bestaetigt is None


def test_ruecksetzmarke_braucht_keine_kontobindung(leere_konten):
    """Die Marke ist lang und zufällig — und steht in einem Link ohne Adresse.

    Hier kennt der Aufrufer das Konto nicht; eine Bindung wäre nicht
    möglich. Das ist der einzige Fall, in dem die Suche allein über den
    Nachweis richtig bleibt.
    """
    konten = leere_konten
    person, _ = konten.registriere("marke@example.org", "geheim-genug-123")
    marke = konten.lege_nachweis_an(person.id, konten.ZWECK_RUECKSETZEN)
    assert len(marke) >= 20, "kurze Marke wäre ratbar"
    assert konten.loese_nachweis_ein(marke, konten.ZWECK_RUECKSETZEN) == person.id


def test_erfolgreicher_versand_meldet_erfolg(leere_konten):
    """`sende` muss True liefern — sonst gilt eine verschickte Mail als Fehler.

    Aus dem Betrieb: Der Adminbereich meldete „Kein SMTP eingerichtet",
    obwohl die Nachricht ankam. Ursache war ein fehlendes `return` am Ende
    von `sende`; der Rückgabewert war None, und `if not verschickt` griff.
    """
    import smtplib
    from unittest.mock import patch

    from rechnungsblatt_web import post

    konten = leere_konten
    konten.setze_einstellungen({
        "smtp_host": "127.0.0.1", "smtp_port": "2525",
        "smtp_benutzer": "", "smtp_absender": "no-reply@example.de",
        "smtp_tls": "",
    })
    try:
        with patch.object(smtplib, "SMTP") as smtp:
            smtp.return_value.__enter__.return_value = smtp
            assert post.sende("kunde@example.org", "Test", "Hallo\n") is True
    finally:
        konten.setze_einstellungen({"smtp_host": "", "smtp_absender": ""})


def test_neuer_wiederherstellungscode_oeffnet_die_daten(leere_konten):
    """Der neue Code muss denselben Datenschlüssel öffnen wie der alte.

    Sonst wäre er wertlos: Er soll genau dann helfen, wenn das Passwort
    weg ist — und dann gibt es keinen zweiten Versuch. Der alte Code muss
    zugleich verfallen, sonst hülfe ein abgeschriebener Zettel weiter.
    """
    from rechnungsblatt_web import tresor

    konten = leere_konten
    person, alter = konten.registriere("code@example.org", "geheim-genug-123")
    konten.bestaetige_email(person.id)
    konten.setze_status(person.id, konten.STATUS_FREI)

    _, schluessel = konten.pruefe_anmeldung("code@example.org", "geheim-genug-123")
    assert schluessel is not None

    neuer = konten.erneuere_code(person.id, schluessel)
    assert neuer != alter

    def huelle_von(nutzer_id):
        with konten.verbindung() as verb:
            return bytes(verb.execute(
                "SELECT huelle_code FROM nutzer WHERE id = %s", (nutzer_id,)
            ).fetchone()["huelle_code"])

    # Der neue Code öffnet denselben Schlüssel …
    assert tresor.oeffne(huelle_von(person.id),
                         tresor.normalisiere_code(neuer)) == schluessel
    # … der alte nicht mehr.
    with pytest.raises(tresor.TresorFehler):
        tresor.oeffne(huelle_von(person.id), tresor.normalisiere_code(alter))


def test_neuer_code_verlangt_das_passwort(leere_konten):
    """Ein offener Bildschirm soll nicht genügen."""
    konten = leere_konten
    lege_kunden_an(konten, "schutz@example.org", "geheim-genug-123")
    klient = TestClient(main.app)
    melde_an(klient, "schutz@example.org", "geheim-genug-123")

    assert klient.post("/api/ich/wiederherstellungscode",
                       json={"passwort": "falsch"}).status_code == 403
    gut = klient.post("/api/ich/wiederherstellungscode",
                      json={"passwort": "geheim-genug-123"})
    assert gut.status_code == 200
    assert len(gut.json()["wiederherstellungscode"]) >= 20
