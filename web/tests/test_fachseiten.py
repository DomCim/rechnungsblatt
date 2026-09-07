"""Die oeffentlichen Fachseiten — dass es sie gibt und dass sie gefunden werden.

**Warum das unter Test steht.** Diese Seiten haben genau einen Zweck: in
einer Suchmaschine gefunden zu werden. Alles, woran das scheitern kann,
scheitert stillschweigend — eine Seite, die nicht in der Sitemap steht,
eine Sitemap, die ein Datum von gestern erfindet, ein Verweis, der beim
naechsten Umbau der Startseite herausfaellt. Nichts davon wirft einen
Fehler; man merkt es erst Monate spaeter an der Search Console.

Diese Tests brauchen keine Datenbank.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import rechnungsblatt_web.main as main
from rechnungsblatt_web.wege_seiten import FACHSEITEN, SITEMAP

SEITEN = Path(__file__).resolve().parents[1] / "src/rechnungsblatt_web/seiten"


@pytest.fixture(scope="module")
def klient():
    """Ohne Anmeldung — die Fachseiten sind Werbung, kein Arbeitsbereich."""
    return TestClient(main.app)


# --- Erreichbarkeit --------------------------------------------------


@pytest.mark.parametrize("name", FACHSEITEN)
def test_fachseite_ist_ohne_anmeldung_erreichbar(klient, name):
    antwort = klient.get(f"/{name}", follow_redirects=False)

    assert antwort.status_code == 200, f"/{name} antwortet {antwort.status_code}"
    assert "text/html" in antwort.headers["content-type"]


def test_uebersicht_ist_erreichbar(klient):
    antwort = klient.get("/funktionen", follow_redirects=False)

    assert antwort.status_code == 200
    assert "text/html" in antwort.headers["content-type"]


@pytest.mark.parametrize("name", FACHSEITEN)
def test_uebersicht_verweist_auf_jede_fachseite(klient, name):
    """Eine Seite, die von nirgends verlinkt ist, wird auch nicht gelesen."""
    text = klient.get("/funktionen").text

    assert f'href="/{name}"' in text, f"/{name} fehlt auf der Uebersicht"


@pytest.mark.parametrize("name", FACHSEITEN)
def test_startseite_verweist_auf_jede_fachseite(klient, name):
    """Der wichtigste Verweisblock: von der Startseite in die Tiefe.

    Ueber die Sitemap allein findet eine Suchmaschine die Seiten zwar,
    gewichtet sie aber kaum. Verweise von der staerksten Seite des
    Angebots sind das, was zaehlt — und genau die verschwinden beim
    naechsten Umbau der Startseite, wenn niemand hinsieht.
    """
    text = klient.get("/").text

    assert f'href="/{name}' in text, f"/{name} ist von der Startseite nicht verlinkt"


def test_jeder_listeneintrag_der_startseite_fuehrt_irgendwohin(klient):
    """Die Liste "Was noch drin steckt" ist die Navigation in die Tiefe.

    Ein einzelner Eintrag ohne Weg sieht nicht nach Absicht aus, sondern
    nach Fehler — neben elf Nachbarn, die klickbar sind, erst recht.
    Deshalb steht hier, dass **jeder** Eintrag einen Weg hat, und nicht
    nur, dass es Wege gibt.
    """
    text = klient.get("/").text

    eintraege = re.findall(r"<dt>(.*?)</dt>", text, re.S)
    assert eintraege, "Die Liste auf der Startseite ist verschwunden"

    ohne_weg = [e.strip() for e in eintraege if 'href="' not in e]
    assert not ohne_weg, f"Listeneintraege ohne Weg: {ohne_weg}"


def test_anker_der_startseiten_verweise_gibt_es_wirklich(klient):
    """Ein Verweis auf #layouts, den es nicht gibt, landet oben.

    Das faellt niemandem auf: Die Seite oeffnet sich, nur eben an der
    falschen Stelle. Genau deshalb steht es unter Test — geprueft wird
    gegen die ausgelieferte Seite, nicht gegen eine Liste im Test.
    """
    startseite = klient.get("/").text

    verweise = set(re.findall(r'href="(/[a-z-]+)#([a-z-]+)"', startseite))
    assert verweise, "Kein Verweis mit Anker auf der Startseite"

    for pfad, anker in sorted(verweise):
        ziel = klient.get(pfad)
        assert ziel.status_code == 200, f"{pfad} antwortet {ziel.status_code}"
        assert f'id="{anker}"' in ziel.text, f"{pfad} hat keinen Anker #{anker}"


# --- Kopfangaben -----------------------------------------------------


@pytest.mark.parametrize("pfad", ["funktionen", *FACHSEITEN])
def test_fachseite_traegt_ihre_kopfangaben(klient, pfad):
    """Titel, Beschreibung, Canonical — ohne die drei ist die Seite blind.

    Die Laenge der Beschreibung ist nicht kosmetisch: Bing meldet eine
    zu lange als Fehler und schneidet ab, eine zu kurze haelt es fuer
    unbrauchbar. Dieselbe Grenze wie auf der Startseite.
    """
    text = klient.get(f"/{pfad}").text

    titel = re.search(r"<title>(.*?)</title>", text, re.S)
    assert titel, f"/{pfad} hat keinen Titel"
    assert 10 < len(titel.group(1)) <= 75, f"/{pfad}: Titel {len(titel.group(1))} Zeichen"

    beschreibung = re.search(
        r'<meta name="description" content="(.*?)">', text, re.S
    )
    assert beschreibung, f"/{pfad} hat keine Beschreibung"
    laenge = len(beschreibung.group(1))
    assert 70 <= laenge <= 170, f"/{pfad}: Beschreibung {laenge} Zeichen"

    assert f'<link rel="canonical" href="/{pfad}">' in text, f"/{pfad}: Canonical falsch"
    assert '<meta name="robots" content="index, follow' in text, (
        f"/{pfad} darf nicht auf noindex stehen"
    )


@pytest.mark.parametrize("pfad", ["funktionen", *FACHSEITEN])
def test_fachseite_nennt_ihre_grenzen(klient, pfad):
    """Jede Fachseite sagt auch, was Rechnungsblatt nicht tut.

    Das ist keine Marotte, sondern die Linie aus `llms.txt` und der
    Startseite: Eine Seite, die nur verspricht, wird beim ersten
    Gegenbeweis im Ganzen unglaubwuerdig. Auf der Uebersicht steht der
    Grundsatz, auf den Fachseiten der Abschnitt.
    """
    text = klient.get(f"/{pfad}").text

    if pfad == "funktionen":
        assert "nicht tut" in text
    else:
        assert 'class="grenze"' in text, f"/{pfad} hat keinen Grenzen-Abschnitt"


@pytest.mark.parametrize("pfad", ["funktionen", *FACHSEITEN])
def test_fachseite_ist_zweisprachig(klient, pfad):
    """Deutsch steht im Markup, Englisch im Textobjekt.

    Beides muss vollstaendig sein: Ein `data-i18n`-Schluessel ohne
    englische Entsprechung faellt beim Umschalten auf den Schluessel
    selbst zurueck — die Seite zeigt dann `t17` statt eines Satzes.
    """
    text = klient.get(f"/{pfad}").text

    schluessel = set(re.findall(r'data-i18n="([^"]+)"', text))
    assert schluessel, f"/{pfad} hat keine uebersetzbaren Texte"

    # Das Textobjekt als Ganzes lesen und als JSON auswerten. Frueher
    # stand hier ein Muster auf die schliessende Klammer — das brach,
    # sobald sich die Einrueckung des Blocks um zwei Zeichen verschob.
    roh = re.search(r"var texte = (\{.*?\n  \});", text, re.S)
    assert roh, f"/{pfad} hat kein Textobjekt"
    texte = json.loads(roh.group(1))

    for sprache in ("de", "en"):
        fehlend = schluessel - set(texte[sprache])
        assert not fehlend, (
            f"/{pfad}: ohne Fassung in {sprache}: {sorted(fehlend)}"
        )


# --- Sitemap ---------------------------------------------------------


def test_sitemap_fuehrt_jede_oeffentliche_seite(klient):
    antwort = klient.get("/sitemap.xml")

    assert antwort.status_code == 200
    baum = ET.fromstring(antwort.content)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    adressen = {ort.text for ort in baum.iter(f"{ns}loc")}

    erwartet = {"/", "/impressum", "/datenschutz", "/agb", "/funktionen"}
    erwartet |= {f"/{name}" for name in FACHSEITEN}

    gefunden = {urllib.parse.urlsplit(a).path for a in adressen}
    assert erwartet <= gefunden, f"fehlt in der Sitemap: {sorted(erwartet - gefunden)}"


def test_sitemap_erfindet_kein_datum(klient):
    """`lastmod` darf nicht der heutige Tag sein.

    Vorher stand dort `dt.date.today()`. Damit behauptete die Sitemap
    jeden Tag aufs Neue, saemtliche Seiten seien gerade ueberarbeitet
    worden. Google erkennt ein `lastmod`, das sich taeglich ohne
    Textaenderung bewegt, und ignoriert die Angabe danach ganz — das
    Signal ist dann auch fuer die Seiten verloren, bei denen es zaehlt.

    Der Test faellt also genau dann, wenn jemand das Datum wieder
    ausrechnen laesst statt es zu pflegen. Bleibt ein von Hand
    gesetztes Datum zufaellig heute stehen, faellt er einen Tag lang
    zu Unrecht — das ist der Preis dafuer, den Rueckfall ueberhaupt
    bemerken zu koennen.
    """
    heute = dt.date.today().isoformat()
    staende = {stand for _, stand, _, _ in SITEMAP}

    assert staende != {heute}, "lastmod wird offenbar wieder berechnet statt gepflegt"


@pytest.mark.parametrize("eintrag", SITEMAP, ids=lambda e: e[0] or "wurzel")
def test_sitemap_datum_ist_gueltig_und_nicht_aus_der_zukunft(eintrag):
    pfad, stand, _, _ = eintrag

    datum = dt.date.fromisoformat(stand)  # wirft bei Unsinn

    assert datum <= dt.date.today(), f"{pfad or '/'}: lastmod liegt in der Zukunft"


# --- robots.txt ------------------------------------------------------


def test_robots_laesst_stilblatt_und_skript_lesen(klient):
    """Gesperrtes CSS macht die Seite fuer den Renderer unbrauchbar.

    Google rendert eine Seite, bevor es sie bewertet. Ist das Stilblatt
    gesperrt, sieht der Renderer unformatierten Text und haelt die Seite
    fuer nicht mobiltauglich. `Disallow: /seiten/` sperrte genau das mit,
    denn dort liegen `basis.css` und `werkzeuge.js`.

    Geprueft werden die Zeilen selbst, nicht ihre Wirkung: Der
    robots-Leser der Standardbibliothek kennt keine Platzhalter und
    beurteilte `Allow: /seiten/*.css` deshalb falsch. Suchmaschinen
    koennen es.
    """
    text = klient.get("/robots.txt").text

    for regel in ("Allow: /seiten/*.css", "Allow: /seiten/*.js"):
        assert regel in text, f"{regel} fehlt"

    # Die Erlaubnis muss vor der Sperre stehen: Google nimmt die laengste
    # passende Regel, einfachere Leser die erste.
    assert text.index("Allow: /seiten/*.css") < text.index("Disallow: /seiten/")


def test_robots_sperrt_das_rohe_html_weiter(klient):
    """Unter /seiten/ liegt jede Seite ein zweites Mal.

    Waere das frei, stuende sie doppelt im Index — einmal unter ihrer
    Adresse, einmal als /seiten/zugferd.html.
    """
    text = klient.get("/robots.txt").text

    assert "Disallow: /seiten/\n" in text


@pytest.mark.parametrize("name", FACHSEITEN)
def test_robots_sperrt_die_fachseiten_nicht(klient, name):
    import urllib.robotparser

    leser = urllib.robotparser.RobotFileParser()
    leser.parse(klient.get("/robots.txt").text.splitlines())

    assert leser.can_fetch("*", f"/{name}"), f"/{name} ist gesperrt"
    assert leser.can_fetch("*", "/funktionen")


# --- Die Dateien selbst ----------------------------------------------


@pytest.mark.parametrize("pfad", ["funktionen", *FACHSEITEN])
def test_fachseite_laedt_das_gemeinsame_stilblatt(pfad):
    """`funktionen.css` muss **nach** `basis.css` stehen.

    Die Fachseiten erben die Handschrift der Startseite. Steht das
    Stilblatt davor, gewinnt die nuechterne Arbeitsflaeche und die
    Seite sieht aus wie ein Formular.
    """
    text = (SEITEN / f"{pfad}.html").read_text(encoding="utf-8")

    assert text.index("basis.css") < text.index("funktionen.css")


@pytest.mark.parametrize("pfad", ["funktionen", *FACHSEITEN])
def test_fachseite_traegt_den_zaehler_platzhalter(pfad):
    """Ohne den Platzhalter wird die Seite nicht gezaehlt.

    `seite()` ersetzt ihn durch das Plausible-Skript. Fehlt er, faellt
    das nirgends auf — die Seite erscheint nur nie in der Statistik.
    """
    text = (SEITEN / f"{pfad}.html").read_text(encoding="utf-8")

    assert "<!--PLAUSIBLE-->" in text
