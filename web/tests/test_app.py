"""API-Tests der Web-Schicht: kompletter Einrichtungs- und Rechnungs-Ablauf."""

import shutil

import pytest
from fastapi.testclient import TestClient

from rechnungsblatt_kern.testbogen import erzeuge_testbogen
import rechnungsblatt_web.main as main

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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATEN", tmp_path)
    return TestClient(main.app)


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
    assert "Einrichtung" in client.get("/").text
    assert "positionen" in client.get("/rechnung").text
    assert client.get("/zonen-editor/").status_code == 200


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
