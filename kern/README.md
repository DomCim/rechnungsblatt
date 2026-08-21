# rechnungsblatt-kern

Der Rechnungskern von Rechnungsblatt — stack-unabhängig, voll testbar.
Die Web-Schicht spricht ihn ausschließlich über `rechnungsblatt_kern.api` an.

## Module

| Modul | Aufgabe |
|---|---|
| `modell` | Datenmodell (`Decimal`, keine Floats): Stammdaten, Empfänger, Positionen, Rechnung, Schreibzone (genau zwei Werte) |
| `pruefung` | §14-UStG-Prüfung, **blockierend**, Befunde mit stabilen Codes für die UI |
| `summen` | Rechenwerk: `ROUND_HALF_UP`, zwei Nachkommastellen, Steuerkörbe, rundungsfeste Rabattverteilung |
| `cii` | CII-XML nach EN 16931; XRechnung-3.0-Profil für Behördenkunden |
| `normalisierung` | Ghostscript-Normalisierung des Briefpapiers (Farbraum → sRGB, Schriften einbetten) + Ablehnungsweg |
| `blatt` | reportlab-Overlay in die Schreibzone, nur eingebettete TTF-Schriften |
| `xmp` | XMP mit PDF/A-3B-Kennung und Factur-X-Extension-Schema |
| `zusammenbau` | pikepdf: Briefpapier + Blatt + XML + XMP → PDF/A-3B |
| `api` | `erzeuge_rechnung()` (ZUGFeRD-PDF) und `erzeuge_xrechnung()` (XML) |
| `testbogen` | Testbögen mit CMYK/RGB/Alpha-Problemfällen — nur für Tests und CI |

## Benutzung

```python
from rechnungsblatt_kern import erzeuge_rechnung, normalisiere_briefpapier, Schreibzone

# einmalig beim Einrichten:
ergebnis = normalisiere_briefpapier("upload.pdf", "briefpapier_norm.pdf")
if ergebnis.schriften_ersetzt:
    ...  # Vorschau-Warnung anzeigen

# je Rechnung:
rechnung = erzeuge_rechnung(
    rechnung=..., stammdaten=..., briefpapier_norm="briefpapier_norm.pdf",
    zone=Schreibzone(kopf_ende_mm=52, fuss_beginn_mm=25),
    zeitpunkt=jetzt_mit_zeitzone,
)
rechnung.pdf  # PDF/A-3B mit factur-x.xml
rechnung.xml  # dasselbe CII-XML einzeln
```

Kernregel: PDF und XML entstehen aus denselben Daten im selben Vorgang.
Ein bestehendes PDF wird nie nachträglich angereichert.

## Tests

```bash
pip install -e "./kern[test]"
python -m pytest kern/tests
```

Die Integrationstests brauchen Ghostscript und Liberation-/DejaVu-Schriften
(werden ohne Ghostscript übersprungen). Die inhaltliche PDF/A- und
EN-16931-Validierung läuft in der CI gegen den Mustang-Validator
(`scripts/` + `validator/`).
