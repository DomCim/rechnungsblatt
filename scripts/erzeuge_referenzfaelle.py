#!/usr/bin/env python3
"""Erzeugt die Referenzfälle für die CI-Validierung.

Ablauf je Fall: Testbogen → Normalisierung (Ghostscript) → Rechnung
(PDF/A-3B mit factur-x.xml). Zusätzlich ein XRechnung-XML für den
Behörden-Export. Alles deterministisch (feste Daten), damit die CI
vergleichbar bleibt.

Aufruf: python scripts/erzeuge_referenzfaelle.py <ausgabeverzeichnis>
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

from rechnungsblatt_kern import (
    Anschrift,
    Belegtyp,
    Blattgestaltung,
    Empfaenger,
    Layoutvariante,
    Position,
    Rechnung,
    Schreibzone,
    Schriftgrad,
    Stammdaten,
    Steuerkategorie,
    Zeitraum,
    erzeuge_rechnung,
    erzeuge_xrechnung,
    normalisiere_briefpapier,
)
from rechnungsblatt_kern.testbogen import erzeuge_testbogen

ZEITPUNKT = dt.datetime(2026, 8, 21, 12, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
ZONE = Schreibzone(kopf_ende_mm=52, fuss_beginn_mm=25)

STAMMDATEN = Stammdaten(
    firmierung="Muster & Partner GmbH",
    anschrift=Anschrift(strasse="Bahnhofstr. 12", plz="95119", ort="Naila"),
    steuernummer="223/456/78901",
    ust_idnr="DE123456789",
    iban="DE14 7805 0000 0001 2345 67",
    bic="BYLADEM1HOF",
    zahlungsziel_tage=14,
    kontakt_name="Max Muster",
    kontakt_email="info@muster-partner.de",
    kontakt_telefon="09282 12345",
)

KLEINUNTERNEHMERIN = Stammdaten(
    firmierung="Anna Beispiel Webdesign",
    anschrift=Anschrift(strasse="Marktplatz 3", plz="95119", ort="Naila"),
    steuernummer="223/123/45678",
    iban="DE14 7805 0000 0001 2345 67",
    zahlungsziel_tage=14,
    kleinunternehmer=True,
)

EMPFAENGER = Empfaenger(
    name="Beispielkunde GmbH",
    anschrift=Anschrift(strasse="Industriestr. 5", plz="95028", ort="Hof"),
)

BEHOERDE = Empfaenger(
    name="Stadt Hof",
    anschrift=Anschrift(strasse="Klosterstr. 1", plz="95028", ort="Hof"),
    leitweg_id="09464000-12345-06",
    email="rechnungseingang@stadt-hof.example.de",
)


def _standard_rechnung() -> Rechnung:
    """Gemischte Steuersätze plus Rabatt — der rechnerisch anspruchsvollste Fall."""
    return Rechnung(
        nummer="RE-2026-0042",
        rechnungsdatum=dt.date(2026, 8, 21),
        empfaenger=EMPFAENGER,
        leistungszeitraum=Zeitraum(von=dt.date(2026, 8, 1), bis=dt.date(2026, 8, 31)),
        faelligkeit=dt.date(2026, 9, 4),
        rabatt_prozent=Decimal("10"),
        rabatt_grund="Treuerabatt",
        freitext="Vielen Dank für Ihren Auftrag.",
        verwendungszweck="RE-2026-0042 Beispielkunde GmbH",
        positionen=(
            Position(
                bezeichnung="Montagearbeiten",
                artikelnummer="ART-4711",
                beschreibung="Demontage Altanlage, Aufbau und Inbetriebnahme",
                menge=Decimal("8"),
                einheit="HUR",
                einzelpreis=Decimal("25.00"),
                steuer=Steuerkategorie.UST_19,
            ),
            Position(
                # Ohne Artikelnummer — der gemischte Fall gehört mit geprüft.
                bezeichnung="Fachbuch „E-Rechnung kompakt“",
                menge=Decimal("2"),
                einheit="C62",
                einzelpreis=Decimal("34.58"),
                steuer=Steuerkategorie.UST_7,
            ),
        ),
    )


def _kleinunternehmer_rechnung() -> Rechnung:
    return Rechnung(
        nummer="2026-017",
        rechnungsdatum=dt.date(2026, 8, 21),
        empfaenger=EMPFAENGER,
        leistungsdatum=dt.date(2026, 8, 15),
        positionen=(
            Position(
                bezeichnung="Gestaltung Website",
                menge=Decimal("1"),
                einheit="C62",
                einzelpreis=Decimal("850.00"),
                steuer=Steuerkategorie.KLEINUNTERNEHMER,
            ),
        ),
    )


def _gutschrift() -> Rechnung:
    return Rechnung(
        nummer="GS-2026-0003",
        typ=Belegtyp.GUTSCHRIFT,
        rechnungsdatum=dt.date(2026, 8, 21),
        empfaenger=EMPFAENGER,
        leistungsdatum=dt.date(2026, 8, 20),
        bezugs_nummer="RE-2026-0041",
        bezugs_datum=dt.date(2026, 8, 1),
        positionen=(
            Position(
                bezeichnung="Gutschrift: zu viel berechnete Stunden",
                menge=Decimal("2"),
                einheit="HUR",
                einzelpreis=Decimal("25.00"),
                steuer=Steuerkategorie.UST_19,
            ),
        ),
    )


def _xrechnung() -> Rechnung:
    return Rechnung(
        nummer="RE-2026-0043",
        rechnungsdatum=dt.date(2026, 8, 21),
        empfaenger=BEHOERDE,
        leistungsdatum=dt.date(2026, 8, 18),
        faelligkeit=dt.date(2026, 9, 18),
        positionen=(
            Position(
                bezeichnung="Wartung Außenanlagen",
                menge=Decimal("12"),
                einheit="HUR",
                einzelpreis=Decimal("48.00"),
                steuer=Steuerkategorie.UST_19,
            ),
        ),
    )


def _mehrseitige_rechnung() -> Rechnung:
    """25 Positionen — muss über mehrere Seiten laufen und trotzdem PDF/A-3B
    bleiben. Prüft Übertrag, wiederholten Tabellenkopf und das je Seite
    unterlegte Briefpapier."""
    return Rechnung(
        nummer="RE-2026-0099",
        rechnungsdatum=dt.date(2026, 8, 21),
        empfaenger=EMPFAENGER,
        leistungsdatum=dt.date(2026, 8, 20),
        faelligkeit=dt.date(2026, 9, 4),
        verwendungszweck="RE-2026-0099",
        freitext="Vielen Dank für Ihren Auftrag.",
        positionen=tuple(
            Position(
                bezeichnung=f"Leistungsposition Nummer {i}",
                artikelnummer=f"ART-{4000 + i}",
                beschreibung=(
                    "Ausführliche Beschreibung der erbrachten Leistung"
                    if i % 3 == 0
                    else None
                ),
                menge=Decimal("2"),
                einheit="HUR",
                einzelpreis=Decimal("45.00"),
                steuer=Steuerkategorie.UST_19,
            )
            for i in range(1, 26)
        ),
    )


def main() -> None:
    ausgabe = Path(sys.argv[1] if len(sys.argv) > 1 else "referenzfaelle")
    ausgabe.mkdir(parents=True, exist_ok=True)

    # Briefbögen: 'gut' (Schriften eingebettet) und 'boese' (Base-14) —
    # beide müssen nach der Normalisierung tragen.
    boegen: dict[str, Path] = {}
    for modus in ("gut", "boese"):
        upload = ausgabe / f"briefbogen_{modus}_upload.pdf"
        upload.write_bytes(erzeuge_testbogen(modus))
        norm = ausgabe / f"briefbogen_{modus}_norm.pdf"
        ergebnis = normalisiere_briefpapier(upload, norm)
        print(
            f"normalisiert: {norm.name} "
            f"(Schriften ersetzt: {'ja' if ergebnis.schriften_ersetzt else 'nein'})"
        )
        boegen[modus] = norm

    modern = Blattgestaltung(
        schrift="carlito",
        schriftgrad=Schriftgrad.GROSS,
        layout=Layoutvariante.MODERN,
    )
    faelle = [
        ("rechnung_standard", _standard_rechnung(), STAMMDATEN, boegen["gut"], None),
        ("rechnung_kleinunternehmer", _kleinunternehmer_rechnung(), KLEINUNTERNEHMERIN, boegen["boese"], None),
        ("gutschrift", _gutschrift(), STAMMDATEN, boegen["gut"], None),
        # Gestaltungs-Referenz: andere Schrift, anderes Layout — muss genauso
        # PDF/A-3B-konform sein wie der Standard
        ("rechnung_gestaltet", _standard_rechnung(), STAMMDATEN, boegen["gut"], modern),
        # Mehrseitig: Seitenumbruch mit Übertrag darf die PDF/A-Konformität
        # nicht brechen und muss das Briefpapier auf jeder Seite tragen.
        ("rechnung_mehrseitig", _mehrseitige_rechnung(), STAMMDATEN, boegen["gut"], None),
    ]
    for name, rechnung, stammdaten, bogen, gestaltung in faelle:
        ergebnis = erzeuge_rechnung(
            rechnung, stammdaten, bogen, ZONE, zeitpunkt=ZEITPUNKT, gestaltung=gestaltung
        )
        (ausgabe / f"{name}.pdf").write_bytes(ergebnis.pdf)
        (ausgabe / f"{name}.xml").write_bytes(ergebnis.xml)
        print(f"erzeugt: {name}.pdf ({ergebnis.summen.brutto} EUR brutto)")

    xrechnung = erzeuge_xrechnung(_xrechnung(), STAMMDATEN)
    (ausgabe / "xrechnung_behoerde.xml").write_bytes(xrechnung)
    print("erzeugt: xrechnung_behoerde.xml")


if __name__ == "__main__":
    main()
