# Schreibzonen-Editor (erster UI-Baustein)

Der Editor aus der Übergabe, §7: **bewusst nur zwei Werte** — wo endet der
Briefkopf, wo beginnt die Fußzeile. Kein Rechteck-Editor. Abnahmekriterium:
ein Nicht-Techniker schafft es ohne Erklärung.

Framework-frei (eine HTML-Datei, kein Build), damit er später unverändert in
die gewählte Web-Schicht (Next.js oder FastAPI+Templates) eingebettet werden
kann. Mehrsprachig DE/EN, hell/dunkel, Tastatur-bedienbar (Pfeiltasten,
Shift = 10 mm).

## Ausprobieren

```bash
pip install -e ./kern
python scripts/zonen_editor_demo.py        # erzeugt briefpapier.png (Demo)
python -m http.server -d web/zonen-editor 8000
# → http://localhost:8000
```

Ohne `briefpapier.png` zeigt der Editor einen gezeichneten Platzhalter-Bogen.
Im Produkt liefert der Server hier die PNG-Vorschau des **normalisierten**
Kunden-Uploads (`rechnungsblatt_kern.erzeuge_vorschau_png`).

## Schnittstelle zur Web-Schicht

- Der Knopf „Schreibzone übernehmen" feuert ein `CustomEvent("schreibzone")`
  mit `detail = {kopf_ende_mm, fuss_beginn_mm}` — dieselben zwei Werte wie
  `rechnungsblatt_kern.Schreibzone`.
- Die Mindesthöhe (100 mm) spiegelt `Schreibzone.MINDESTHOEHE_MM`; der Kern
  bleibt die verbindliche Prüfung.
