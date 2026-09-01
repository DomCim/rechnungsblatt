"""Was die Betriebsprüfung zu sehen bekommt: Siegel, Protokoll, Ausgabe.

Diese Tests brauchen **keine Datenbank** — sie prüfen die Ablage auf der
Platte. Damit laufen sie auch dort, wo die Kontentests sich überspringen.

Der Kern der Sache steckt in ``test_neu_gerechnetes_siegel_faellt_auf``:
Ein Angreifer, der einen Beleg ändert, kann dessen Siegel neu bilden. Erst
die Verkettung mit dem Vorgänger verrät ihn — an den Nachfolgern. Ohne
diesen Test wäre die Kette bloß eine Prüfsumme.
"""

from __future__ import annotations

import json

import pytest

from rechnungsblatt_web import siegel, verfahrensdokumentation


def _lege_beleg(wurzel, nummer: str, inhalt: bytes = b"PDF") -> None:
    ordner = wurzel / "ablage" / nummer
    ordner.mkdir(parents=True)
    (ordner / "rechnung.pdf").write_bytes(inhalt + nummer.encode())
    (ordner / "factur-x.xml").write_bytes(b"<xml>" + nummer.encode() + b"</xml>")
    (ordner / "daten.json").write_bytes(
        json.dumps({"nummer": nummer}).encode("utf-8"))
    siegel.siegle(wurzel, nummer)


@pytest.fixture
def ablage(tmp_path):
    """Drei gesiegelte Belege — der Normalfall, von dem aus geprüft wird."""
    for nummer in ("R-1", "R-2", "R-3"):
        _lege_beleg(tmp_path, nummer)
    return tmp_path


def test_unberuehrte_kette_ist_heil(ablage):
    bericht = siegel.pruefe(ablage)
    assert bericht["heil"]
    assert bericht["glieder"] == 3
    assert bericht["befunde"] == []


def test_geaenderter_beleg_faellt_auf(ablage):
    (ablage / "ablage" / "R-2" / "rechnung.pdf").write_bytes(b"gefaelscht")

    bericht = siegel.pruefe(ablage)
    assert not bericht["heil"]
    assert {"R-2"} == {b["nummer"] for b in bericht["befunde"]}
    assert bericht["befunde"][0]["art"] == "geaendert"


def test_entfernter_beleg_faellt_auf(ablage):
    ordner = ablage / "ablage" / "R-2"
    for datei in ordner.iterdir():
        datei.unlink()
    ordner.rmdir()

    bericht = siegel.pruefe(ablage)
    assert not bericht["heil"]
    assert any(b["art"] == "fehlt" for b in bericht["befunde"])


def test_neu_gerechnetes_siegel_faellt_auf(ablage):
    """Der eigentliche Zweck der Verkettung.

    Wer einen Beleg ändert, kann dessen Siegel neu bilden — der Abdruck
    stimmte dann wieder. Aber das Glied des **nächsten** Belegs zeigt noch
    auf das alte Siegel, und genau daran bricht der Versuch.
    """
    (ablage / "ablage" / "R-2" / "rechnung.pdf").write_bytes(b"gefaelscht")

    kette = siegel.lies(ablage)
    glied = kette[1]
    glied["abdruck"] = siegel._abdruck(ablage / "ablage" / "R-2")
    glied["siegel"] = siegel._glied(
        glied["nummer"], glied["abdruck"], glied["vorher"], glied["zeitpunkt"])
    (ablage / "ablage" / siegel.DATEI).write_text(
        "\n".join(json.dumps(g, ensure_ascii=False, sort_keys=True)
                  for g in kette) + "\n",
        encoding="utf-8")

    bericht = siegel.pruefe(ablage)
    assert not bericht["heil"], "Die Neuberechnung blieb unbemerkt"
    # Der Nachfolger schlägt an, nicht der manipulierte Beleg selbst.
    assert ("R-3", "kette") in {(b["nummer"], b["art"]) for b in bericht["befunde"]}


def test_verkettung_ist_der_grund_fuer_den_befund(ablage):
    """Gegenprobe: Ohne den Verweis auf den Vorgänger bliebe es unentdeckt.

    Ein Siegel nur über den eigenen Abdruck wäre nach der Neuberechnung
    wieder stimmig. Der Test zeigt, dass der Befund aus ``vorher`` kommt —
    fiele das Feld weg, wäre die Kette wertlos.
    """
    kette = siegel.lies(ablage)
    assert kette[0]["vorher"] == siegel.ANKER
    for vorheriges, glied in zip(kette, kette[1:]):
        assert glied["vorher"] == vorheriges["siegel"]


