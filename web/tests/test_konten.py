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
