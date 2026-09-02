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

def test_agb_zahlen_guthaben_nicht_zurueck(klient):
    """Wer aufhört, bekommt sein Guthaben nicht zurück.

    Diese Klausel wurde einmal missverstanden, weil zwei gegenläufige
    Regeln in einem Semikolon-Satz standen. Getrennt formuliert gilt:
    Kündigt der Nutzer, wird nichts ausgezahlt. Nur wenn der Anbieter
    die Anwendung einstellt, gibt es — nach drei Monaten Vorlauf zum
    Aufbrauchen — eine Erstattung.
    """
    fliesstext = " ".join(klient.get("/agb").text.split())

    assert "Auszahlung nicht verbrauchten Guthabens erfolgt nicht" in fliesstext
    # Und ausdrücklich für den Fall, dass der Nutzer selbst beendet.
    assert "wenn der Nutzer den Vertrag beendet" in fliesstext
    # Die Ankündigungsfrist ist der Ausweg statt einer Zahlung.
    assert "drei Monate vorher" in fliesstext

def test_llms_txt_ist_erreichbar_und_grenzt_ab(klient):
    """llms.txt — vor allem für das Richtigstellen.

    Der Nutzen liegt weniger im Bewerben: Ein Modell, das die Seite
    überfliegt, hält Rechnungsblatt leicht für eine Buchhaltung oder
    für zertifiziert. Die Abgrenzungen müssen darin stehen bleiben.
    """
    antwort = klient.get("/llms.txt")

    assert antwort.status_code == 200
    assert "text/plain" in antwort.headers["content-type"]
    text = antwort.text
    assert text.startswith("# Rechnungsblatt")
    for abgrenzung in (
        "Keine Buchhaltung",
        "Nicht GoBD-zertifiziert",
        "Kein Achtjahresarchiv",
        "Nicht offline nutzbar",
    ):
        assert abgrenzung in text, f"Abgrenzung fehlt: {abgrenzung}"


def test_startseite_verweist_auf_den_betreiber(klient):
    """Der Verweis auf did0m.dev — ohne nofollow.

    Mit nofollow wäre er für Ranking und Search Console wertlos. Es
    sind eigene Domains und der Zusammenhang ist inhaltlich begründet,
    also darf die Linkkraft fließen.
    """
    text = klient.get("/").text

    assert 'href="https://did0m.dev"' in text
    assert "nofollow" not in text
    # Und die maschinenlesbare Verknüpfung, die mehr wiegt als der Link.
    assert '"publisher"' in text
    assert '"url": "https://did0m.dev"' in text

# Bing beanstandet Meta-Beschreibungen als „too long or too short". Die
# Grenzen sind nirgends amtlich, aber gemessen: Über etwa 158 Zeichen
# schneiden Google und Bing ab, unter etwa 70 hält Bing sie für zu kurz.
#
# Am 2026-09-02 gemeldet: Startseite 211 Zeichen. Die drei Rechtsseiten
# lagen bei 39 bis 60 und wären als nächstes aufgefallen.
BESCHREIBUNG_MIN = 70
BESCHREIBUNG_MAX = 158


@pytest.mark.parametrize("datei", [
    "start.html", "impressum.html", "datenschutz.html", "agb.html",
])
def test_meta_beschreibung_hat_brauchbare_laenge(datei):
    """Jede öffentliche Seite braucht eine Beschreibung passender Länge.

    Ohne sie bildet die Suchmaschine einen Auszug aus dem Text — bei
    einem Rechtstext wird das unbrauchbar.
    """
    text = (SEITEN / datei).read_text(encoding="utf-8")

    treffer = re.search(r'<meta name="description" content="([^"]*)"', text)
    assert treffer, f"{datei}: keine Meta-Beschreibung"

    laenge = len(treffer.group(1))
    assert BESCHREIBUNG_MIN <= laenge <= BESCHREIBUNG_MAX, (
        f"{datei}: Beschreibung hat {laenge} Zeichen, erwartet "
        f"{BESCHREIBUNG_MIN} bis {BESCHREIBUNG_MAX}"
    )


@pytest.mark.parametrize("datei", [
    "start.html", "impressum.html", "datenschutz.html", "agb.html",
])
def test_titel_hat_brauchbare_laenge(datei):
    """Titel über etwa 60 Zeichen schneidet Google in der Trefferliste ab."""
    text = (SEITEN / datei).read_text(encoding="utf-8")

    treffer = re.search(r"<title>(.*?)</title>", text, re.S)
    assert treffer, f"{datei}: kein Titel"

    # Entities zählen als ein Zeichen, nicht als sechs.
    titel = re.sub(r"&[a-zA-Z]+;", "x", treffer.group(1)).strip()
    assert 15 <= len(titel) <= 65, (
        f"{datei}: Titel hat {len(titel)} Zeichen"
    )

def test_indexnow_schluessel_ist_abrufbar(klient):
    """Der Eigentumsnachweis für IndexNow.

    Bing, Yandex und Seznam holen diese Datei, bevor sie eine gemeldete
    Adresse annehmen. Fehlt sie oder weicht ihr Inhalt ab, werden
    Meldungen **stillschweigend** verworfen — man erfährt es nicht,
    sondern merkt nur, dass nichts passiert.

    Der Dateiname muss der Schlüssel sein, der Inhalt genau derselbe,
    und beides in der Wurzel — nicht unter /seiten/.
    """
    from rechnungsblatt_web.wege_seiten import INDEXNOW_SCHLUESSEL

    antwort = klient.get(f"/{INDEXNOW_SCHLUESSEL}.txt")

    assert antwort.status_code == 200
    assert "text/plain" in antwort.headers["content-type"]
    # Genau der Schlüssel, ohne Zeilenumbruch und ohne BOM.
    assert antwort.text == INDEXNOW_SCHLUESSEL
    assert len(INDEXNOW_SCHLUESSEL) == 32


def test_robots_sperrt_den_indexnow_schluessel_nicht(klient):
    """`Allow: /$` erlaubt nur die Wurzel exakt — sperrt aber nichts.

    Die Regel sieht restriktiver aus, als sie ist. Der Test hält fest,
    dass die öffentlichen Dateien erreichbar bleiben und der
    Arbeitsbereich gesperrt ist.
    """
    import urllib.robotparser

    from rechnungsblatt_web.wege_seiten import INDEXNOW_SCHLUESSEL

    leser = urllib.robotparser.RobotFileParser()
    leser.parse(klient.get("/robots.txt").text.splitlines())

    for pfad in (
        "/",
        f"/{INDEXNOW_SCHLUESSEL}.txt",
        "/llms.txt",
        "/impressum",
        "/sitemap.xml",
    ):
        assert leser.can_fetch("*", pfad), f"{pfad} ist gesperrt"

    # Und die Gegenprobe: Der Arbeitsbereich bleibt draußen.
    assert not leser.can_fetch("*", "/app/konto")
    assert not leser.can_fetch("*", "/api/ich")
