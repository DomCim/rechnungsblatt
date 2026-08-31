"""Was aus JSON wird: Stammdaten, Anschrift, Gestaltung, Nummernmuster.

Die Oberfläche schickt lose Wörterbücher, der Kern will seine Datentypen.
Diese Umwandlung brauchen zwei Bereiche — die Einrichtung beim Speichern
und der Beleg beim Erzeugen. Läge sie bei einem von beiden, importierte
der andere quer.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from rechnungsblatt_kern import (
    Anschrift,
    Blattgestaltung,
    Layoutvariante,
    Schriftgrad,
    Stammdaten,
    verfuegbare_schriften,
)

from .ablage import lese_json


_FARBE_MUSTER = re.compile(r"#[0-9a-fA-F]{6}")


def _gestaltung_aus_json(daten: dict) -> Blattgestaltung:
    schrift = daten.get("schrift", "liberation-sans")
    if schrift not in {s.schluessel for s in verfuegbare_schriften()}:
        raise HTTPException(422, detail={"grund": f"Unbekannte Schrift: {schrift!r}."})
    try:
        schriftgrad = Schriftgrad[str(daten.get("schriftgrad", "normal")).upper()]
        layout = Layoutvariante(str(daten.get("layout", "klassisch")).lower())
    except (KeyError, ValueError) as fehler:
        raise HTTPException(
            422, detail={"grund": f"Ungültige Gestaltung: {fehler}"}
        ) from fehler
    farbe = str(daten.get("akzentfarbe") or "#136f83").strip()
    if not _FARBE_MUSTER.fullmatch(farbe):
        raise HTTPException(
            422, detail={"grund": f"Ungültige Akzentfarbe: {farbe!r} (erwartet #rrggbb)."}
        )
    return Blattgestaltung(
        schrift=schrift,
        schriftgrad=schriftgrad,
        layout=layout,
        belegdaten_als_zeile=bool(daten.get("belegdaten_als_zeile", False)),
        akzent_an=bool(daten.get("akzent_an", False)),
        akzentfarbe=farbe,
    )


def _gestaltung_laden(wurzel: Path) -> Blattgestaltung:
    daten = lese_json(wurzel / "gestaltung.json")
    if daten is None:
        return Blattgestaltung()
    return _gestaltung_aus_json(daten)


def _stammdaten_aus_json(daten: dict) -> Stammdaten:
    return Stammdaten(
        firmierung=daten.get("firmierung", ""),
        anschrift=_anschrift_aus_json(daten.get("anschrift", {})),
        steuernummer=daten.get("steuernummer") or None,
        ust_idnr=daten.get("ust_idnr") or None,
        iban=daten.get("iban", ""),
        bic=daten.get("bic") or None,
        zahlungsziel_tage=int(daten.get("zahlungsziel_tage") or 14),
        kontakt_name=daten.get("kontakt_name") or None,
        kontakt_email=daten.get("kontakt_email") or None,
        kontakt_telefon=daten.get("kontakt_telefon") or None,
        kleinunternehmer=bool(daten.get("kleinunternehmer", False)),
        artikelnummern=bool(daten.get("artikelnummern", False)),
    )


def _anschrift_aus_json(daten: dict) -> Anschrift:
    return Anschrift(
        strasse=daten.get("strasse", ""),
        plz=daten.get("plz", ""),
        ort=daten.get("ort", ""),
        land=daten.get("land") or "DE",
    )


def _muster_zerlegen(muster: str) -> tuple[re.Pattern, int, bool]:
    """Zerlegt ein Nummern-Muster ({JJJJ}, {JJ}, genau ein {N…}-Zähler).

    Liefert (Erkennungs-Regex, Zählerbreite, enthält Jahresanteil).
    """
    zaehler = re.findall(r"\{(N+)\}", muster)
    if len(zaehler) != 1:
        raise ValueError(
            "Das Nummern-Muster braucht genau einen Zähler-Platzhalter "
            "({N}, {NN}, {NNN} …), z. B. RE-{JJJJ}-{NNNN}."
        )
    breite = len(zaehler[0])
    ausdruck = ""
    for teil in re.split(r"(\{JJJJ\}|\{JJ\}|\{N+\})", muster):
        if teil == "{JJJJ}":
            ausdruck += r"(?P<jahr>\d{4})"
        elif teil == "{JJ}":
            ausdruck += r"(?P<jahr2>\d{2})"
        elif teil and re.fullmatch(r"\{N+\}", teil):
            ausdruck += r"(?P<lfd>\d{" + str(breite) + r",})"
        elif teil:
            ausdruck += re.escape(teil)
    hat_jahr = "{JJJJ}" in muster or "{JJ}" in muster
    return re.compile(f"^{ausdruck}$"), breite, hat_jahr


def _girocode_aktiv(wurzel: Path) -> bool:
    daten = lese_json(wurzel / "stammdaten.json") or {}
    return bool(daten.get("girocode", True))
