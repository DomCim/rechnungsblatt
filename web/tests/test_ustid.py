"""Die Bestätigungsabfrage — und vor allem: dass sie niemanden aussperrt.

Kein Test hier geht ins Netz. Die Antworten von VIES sind nachgestellt,
aber **nicht erfunden**: Die beiden entscheidenden Formen wurden am
10.09.2026 am echten Dienst gemessen und stehen unten im Wortlaut.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main
from rechnungsblatt_web import ustid

from hilfen import lege_kunden_an, melde_an

ZUGANG = ("kundin@example.de", "langgenug12")

# Am 10.09.2026 gemessen: eine erfundene deutsche Nummer.
ANTWORT_UNGUELTIG = {
    "isValid": False, "userError": "INVALID", "name": "---", "address": "---",
    "requestDate": "2026-09-10T20:40:59.133Z",
}
# Ebenfalls gemessen: eine ECHTE franzoesische Nummer, waehrend Frankreich
# drosselte. isValid sagt dasselbe wie oben -- der Unterschied steht allein
# in userError.
ANTWORT_GEDROSSELT = {
    "isValid": False, "userError": "MS_MAX_CONCURRENT_REQ", "name": "---",
    "address": "---", "requestDate": "2026-09-10T20:40:41.933Z",
}
ANTWORT_GUELTIG = {
    "isValid": True, "userError": "VALID", "name": "NEXT-CONCEPT",
    "address": "24 AVENUE GEORGES CLEMENCEAU\n67630 LAUTERBOURG",
    "requestDate": "2026-09-10T20:41:00.000Z",
}


@pytest.fixture
def klient(tmp_path, monkeypatch, leere_konten):
    monkeypatch.setattr(main, "DATEN", tmp_path)
    lege_kunden_an(leere_konten, *ZUGANG)
    k = TestClient(main.app)
    melde_an(k, *ZUGANG)
    return k


def antworte_mit(monkeypatch, koerper):
    def statt_netz(url, **kwargs):
        return httpx.Response(200, content=json.dumps(koerper).encode(),
                              headers={"content-type": "application/json"},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(ustid.httpx, "get", statt_netz)


# --- Die Falle -------------------------------------------------------

def test_gedrosselt_ist_nicht_ungueltig(monkeypatch):
    """Der wichtigste Test dieser Datei.

    VIES antwortet auf eine Anfrage, die es nicht beantworten konnte, mit
    ``isValid: false`` — genau wie auf eine ungültige Nummer. Wer nur
    darauf schaut, erklärt eine gültige Nummer für ungültig und schreckt
    einen Kunden davon ab, eine richtige Rechnung zu schreiben.
    """
    antworte_mit(monkeypatch, ANTWORT_GEDROSSELT)

    ergebnis = ustid.pruefe("FR53987550159", "FR")

    assert ergebnis["stand"] == ustid.UNBEKANNT
    assert ergebnis["stand"] != ustid.UNGUELTIG
    assert "MS_MAX_CONCURRENT_REQ" in ergebnis["grund"]


def test_ungueltig_bleibt_ungueltig(monkeypatch):
    antworte_mit(monkeypatch, ANTWORT_UNGUELTIG)
    assert ustid.pruefe("DE123456789", "DE")["stand"] == ustid.UNGUELTIG


def test_gueltig_bringt_namen_mit(monkeypatch):
    antworte_mit(monkeypatch, ANTWORT_GUELTIG)
    ergebnis = ustid.pruefe("FR53987550159", "FR")

    assert ergebnis["stand"] == ustid.GUELTIG
    assert ergebnis["name"] == "NEXT-CONCEPT"
    assert "LAUTERBOURG" in ergebnis["anschrift"]


def test_drei_striche_gelten_als_leer(monkeypatch):
    """VIES setzt „---“, wo der Mitgliedstaat nichts herausgibt."""
    antworte_mit(monkeypatch, ANTWORT_UNGUELTIG)
    ergebnis = ustid.pruefe("DE123456789", "DE")
    assert ergebnis["name"] == "" and ergebnis["anschrift"] == ""


# --- Nie blockieren --------------------------------------------------

def test_zeitueberschreitung_gibt_unbekannt_zurueck(monkeypatch):
    def statt_netz(url, **kwargs):
        raise httpx.ReadTimeout("zu langsam")
    monkeypatch.setattr(ustid.httpx, "get", statt_netz)

    ergebnis = ustid.pruefe("FR53987550159", "FR")

    assert ergebnis["stand"] == ustid.UNBEKANNT
    assert ergebnis["grund"] == "nicht erreichbar"


def test_muell_im_koerper_wirft_nicht(monkeypatch):
    def statt_netz(url, **kwargs):
        return httpx.Response(200, content=b"<html>Wartungsarbeiten</html>",
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(ustid.httpx, "get", statt_netz)
    assert ustid.pruefe("FR53987550159", "FR")["stand"] == ustid.UNBEKANNT


def test_drittland_wird_nicht_gefragt(monkeypatch):
    """Die Schweiz führt keine USt-IdNr. — da gibt es nichts zu fragen."""
    def darf_nicht(url, **kwargs):
        raise AssertionError("VIES darf für CH gar nicht gefragt werden")
    monkeypatch.setattr(ustid.httpx, "get", darf_nicht)

    assert ustid.pruefe("CHE-123.456.789 MWST", "CH")["stand"] == ustid.UNBEKANNT


def test_griechenland_wird_als_el_gefragt():
    """VIES kennt Griechenland als EL, nicht als GR."""
    assert ustid.zerlege("EL123456789", "GR") == ("EL", "123456789")


# --- Über den Weg ----------------------------------------------------

def test_endpunkt_merkt_sich_das_ergebnis(klient, monkeypatch):
    antworte_mit(monkeypatch, ANTWORT_GUELTIG)

    erste = klient.post("/api/ustid/pruefen",
                        json={"nummer": "FR 53 987 550 159", "land": "FR"})
    assert erste.status_code == 200
    assert erste.json()["stand"] == "gueltig"

    # Der Dienst schweigt beim zweiten Mal — das darf die Auskunft von
    # eben nicht entwerten.
    antworte_mit(monkeypatch, ANTWORT_GEDROSSELT)
    klient.post("/api/ustid/pruefen", json={"nummer": "FR53987550159", "land": "FR"})

    gemerkt = klient.get("/api/ustid/pruefungen").json()
    assert gemerkt["FR53987550159"]["stand"] == "gueltig", \
        "ein Schweigen darf ein Ja nicht ueberschreiben"
