"""API-Tests der Web-Schicht: kompletter Einrichtungs- und Rechnungs-Ablauf."""

import shutil

import pytest
from fastapi.testclient import TestClient

from rechnungsblatt_kern.testbogen import erzeuge_testbogen
import rechnungsblatt_web.main as main

from hilfen import lege_kunden_an, melde_an

benoetigt_gs = pytest.mark.skipif(
    shutil.which("gs") is None, reason="Ghostscript nicht installiert"
)

STAMMDATEN = {
    "firmierung": "Muster & Partner GmbH",
    "anschrift": {"strasse": "Bahnhofstr. 12", "plz": "95119", "ort": "Naila"},
    "steuernummer": "223/456/78901",
    "ust_idnr": "DE123456789",
    "iban": "DE14 7805 0000 0001 2345 67",
    "bic": "BYLADEM1HOF",
    "zahlungsziel_tage": 14,
    "kontakt_name": "Max Muster",
    "kontakt_email": "info@muster-partner.de",
    "kontakt_telefon": "09282 12345",
    "kleinunternehmer": False,
}

RECHNUNG = {
    "typ": "RECHNUNG",
    "nummer": "RE-2026-0001",
    "rechnungsdatum": "2026-08-21",
    "leistungsdatum": "2026-08-20",
    "faelligkeit": "2026-09-04",
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


PRUEFER = ("pruefer@example.de", "pruefpasswort")


@pytest.fixture
def client(tmp_path, monkeypatch, leere_konten):
    """Angemeldeter Mandant ohne Mengenbegrenzung auf einem leeren Verzeichnis."""
    monkeypatch.setattr(main, "DATEN", tmp_path)
    lege_kunden_an(leere_konten, *PRUEFER)
    klient = TestClient(main.app)
    melde_an(klient, *PRUEFER)
    return klient


def _richte_ein(client):
    antwort = client.post(
        "/api/briefpapier",
        files={"datei": ("bogen.pdf", erzeuge_testbogen("gut"), "application/pdf")},
    )
    assert antwort.status_code == 200, antwort.text
    assert client.put(
        "/api/schreibzone", json={"kopf_ende_mm": 52, "fuss_beginn_mm": 25}
    ).status_code == 200
    assert client.put("/api/stammdaten", json=STAMMDATEN).status_code == 200


def test_seiten_laden(client):
    assert "Einrichtung" in client.get("/app/einrichtung").text
    assert "positionen" in client.get("/app/rechnung").text
    assert client.get("/app/ablage").status_code == 200
    assert client.get("/zonen-editor/").status_code == 200


def test_oeffentliche_startseite_ohne_anmeldung():
    """Die Startseite erklärt das Modell und braucht kein Konto."""
    klient = TestClient(main.app)
    seite = klient.get("/")
    assert seite.status_code == 200
    assert "Briefpapier" in seite.text
    assert klient.get("/anmelden").status_code == 200


def test_status_anfangs_leer(client):
    status = client.get("/api/status").json()
    assert status["bereit"] is False
    assert status["briefpapier"] is None


def test_rechnung_ohne_einrichtung_wird_abgewiesen(client):
    antwort = client.post("/api/rechnung", json=RECHNUNG)
    assert antwort.status_code == 409
    assert "Einrichtung unvollständig" in antwort.json()["detail"]["grund"]


@benoetigt_gs
def test_kompletter_ablauf(client):
    _richte_ein(client)
    assert client.get("/api/status").json()["bereit"] is True
    assert client.get("/api/briefpapier/vorschau.png").headers["content-type"] == "image/png"

    antwort = client.post("/api/rechnung", json=RECHNUNG)
    assert antwort.status_code == 200, antwort.text
    ergebnis = antwort.json()
    assert ergebnis["brutto"] == "238.00"

    pdf = client.get(ergebnis["pdf"])
    assert pdf.content[:5] == b"%PDF-"
    xml = client.get(ergebnis["xml"])
    assert b"urn:cen.eu:en16931:2017" in xml.content

    belege = client.get("/api/ablage").json()
    assert belege[0]["nummer"] == "RE-2026-0001"
    assert belege[0]["empfaenger"] == "Beispielkunde GmbH"

    # Nummernkreis zählt weiter
    assert client.get("/api/nummer/vorschlag").json()["nummer"] == "RE-2026-0002"


@benoetigt_gs
def test_befunde_mit_codes(client):
    _richte_ein(client)
    kaputt = dict(RECHNUNG, nummer="", leistungsdatum=None)
    antwort = client.post("/api/rechnung", json=kaputt)
    assert antwort.status_code == 422
    codes = {befund["code"] for befund in antwort.json()["befunde"]}
    assert {"R1", "R3"} <= codes


@benoetigt_gs
def test_mehrseitiger_upload_wird_abgelehnt(client, tmp_path):
    import io

    import pikepdf

    quelle = pikepdf.open(io.BytesIO(erzeuge_testbogen("gut")))
    doppelt = pikepdf.new()
    doppelt.pages.extend([quelle.pages[0], quelle.pages[0]])
    puffer = io.BytesIO()
    doppelt.save(puffer)
    antwort = client.post(
        "/api/briefpapier",
        files={"datei": ("doppelt.pdf", puffer.getvalue(), "application/pdf")},
    )
    assert antwort.status_code == 422
    assert "mehrere Seiten" in antwort.json()["detail"]["grund"]


@benoetigt_gs
def test_xrechnung_download(client):
    _richte_ein(client)
    behoerde = dict(
        RECHNUNG,
        empfaenger={
            "name": "Stadt Hof",
            "anschrift": {"strasse": "Klosterstr. 1", "plz": "95028", "ort": "Hof"},
            "leitweg_id": "09464000-12345-06",
            "email": "rechnung@stadt-hof.example.de",
        },
    )
    antwort = client.post("/api/rechnung/xrechnung", json=behoerde)
    assert antwort.status_code == 200
    assert b"xrechnung_3.0" in antwort.content

    # ohne Leitweg-ID: Befund X1
    antwort = client.post("/api/rechnung/xrechnung", json=RECHNUNG)
    assert antwort.status_code == 422
    assert "X1" in {befund["code"] for befund in antwort.json()["befunde"]}


def test_word_upload_bekommt_pdf_anleitung(client):
    antwort = client.post(
        "/api/briefpapier",
        files={
            "datei": (
                "briefbogen.docx",
                b"PK\x03\x04egal",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert antwort.status_code == 422
    detail = antwort.json()["detail"]
    assert detail["code"] == "word_datei"
    assert "Speichern unter" in detail["grund"]


def test_nicht_pdf_upload_bekommt_pdf_anleitung(client):
    antwort = client.post(
        "/api/briefpapier",
        files={"datei": ("bild.png", b"\x89PNG\r\n\x1a\n...", "image/png")},
    )
    assert antwort.status_code == 422
    detail = antwort.json()["detail"]
    assert detail["code"] == "kein_pdf"
    assert "PDF" in detail["grund"]


@benoetigt_gs
def test_nummern_muster_und_verwendungszweck(client):
    _richte_ein(client)
    eigene = dict(
        STAMMDATEN,
        nummern_muster="MP{JJ}-{NNN}",
        verwendungszweck_muster="Rechnung {NUMMER} vom {DATUM}",
    )
    assert client.put("/api/stammdaten", json=eigene).status_code == 200

    vorschlag = client.get("/api/nummer/vorschlag").json()["nummer"]
    assert vorschlag == "MP26-001"

    rechnung = dict(RECHNUNG, nummer=vorschlag)
    antwort = client.post("/api/rechnung", json=rechnung)
    assert antwort.status_code == 200, antwort.text
    xml = client.get(antwort.json()["xml"]).content
    assert b"<ram:PaymentReference>Rechnung MP26-001 vom 21.08.2026</ram:PaymentReference>" in xml

    # Zähler ist fortgeschrieben
    assert client.get("/api/nummer/vorschlag").json()["nummer"] == "MP26-002"

    # kaputtes Muster wird abgewiesen
    kaputt = client.put("/api/stammdaten", json=dict(STAMMDATEN, nummern_muster="RE-{JJJJ}"))
    assert kaputt.status_code == 422
    assert kaputt.json()["detail"]["code"] == "nummern_muster"


@benoetigt_gs
def test_kundenstamm_wird_gepflegt(client):
    _richte_ein(client)
    mit_details = dict(
        RECHNUNG,
        empfaenger=dict(
            RECHNUNG["empfaenger"],
            ust_idnr="ATU12345678",
            email="buchhaltung@beispielkunde.example",
        ),
    )
    assert client.post("/api/rechnung", json=mit_details).status_code == 200
    kunden = client.get("/api/kunden").json()
    assert kunden[0]["name"] == "Beispielkunde GmbH"
    assert kunden[0]["ust_idnr"] == "ATU12345678"
    assert kunden[0]["email"] == "buchhaltung@beispielkunde.example"

    # gleicher Kunde erneut, andere Daten → Upsert, kein Duplikat
    geaendert = dict(
        mit_details,
        nummer="RE-2026-0002",
        empfaenger=dict(mit_details["empfaenger"], email="neu@beispielkunde.example"),
    )
    assert client.post("/api/rechnung", json=geaendert).status_code == 200
    kunden = client.get("/api/kunden").json()
    assert len(kunden) == 1
    assert kunden[0]["email"] == "neu@beispielkunde.example"


@benoetigt_gs
def test_girocode_schalter(client):
    _richte_ein(client)
    mit = client.post("/api/rechnung", json=RECHNUNG)
    assert mit.status_code == 200
    pdf_mit = client.get(mit.json()["pdf"]).content

    client.put("/api/stammdaten", json=dict(STAMMDATEN, girocode=False))
    ohne = client.post("/api/rechnung", json=dict(RECHNUNG, nummer="RE-2026-0002"))
    assert ohne.status_code == 200
    pdf_ohne = client.get(ohne.json()["pdf"]).content
    # Der QR-Code (hunderte Vektor-Rechtecke) macht das PDF messbar größer
    assert len(pdf_mit) > len(pdf_ohne) + 1000


def test_gestaltung_speichern_und_status(client):
    schriften = client.get("/api/gestaltung/schriften").json()
    assert {"liberation-sans", "carlito"} <= {s["schluessel"] for s in schriften}

    antwort = client.put(
        "/api/gestaltung",
        json={"schrift": "carlito", "schriftgrad": "gross", "layout": "modern"},
    )
    assert antwort.status_code == 200
    assert client.get("/api/status").json()["gestaltung"]["schrift"] == "carlito"

    kaputt = client.put("/api/gestaltung", json={"schrift": "comic-sans"})
    assert kaputt.status_code == 422


@benoetigt_gs
def test_gestaltungsvorschau_png(client):
    antwort = client.get(
        "/api/gestaltung/vorschau.png?schrift=caladea&schriftgrad=kompakt&layout=kompakt"
    )
    assert antwort.status_code == 200
    assert antwort.content[:8] == b"\x89PNG\r\n\x1a\n"


@benoetigt_gs
def test_rechnung_nutzt_gespeicherte_gestaltung(client):
    _richte_ein(client)
    client.put(
        "/api/gestaltung",
        json={"schrift": "caladea", "schriftgrad": "normal", "layout": "modern"},
    )
    antwort = client.post("/api/rechnung", json=RECHNUNG)
    assert antwort.status_code == 200, antwort.text
    pdf = client.get(antwort.json()["pdf"]).content
    assert b"Caladea" in pdf  # eingebettete Schrift taucht im PDF auf


def test_ablage_pfadausbruch_wird_abgewiesen(client):
    assert client.get("/api/ablage/..%2F..%2Fstammdaten/pdf").status_code in (404, 422)


@benoetigt_gs
def test_vergebene_nummer_wird_nicht_ueberschrieben(client):
    """Eine erteilte Rechnung darf nicht geändert werden.

    Ohne diese Sperre überschriebe ein zweiter Aufruf mit derselben Nummer
    PDF, XML und Daten des ersten Belegs — die fortlaufende Nummerierung
    wäre wertlos, weil hinter einer Nummer nacheinander verschiedene
    Rechnungen stünden. Korrigiert wird per Gutschrift, nicht durch
    Überschreiben.
    """
    _richte_ein(client)
    assert client.post("/api/rechnung", json=RECHNUNG).status_code == 200

    anders = dict(RECHNUNG)
    anders["empfaenger"] = dict(RECHNUNG["empfaenger"], name="Jemand anderes")
    antwort = client.post("/api/rechnung", json=anders)
    assert antwort.status_code == 409, antwort.text
    assert antwort.json()["code"] == "nummer_vergeben"

    # Der erste Beleg steht unverändert.
    belege = client.get("/api/ablage").json()
    assert [b["nummer"] for b in belege] == [RECHNUNG["nummer"]]
    assert belege[0]["empfaenger"] == RECHNUNG["empfaenger"]["name"]


@benoetigt_gs
def test_gutschrift_traegt_bezug_zur_ursprungsrechnung(client):
    """Der Storno-Weg: Gutschrift mit Bezug, eigene Nummer.

    Der Bezug ist Pflicht (Befund G1) und landet als
    InvoiceReferencedDocument im XML — daran erkennt der Empfänger, welche
    Rechnung aufgehoben wird.
    """
    _richte_ein(client)
    assert client.post("/api/rechnung", json=RECHNUNG).status_code == 200

    ohne_bezug = dict(RECHNUNG, nummer="GS-2026-0001", typ="GUTSCHRIFT")
    antwort = client.post("/api/rechnung", json=ohne_bezug)
    assert antwort.status_code == 422
    assert "G1" in [b["code"] for b in antwort.json()["befunde"]]

    gutschrift = dict(ohne_bezug, bezugs_nummer=RECHNUNG["nummer"])
    antwort = client.post("/api/rechnung", json=gutschrift)
    assert antwort.status_code == 200, antwort.text
    xml = client.get(antwort.json()["xml"]).content
    assert b"<ram:TypeCode>381</ram:TypeCode>" in xml
    assert RECHNUNG["nummer"].encode() in xml
