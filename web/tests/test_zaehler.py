"""Die Besucherzählung über die eigene Adresse.

Diese Tests brauchen **keine Datenbank** und kein laufendes Plausible —
das interne Ziel wird als Attrappe eingesetzt.

Der Kern der Sache: Plausible ist vom Browser aus nicht erreichbar. Geht
etwas schief, darf das **nie** einen Fehler in der Konsole des Kunden
erzeugen; ein verlorener Seitenaufruf in der Statistik ist das kleinere
Übel.
"""

from __future__ import annotations

import httpx
import pytest

# Ohne zugehörige Anfrage wirft raise_for_status einen RuntimeError,
# statt den Status zu prüfen — die Attrappe braucht sie also.
ANFRAGE = httpx.Request("GET", "http://plausible:8000/js/script.js")

from rechnungsblatt_web import zaehler


@pytest.fixture(autouse=True)
def frischer_zwischenspeicher():
    """Das Skript wird eine Stunde gemerkt — sonst färben Tests aufeinander ab."""
    zaehler._gemerkt = None
    yield
    zaehler._gemerkt = None


@pytest.fixture
def mit_plausible(monkeypatch):
    """Eine Attrappe des internen Plausible."""
    monkeypatch.setattr(zaehler, "zaehladresse", lambda: "http://plausible:8000")


def test_ohne_einrichtung_kommt_ein_leeres_skript(monkeypatch):
    """Kein 404: Das Skript-Tag steht womöglich schon im Seitenkopf.

    Ein Fehler in der Konsole sähe nach einem kaputten Dienst aus.
    """
    monkeypatch.setattr(zaehler, "zaehladresse", lambda: "")

    antwort = zaehler.zaehlskript()

    assert antwort.status_code == 200
    assert b"keine" in antwort.body
    assert "javascript" in antwort.headers["content-type"]


def test_skript_wird_durchgereicht_und_bewacht(monkeypatch, mit_plausible):
    def falscher_abruf(url, **_):
        assert url == "http://plausible:8000/js/script.js"
        return httpx.Response(200, text="/* echtes plausible */", request=ANFRAGE)

    monkeypatch.setattr(zaehler.httpx, "get", falscher_abruf)

    text = zaehler.zaehlskript().body.decode("utf-8")

    assert "/* echtes plausible */" in text
    # Die Wache: Unter Fernsteuerung wird nicht gezählt, sonst
    # verfälschten die eigenen PageSpeed-Läufe die Statistik.
    assert "navigator.webdriver" in text
    assert "HeadlessChrome" in text


def test_skript_wird_zwischengespeichert(monkeypatch, mit_plausible):
    aufrufe = []

    def falscher_abruf(url, **_):
        aufrufe.append(url)
        return httpx.Response(200, text="/* eins */", request=ANFRAGE)

    monkeypatch.setattr(zaehler.httpx, "get", falscher_abruf)

    zaehler.zaehlskript()
    zaehler.zaehlskript()

    assert len(aufrufe) == 1, "Das Skript wurde zweimal geholt"


def test_unerreichbares_plausible_stoert_die_seite_nicht(monkeypatch, mit_plausible):
    """Steht die Statistik nicht, wird eben nicht gezählt — mehr nicht."""
    def falscher_abruf(url, **_):
        raise httpx.ConnectError("kein Netz")

    monkeypatch.setattr(zaehler.httpx, "get", falscher_abruf)

    antwort = zaehler.zaehlskript()

    assert antwort.status_code == 200
    assert b"nicht erreichbar" in antwort.body
    # Kurze Frist, damit es sich von selbst wieder einrenkt.
    assert "max-age=60" in antwort.headers["cache-control"]


def test_fehler_wird_nicht_zwischengespeichert(monkeypatch, mit_plausible):
    """Sonst bliebe die Zählung eine Stunde aus, obwohl Plausible längst läuft."""
    zustand = {"kaputt": True}

    def falscher_abruf(url, **_):
        if zustand["kaputt"]:
            raise httpx.ConnectError("kein Netz")
        return httpx.Response(200, text="/* wieder da */", request=ANFRAGE)

    monkeypatch.setattr(zaehler.httpx, "get", falscher_abruf)

    assert b"nicht erreichbar" in zaehler.zaehlskript().body
    zustand["kaputt"] = False
    assert b"wieder da" in zaehler.zaehlskript().body


def test_herkunft_nimmt_den_ersten_eintrag_der_kette():
    """Der erste Eintrag ist der Besucher, dahinter stehen die Proxys.

    Wer den letzten nimmt, misst seinen eigenen Proxy — dann wäre jeder
    Besucher derselbe und käme aus demselben Land.
    """
    class Attrappe:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1, 172.18.0.2"}

    assert zaehler._herkunft(Attrappe()) == "203.0.113.7"


def test_herkunft_faellt_auf_x_real_ip_zurueck():
    class Attrappe:
        headers = {"x-real-ip": "203.0.113.9"}

    assert zaehler._herkunft(Attrappe()) == "203.0.113.9"


def test_herkunft_ohne_angabe():
    class Attrappe:
        headers = {}

    assert zaehler._herkunft(Attrappe()) is None
