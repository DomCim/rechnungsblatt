#!/usr/bin/env python3
"""Prüft die Referenzfälle mit dem Mustang-Validator (PDF/A-3 + EN 16931).

Erwartet die kompilierte Val-Klasse neben der validator.jar (siehe
validator/README.md). Bricht mit Exit 1 ab, sobald ein Fall nicht
``status="valid"`` bzw. (beim PDF-Teil) ``isCompliant`` liefert.

Aufruf:
  python scripts/pruefe_referenzfaelle.py <verzeichnis> [--jar validator.jar] [--klasse .]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def validiere(datei: Path, jar: str, klassenpfad: str) -> tuple[bool, str]:
    lauf = subprocess.run(
        ["java", "-cp", f"{klassenpfad}:{jar}", "Val", str(datei)],
        capture_output=True,
        text=True,
    )
    ausgabe = lauf.stdout
    if lauf.returncode != 0 and not ausgabe.strip():
        return False, f"Validator-Aufruf fehlgeschlagen: {lauf.stderr.strip()}"
    beginn = ausgabe.find("<")
    if beginn < 0:
        return False, f"Keine XML-Ausgabe: {ausgabe[:400]}"
    try:
        wurzel = ET.fromstring(ausgabe[beginn:])
    except ET.ParseError as fehler:
        return False, f"Validator-XML nicht lesbar: {fehler}\n{ausgabe[:400]}"

    zusammenfassungen = wurzel.findall(".//summary")
    if not zusammenfassungen:
        return False, "Keine <summary> im Validator-Ergebnis."
    probleme = []
    for zusammenfassung in zusammenfassungen:
        status = zusammenfassung.get("status")
        if status != "valid":
            probleme.append(f"summary status={status!r}")
    if datei.suffix == ".pdf":
        # der PDF/A-Teil (veraPDF) muss ausdrücklich isCompliant melden
        berichte = wurzel.findall(".//validationReport")
        if not berichte:
            probleme.append("kein PDF/A-validationReport")
        for bericht in berichte:
            if bericht.get("isCompliant") != "true":
                probleme.append(f"PDF/A nicht konform: {bericht.get('profileName')}")
    for meldung in wurzel.findall(".//error"):
        probleme.append((meldung.text or "").strip()[:200])

    if probleme:
        return False, "; ".join(p for p in probleme if p)
    return True, ", ".join(f"summary={z.get('status')}" for z in zusammenfassungen)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("verzeichnis", type=Path)
    parser.add_argument("--jar", default="validator.jar")
    parser.add_argument("--klasse", default=".", help="Klassenpfad mit Val.class")
    argumente = parser.parse_args()

    kandidaten = sorted(
        datei
        for datei in argumente.verzeichnis.iterdir()
        if datei.suffix == ".pdf" and "_upload" not in datei.name and "_norm" not in datei.name
    ) + sorted(argumente.verzeichnis.glob("xrechnung_*.xml"))

    if not kandidaten:
        print("Keine Referenzfälle gefunden.", file=sys.stderr)
        return 1

    fehler = 0
    for datei in kandidaten:
        gut, detail = validiere(datei, argumente.jar, argumente.klasse)
        zeichen = "OK  " if gut else "FAIL"
        print(f"{zeichen} {datei.name}: {detail}")
        if not gut:
            fehler += 1

    if fehler:
        print(f"\n{fehler} von {len(kandidaten)} Referenzfällen ungültig.", file=sys.stderr)
        return 1
    print(f"\nAlle {len(kandidaten)} Referenzfälle gültig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
