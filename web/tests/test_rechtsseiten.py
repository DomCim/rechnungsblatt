"""Impressum, Datenschutz, AGB — und dass man sie findet.

**Warum das unter Test steht.** § 5 DDG verlangt die Anbieterangaben
„leicht erkennbar, unmittelbar erreichbar und ständig verfügbar". Ein
Verweis, der bei einem Umbau der Fußzeile verschwindet, ist keine
Kleinigkeit: Fehlende Pflichtangaben sind abmahnfähig, und auffallen
würde es erst durch die Abmahnung.

Diese Tests brauchen keine Datenbank.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main

SEITEN = Path(__file__).resolve().parents[1] / "src/rechnungsblatt_web/seiten"


@pytest.fixture(scope="module")
def klient():
    """Ohne Anmeldung — die Rechtsseiten müssen offen sein."""
    return TestClient(main.app)


@pytest.mark.parametrize("pfad", ["/impressum", "/datenschutz", "/agb"])
def test_rechtsseiten_sind_ohne_anmeldung_erreichbar(klient, pfad):
    """Ohne Anmeldung und ohne Umleitung.

    Ein Impressum hinter einer Anmeldung wäre keins.
    """
    antwort = klient.get(pfad, follow_redirects=False)

    assert antwort.status_code == 200, f"{pfad} antwortet {antwort.status_code}"
    assert "text/html" in antwort.headers["content-type"]


def test_impressum_nennt_den_anbieter(klient):
    text = klient.get("/impressum").text

    # Name, Anschrift und ein Weg zur Kontaktaufnahme — § 5 Abs. 1 DDG.
    assert "Dominik Dill" in text
    assert "Goldammerweg 25" in text
    assert "95119 Naila" in text
    assert "mailto:" in text


def test_impressum_nennt_keine_steuernummer(klient):
    """Die persönliche Steuernummer gehört nicht ins Impressum.

    § 5 DDG verlangt nur die USt-IdNr., und die gibt es hier nicht.
    Eine veröffentlichte Steuernummer ist personenbezogen und bringt
    keinen Nutzen — sie stand einmal zur Debatte und wurde bewusst
    weggelassen.
    """
    text = klient.get("/impressum").text

    assert not re.search(r"\b\d{11}\b", text), "Da steht eine Steuernummer"
    assert "Steuernummer" not in text


def test_impressum_nennt_die_kleinunternehmerregelung(klient):
    """Warum keine USt-IdNr. dasteht, muss erklärt sein.

    Sonst sieht es wie eine Lücke aus.
    """
    text = klient.get("/impressum").text
    assert "19" in text and "UStG" in text


def test_datenschutz_nennt_die_pflichtangaben(klient):
    text = klient.get("/datenschutz").text

    # Verantwortlicher, Rechtsgrundlagen, Rechte, Aufsichtsbehörde.
    assert "Verantwortlicher" in text
    assert "DSGVO" in text
    assert "Landesamt f&uuml;r Datenschutzaufsicht" in text
    for artikel in ("15", "16", "17", "20", "21"):
        assert f"Art.&nbsp;{artikel}" in text, f"Art. {artikel} fehlt"


def test_datenschutz_nennt_stripe_und_die_zaehlung(klient):
    """Zwei Verarbeitungen, die tatsächlich stattfinden."""
    text = klient.get("/datenschutz").text

    assert "Stripe" in text
    assert "Plausible" in text
    # Und die Aussage, die das Besondere ist.
    assert "Kartendaten erreichen diesen Server nie" in text


def test_agb_nennen_widerruf_und_haftung(klient):
    text = klient.get("/agb").text

    assert "Widerrufsrecht" in text
    assert "355 BGB" in text.replace("&nbsp;", " ")
    assert "Haftung" in text
    # Der Punkt, der dieses Produkt betrifft. Über Zeilenumbrüche hinweg
    # prüfen — der Satz ist im Quelltext umbrochen.
    fliesstext = " ".join(text.split())
    assert "keine Steuerberatung und keine Rechtsberatung" in fliesstext


def test_agb_nennen_den_verlust_der_zugangsdaten(klient):
    """Der Kunde muss vorher wissen, dass ihm niemand helfen kann.

    Die Daten liegen verschlüsselt, der Schlüssel hängt am Kennwort.
    Erfährt der Kunde das erst im Ernstfall, ist es zu spät.
    """
    text = klient.get("/agb").text

    assert "nicht wiederhergestellt" in text
    assert "Wiederherstellungscode" in text


@pytest.mark.parametrize("seite", ["start.html", "konto.html"])
def test_verweise_auf_die_rechtsseiten_stehen_in_der_seite(seite):
    """Die Verweise selbst — § 5 DDG verlangt „leicht erkennbar".

    Ohne sie sind die Seiten da, aber niemand findet sie.
    """
    text = (SEITEN / seite).read_text(encoding="utf-8")

    for ziel in ("/impressum", "/datenschutz", "/agb"):
        assert f'href="{ziel}"' in text, f"{seite}: Verweis auf {ziel} fehlt"


def test_rechtsseiten_haben_keine_uebersetzung_noetig():
    """Sie sind bewusst nur deutsch — und tragen kein data-i18n.

    Ein halb übersetzter Rechtstext wäre schlimmer als ein deutscher:
    Bei Abweichungen wäre unklar, welche Fassung gilt.
    """
    for name in ("impressum.html", "datenschutz.html", "agb.html"):
        text = (SEITEN / name).read_text(encoding="utf-8")
        assert "data-i18n" not in text, f"{name} trägt data-i18n"
        assert 'lang="de"' in text
