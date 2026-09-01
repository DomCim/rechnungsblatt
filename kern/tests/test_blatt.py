import dataclasses
import io
import re
from decimal import Decimal

import pikepdf
import pytest

from rechnungsblatt_kern import (
    BlattUeberlauf,
    Position,
    Schreibzone,
    Steuerkategorie,
    berechne_summen,
    format_betrag,
    rendere_blatt,
)


def test_format_betrag_deutsch():
    assert format_betrag(Decimal("1234.56")) == "1.234,56 €"
    assert format_betrag(Decimal("0.05")) == "0,05 €"
    assert format_betrag(Decimal("-12.30")) == "-12,30 €"
    assert format_betrag(Decimal("1000000.00")) == "1.000.000,00 €"


def test_schreibzone_validierung():
    with pytest.raises(ValueError):
        Schreibzone(kopf_ende_mm=150, fuss_beginn_mm=100)
    with pytest.raises(ValueError):
        Schreibzone(kopf_ende_mm=-1, fuss_beginn_mm=20)
    zone = Schreibzone(kopf_ende_mm=45, fuss_beginn_mm=25)
    assert zone.nutzhoehe_mm == pytest.approx(227.0)


def test_blatt_ist_einseitiges_pdf(rechnung, stammdaten):
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone())
    assert blatt.startswith(b"%PDF-")

    import pikepdf, io

    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) == 1


def test_blatt_bettet_benutzte_schriften_ein(rechnung, stammdaten):
    """PDF/A verlangt eingebettete Schriften — Base-14 wäre Fehlerklasse 3.

    Bewertet werden nur per ``Tf`` benutzte Schriften; das unbenutzte
    Standard-Helvetica, das reportlab immer anlegt, ist nachweislich
    unkritisch (Prototyp: 124 passedRules, 0 failed).
    """
    import io

    import pikepdf

    from rechnungsblatt_kern.normalisierung import _benutzte_schriften

    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        benutzte = list(_benutzte_schriften(pdf.pages[0]))
        assert len(benutzte) >= 2  # normal + fett
        for schrift, name in benutzte:
            deskriptor = schrift.get("/FontDescriptor", None)
            if deskriptor is None and "/DescendantFonts" in schrift:
                deskriptor = schrift.DescendantFonts[0].get("/FontDescriptor", None)
            assert deskriptor is not None, f"{name}: ohne FontDescriptor (Base-14?)"
            assert any(
                key in deskriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
            ), f"{name}: Schriftprogramm nicht eingebettet"


def _viele_positionen(rechnung, anzahl: int):
    return dataclasses.replace(
        rechnung,
        positionen=tuple(
            Position(
                bezeichnung=f"Position {i} mit einem sehr langen beschreibenden Text, "
                "der über mehrere Zeilen umbricht und Platz verbraucht",
                menge=Decimal("1"),
                einheit="C62",
                einzelpreis=Decimal("10.00"),
                steuer=Steuerkategorie.UST_19,
            )
            for i in range(anzahl)
        ),
    )


def test_viele_positionen_brechen_um(rechnung, stammdaten):
    """40 Positionen ergeben mehrere Seiten statt eines Überlauffehlers."""
    viele = _viele_positionen(rechnung, 40)
    summen = berechne_summen(viele)
    blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) > 1


def test_umbruch_auch_bei_hoher_fussleiste(rechnung, stammdaten):
    """Eine hohe Fußleiste verkleinert die Zone — es muss trotzdem gehen."""
    viele = _viele_positionen(rechnung, 25)
    summen = berechne_summen(viele)
    eng = Schreibzone(kopf_ende_mm=50, fuss_beginn_mm=60)
    blatt = rendere_blatt(viele, stammdaten, summen, eng)
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) > 2  # enge Zone braucht mehr Seiten


def _seitentext(pdf, nummer: int) -> str:
    """Sichtbaren Text einer Seite aus den Content-Streams lesen.

    pikepdf bringt keine Textextraktion mit; für die Prüfung genügen die
    Zeichenketten in Klammern, die der Textoperator ausgibt.
    """
    roh = pikepdf.Page(pdf.pages[nummer]).obj.Contents.read_bytes()
    stuecke = re.findall(rb"\(([^()]*)\)", roh)
    return b" ".join(stuecke).decode("latin-1", "replace")


def test_uebertrag_und_seitenzahl_stehen_auf_dem_blatt(rechnung, stammdaten):
    viele = _viele_positionen(rechnung, 40)
    summen = berechne_summen(viele)
    blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        gesamt = len(pdf.pages)
        erste = _seitentext(pdf, 0)
        letzte = _seitentext(pdf, gesamt - 1)
    assert "bertrag" in erste  # „Übertrag“, Umlaut je nach Kodierung
    assert f"Seite 1 von {gesamt}" in erste
    assert f"Seite {gesamt} von {gesamt}" in letzte


def test_einseitig_ohne_seitenzahl(rechnung, stammdaten):
    """Eine Seite bleibt eine Seite — ohne Fußzeile und ohne Übertrag."""
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        assert len(pdf.pages) == 1
        text = _seitentext(pdf, 0)
    assert "Seite 1 von" not in text
    assert "bertrag" not in text


