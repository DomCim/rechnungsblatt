# Web-Schicht

**Erster Baustein vorhanden:** der Schreibzonen-Editor unter
[`zonen-editor/`](zonen-editor/) — zwei Regler, DE/EN, framework-frei,
zum Einbetten in den späteren Stack. Der Rest der Web-Schicht ist noch
nicht begonnen.

Die Web-Schicht kommt **nach** dem Kern (Übergabe, §11 Schritt 6). Stack ist
frei wählbar (Next.js oder FastAPI); sie spricht den Kern über die schmale
Schnittstelle in `rechnungsblatt_kern.api` an.

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