def test_beleg_ohne_siegel_ist_kein_fehler(ablage):
    """Belege aus der Zeit vor der Kette dürfen nicht als Mangel gelten."""
    (ablage / "ablage" / "ALT-1").mkdir()

    bericht = siegel.pruefe(ablage)
    assert bericht["heil"]
    assert bericht["ohne_siegel"] == ["ALT-1"]


def test_leere_ablage(tmp_path):
    bericht = siegel.pruefe(tmp_path)
    assert bericht["heil"]
    assert bericht["glieder"] == 0


def test_unlesbare_zeile_bricht_nicht_die_pruefung(ablage):
    pfad = ablage / "ablage" / siegel.DATEI
    pfad.write_text(pfad.read_text(encoding="utf-8") + "kein json\n",
                    encoding="utf-8")

    bericht = siegel.pruefe(ablage)
    assert not bericht["heil"]


def test_verfahrensdokumentation_fuellt_die_stammdaten(ablage):
    (ablage / "stamm.json").write_text(json.dumps({
        "firmierung": "Muster Werkzeugbau GmbH",
        "anschrift": {"strasse": "Bahnhofstr. 3", "plz": "95119",
                      "ort": "Naila"},
        "steuernummer": "223/456/7890",
    }, ensure_ascii=False), encoding="utf-8")

    text = verfahrensdokumentation.erzeuge(ablage)

    assert "Muster Werkzeugbau GmbH" in text
    assert "Bahnhofstr. 3, 95119 Naila" in text
    assert "223/456/7890" in text
    # Kein Platzhalter darf ungefüllt im Dokument des Kunden landen.
    assert "{" not in text and "}" not in text


def test_verfahrensdokumentation_ohne_stammdaten(tmp_path):
    """Ein leeres Konto darf kein Fehlschlag sein — nur unvollständig."""
    text = verfahrensdokumentation.erzeuge(tmp_path)

    assert "[ bitte ergänzen ]" in text
    assert "{" not in text and "}" not in text


def test_verfahrensdokumentation_nennt_den_siegelstand(ablage):
    text = verfahrensdokumentation.erzeuge(ablage)
    assert "3 Siegel geprueft, Kette unversehrt." in text


def test_verfahrensdokumentation_verschweigt_abweichungen_nicht(ablage):
    """Ein Dokument, das den Mangel verschweigt, wäre in der Prüfung fatal."""
    (ablage / "ablage" / "R-2" / "rechnung.pdf").write_bytes(b"gefaelscht")

    text = verfahrensdokumentation.erzeuge(ablage)
    assert "Abweichung" in text
    assert "Kette unversehrt" not in text


def test_verfahrensdokumentation_benennt_die_grenzen(ablage):
    """Die Zusicherung darf nicht weiter reichen als der Nachweis."""
    text = verfahrensdokumentation.erzeuge(ablage)

    # Rz. 110 — die Dateiablage genügt für sich genommen nicht.
    assert "Rz. 110" in text
    # Die Kette ist kein Zeitstempel einer anerkannten Stelle.
    assert "kein Zeitstempel einer anerkannten Stelle" in text
    # Verantwortlich bleibt der Steuerpflichtige (Rz. 21).
    assert "Rz. 21" in text
    # Und die Bewertung steht dem Berater zu, nicht diesem Dokument.
    assert "steuerliche Berater" in text


def test_verfahrensdokumentation_nennt_acht_jahre(ablage):
    """Seit 01.01.2025 acht statt zehn Jahre — ein falscher Wert wäre teuer."""
    text = verfahrensdokumentation.erzeuge(ablage)
    assert "acht Jahre" in text
    assert "zehn Jahre" not in text


def test_verfahrensdokumentation_zeilenenden(ablage):
    """CRLF durchgängig — die Datei wird im Windows-Editor geöffnet."""
    text = verfahrensdokumentation.erzeuge(ablage)
    assert text.count("\n") == text.count("\r")
    assert "\n" not in text.replace("\r\n", "")