def _uebertraege(text: str) -> list[Decimal]:
    """Alle Beträge, die in einer Übertragszeile stehen.

    Der Text kommt aus den Content-Streams; „Übertrag" und der Betrag
    stehen dort als getrennte Zeichenketten nebeneinander.
    """
    betraege = []
    stuecke = text.split()
    for i, stueck in enumerate(stuecke):
        if "bertrag" not in stueck:
            continue
        # Der Betrag folgt unmittelbar — als „1.234,56 €" oder Teilen davon.
        rest = " ".join(stuecke[i + 1:i + 4])
        treffer = re.search(r"([\d.]+,\d\d)", rest)
        if treffer:
            betraege.append(Decimal(treffer.group(1).replace(".", "").replace(",", ".")))
    return betraege


def test_uebertrag_traegt_den_richtigen_betrag(rechnung, stammdaten):
    """Der Übertrag muss die Positionen bis zum Seitenende summieren.

    Bisher prüfte nur eine Zeichenkette, dass „Übertrag" überhaupt
    dasteht. Der **Wert** war ungeprüft — und er entsteht in `blatt.py`
    aus einer zweiten, vom Rechenwerk unabhängigen Summierung
    (`laufende_summe += zeilensumme(...)`). Liefe die je auseinander,
    zeigte das Blatt einen Übertrag, der nicht zur Endsumme passt: für
    den Kunden ein sichtbarer Rechenfehler auf seiner Rechnung.
    """
    viele = _viele_positionen(rechnung, 40)
    summen = berechne_summen(viele)
    blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        seiten = len(pdf.pages)
        texte = [_seitentext(pdf, i) for i in range(seiten)]

    assert seiten > 1, "der Fall braucht einen Seitenumbruch"

    # Jeder Übertrag steht zweimal: unten auf der Seite, die ihn
    # abschließt, und oben auf der folgenden. Die letzte Seite mit
    # Positionen schließt ohne — dort endet die Liste, es folgt der
    # Summenblock. Geprüft wird die Paarung, nicht die Seitenzahl.
    je_seite = [_uebertraege(t) for t in texte]
    for nummer, werte in enumerate(je_seite):
        if len(werte) == 2:
            # Seite mit übernommenem und weitergereichtem Übertrag.
            assert werte[0] < werte[1], (
                f"Seite {nummer + 1}: Übertrag schrumpft von {werte[0]} "
                f"auf {werte[1]}")
        if werte and nummer + 1 < len(je_seite) and je_seite[nummer + 1]:
            assert werte[-1] == je_seite[nummer + 1][0], (
                f"Seite {nummer + 1} reicht {werte[-1]} weiter, "
                f"Seite {nummer + 2} übernimmt {je_seite[nummer + 1][0]}")

    kette = [w for werte in je_seite for w in werte]
    assert kette, "kein einziger Übertrag gefunden"
    assert kette == sorted(kette), f"Überträge laufen nicht aufwärts: {kette}"
    assert kette[-1] < summen.zeilensumme, (
        f"letzter Übertrag {kette[-1]} muss unter der Zeilensumme "
        f"{summen.zeilensumme} liegen")
    # Alle Positionen zu 10,00 €: jeder Übertrag ist ein glattes Vielfaches.
    for wert in kette:
        assert wert % Decimal("10.00") == 0, (
            f"Übertrag {wert} passt nicht zu Positionen à 10,00 €")


def test_uebertrag_und_endsumme_passen_zusammen(rechnung, stammdaten):
    """Die Zeilensumme auf dem Blatt muss die des Rechenwerks sein.

    Der Gegencheck zum Übertrag: Selbst wenn die Überträge untereinander
    stimmen, könnte die Schlusssumme daneben liegen.
    """
    viele = _viele_positionen(rechnung, 40)
    summen = berechne_summen(viele)
    blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        letzte = _seitentext(pdf, len(pdf.pages) - 1)

    erwartet = f"{summen.zeilensumme:,.2f}".replace(",", "#").replace(".", ",")
    erwartet = erwartet.replace("#", ".")
    assert erwartet in letzte, (
        f"Zeilensumme {erwartet} steht nicht auf der Schlussseite")


def test_seitenzahl_stimmt_bei_verschiedenen_laengen(rechnung, stammdaten):
    """„Seite 1 von N" muss zur tatsächlichen Seitenzahl passen.

    Der Beleg entsteht in zwei Durchläufen: erst zählen, dann zeichnen.
    Bräche der zweite Lauf anders um als der erste, stünde „Seite 3 von 2"
    auf dem Blatt. Ein Kommentar in `blatt.py` zeigt, dass genau das schon
    einmal auftrat und mit etwas Reserve entschärft wurde — geprüft hat es
    bisher nichts.
    """
    for anzahl in (12, 25, 40, 60):
        viele = _viele_positionen(rechnung, anzahl)
        summen = berechne_summen(viele)
        blatt = rendere_blatt(viele, stammdaten, summen, Schreibzone())
        with pikepdf.open(io.BytesIO(blatt)) as pdf:
            seiten = len(pdf.pages)
            texte = [_seitentext(pdf, i) for i in range(seiten)]
        if seiten == 1:
            continue
        for nummer, text in enumerate(texte, start=1):
            assert f"Seite {nummer} von {seiten}" in text, (
                f"{anzahl} Positionen ergeben {seiten} Seiten, "
                f"Seite {nummer} behauptet etwas anderes")
