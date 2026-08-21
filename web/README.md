# Web-Schicht

FastAPI-App (`src/rechnungsblatt_web/`) über der schmalen Kern-Schnittstelle
(`rechnungsblatt_kern.api`). Stand:

- **Einrichtung** (`/`): Briefpapier-Upload → Normalisierung → Ampel
  (inkl. Schriftersetzungs-Warnung), Schreibzone (eingebetteter
  [`zonen-editor/`](zonen-editor/)), Stammdaten.
- **Neue Rechnung** (`/rechnung`): Formular mit Pflichtfeld-Erzwingung
  (Befund-Codes vom Kern, feldgenau angezeigt), Positionen, Rabatt,
  Gutschrift/Korrektur mit Bezug, Nummernkreis, Merkliste + Duplikat als
  Vorlage aus der Ablage, ZUGFeRD-PDF- und XRechnung-Download.
- Einzelmandant ohne Login (Konto kommt später) — Betrieb nur hinter
  Zugriffsschutz, siehe [`../deploy/README.md`](../deploy/README.md).

```bash
pip install -e ./kern -e "./web[test]"
python -m pytest web/tests
DATEN_VERZEICHNIS=/tmp/rb-daten uvicorn rechnungsblatt_web.main:app --reload
```

## Feststehende Anforderungen

- **Eigenständiges, modernes Design.** Kein generisches
  Framework-/Template-Aussehen (kein Standard-Bootstrap, kein unangepasstes
  shadcn/Material): eigene Designsprache mit durchdachter Typografie,
  Farbwelt und Mikrointeraktionen. Das Produkt verkauft „Ihr Briefpapier,
  Ihr Auftritt" — die Oberfläche muss diesen Anspruch selbst einlösen.
- **Mehrsprachige UI: mindestens Deutsch und Englisch.** Von Anfang an mit
  i18n-Framework bauen, keine hartkodierten Texte in Komponenten.
  - Die §14-Prüfung des Kerns liefert Befunde mit **stabilen Codes**
    (`S1`…`S6`, `E1`/`E2`, `R1`…`R4`, `P0`…`P4`, `K1`/`K2`, `RC1`/`RC2`,
    `IG1`, `G1`, `X1`/`X2`). Die UI übersetzt über den Code; die deutschen
    Texte im Kern sind nur Fallback bzw. für Logs.
  - Das **Rechnungsdokument selbst** (Blatt + XML) bleibt davon unberührt —
    Pflichthinweise nach UStG sind Teil des Belegs, nicht der UI.
- **Schreibzone: genau zwei Regler** (Kopf-Ende, Fuß-Beginn). Kein
  Rechteck-Editor. Abnahmekriterium: ein Nicht-Techniker schafft es ohne
  Erklärung.
- Briefpapier-Upload mit Normalisierung + Ampel (einmalig beim Einrichten);
  nur die normalisierte Fassung wird gespeichert, das Original verworfen.
- Schriftersetzungs-Warnung sichtbar in der Vorschau: „Wir mussten
  Schriften ersetzen, bitte prüfen."
- Sauberer Ablehnungsweg für nicht unterstützte Bögen (Sonderfarben,
  verschlüsselte PDFs, mehrseitige Bögen) statt einer kaputten Rechnung.
- Pflichtfeld-Erzwingung im Formular, blockierend — Befunde des Kerns 1:1
  am Feld anzeigen (`Befund.feld` adressiert das Formularfeld).

## MVP-Umfang

Siehe `docs/uebergabe.md` §8 — Konto, Stammdaten, Briefpapier-Upload,
Schreibzone, Rechnungsformular, Kundenmerkliste, Nummernkreis, Vorschau,
ZUGFeRD- und XRechnung-Download, Ablage, Duplikat als Vorlage,
Gutschrift/Korrektur, Bezahlung je Rechnung. Kein Mailversand, kein Peppol,
kein GoBD-Archiv-Versprechen, kein Mahnwesen, keine Buchhaltung.
