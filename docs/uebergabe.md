# Rechnungsblatt — Projektübergabe

*Stand 21.08.2026. Übergabe an Claude Code zum Aufsetzen des Repositories.
Grundlage: Konzept „E-Rechnungen mit eigenem Briefpapier" plus ein
durchgeführter und validierter Prototyp-Test.*

---

## 1. Was gebaut wird

Ein Web-Werkzeug, mit dem Selbstständige und Kleinbetriebe eine
rechtsgültige deutsche E-Rechnung erzeugen — **auf ihrem eigenen
Briefpapier**, bezahlt je Rechnung statt im Abo.

**Kein KI-Auslesen bestehender PDFs.** Die Rechnung entsteht aus
strukturierten Formulardaten; das Briefpapier ist reine Unterlage. Das
ist die bewusste Abgrenzung zum gesamten Konverter-Markt (siehe §9).

**Name:** Rechnungsblatt · Repo `rechnungsblatt` · Domain rechnungsblatt.de
(vor Kauf noch per DENIC-Webabfrage und DPMA-Register gegenprüfen).

---

## 2. Architekturentscheidung — bitte lesen, bevor gebaut wird

Das ursprüngliche Konzept sah Next.js + pdf-lib vor. **Davon rate ich für
den PDF-Kern ab.** Der PDF/A-3-Teil wurde in Python prototypisch bewiesen
(pikepdf + Ghostscript + veraPDF); in Node gibt es für die
Farbraum-Normalisierung und die veraPDF-Prüfung kein gleichwertiges
Ökosystem.

**Empfehlung:**

- **Rechnungskern** als eigenständiges Python-Paket (`rechnungsblatt-kern`)
  — Datenmodell, §14-Prüfung, CII-XML, Briefpapier-Normalisierung,
  Blatt-Rendering, PDF/A-3-Zusammenbau. Stack-unabhängig, voll testbar.
- **Web-Schicht** frei wählbar (Next.js oder FastAPI), spricht den Kern
  über eine schmale Schnittstelle an.
- **Beides in einem Monorepo**, damit der Kern nicht als separates Produkt
  gepflegt werden muss.

Erst den Kern bauen, dann die Web-Schicht. Der Kern ist der Wert; die
Oberfläche ist austauschbar.

---

## 3. Der bewiesene Kern — Ablauf

Reihenfolge ist zwingend. Der Normalisierungsschritt darf nicht entfallen.

```
Briefpapier-Upload (einmalig, beim Einrichten)
   └─> NORMALISIEREN (Ghostscript)   ← ohne diesen Schritt scheitert alles
   └─> Ampelprüfung gegen veraPDF
   └─> normalisierte Fassung speichern, Original verwerfen

Je Rechnung:
   Formulardaten
   ├─> §14-Prüfung (blockierend)
   ├─> Blatt rendern (reportlab, in die Schreibzone)
   ├─> CII-XML erzeugen (EN 16931)
   └─> Zusammenbau: normalisiertes Briefpapier + Blatt + XML + XMP
       └─> PDF/A-3B
```

**Kernregel:** PDF und XML entstehen aus denselben Daten im selben
Vorgang. Ein bestehendes PDF wird nie nachträglich angereichert.

---

## 4. Schritt „Normalisieren" — der entscheidende Fund

### Warum

PDF/A erlaubt **genau eine** Ausgabebedingung. Ein echter Briefbogen
mischt aber CMYK-Flächen aus der Druckvorstufe mit einem RGB-Logo aus
dem Web. Gemessen am Prototyp:

| OutputIntent | Ergebnis |
|---|---|
| sRGB | `DeviceCMYK colour space is used without CMYK output intent profile` — 4 Verstöße |
| FOGRA39 (CMYK) | `DeviceRGB colour space is used without RGB output intent profile` — 36 Verstöße |

Der Fehler kippt nur um. **Der Farbraum des Uploads muss vereinheitlicht
werden, bevor überhaupt etwas darübergelegt wird.**

### Der Aufruf, der funktioniert hat

```bash
gs -dQUIET -dBATCH -dNOPAUSE -sDEVICE=pdfwrite \
   -dColorConversionStrategy=/sRGB \
   -dProcessColorModel=/DeviceRGB \
   -dConvertCMYKImagesToRGB=true \
   -dEmbedAllFonts=true -dSubsetFonts=true \
   -dPDFSETTINGS=/prepress -dCompatibilityLevel=1.7 \
   -sFONTPATH=/usr/share/fonts/truetype/liberation:/usr/share/fonts/truetype/dejavu \
   -sOutputFile=briefpapier_norm.pdf upload.pdf
```

`-sFONTPATH` ist nicht optional: Ohne den Pfad scheitern Briefbögen mit
Base-14-Schriften an `The font program is not embedded`. Mit dem Pfad
werden die Schriften ersetzt und eingebettet — dann grün.

### Die drei Fehlerklassen

| # | Fehler | Ursache | Lösung |
|---|---|---|---|
| 1 | `MIME type ... of an embedded file is missing or invalid` | Subtype-Name des Anhangs falsch escaped | `Name("/text/xml")` — pikepdf kodiert korrekt |
| 2 | `DeviceCMYK ... without CMYK output intent profile` | gemischte Farbräume im Upload | Normalisierung (oben) |
| 3 | `The font program is not embedded` | Base-14-Schriften im Briefbogen | `-sFONTPATH` beim Normalisieren |

Transparenz und Alphakanal-Bilder waren **unkritisch** — die überstanden
die Normalisierung ohne Beanstandung. Das war die Überraschung; ich hatte
sie als Hauptrisiko erwartet.

---

## 5. Zusammenbau zu PDF/A-3B

Referenzimplementierung (pikepdf). Diese Punkte sind alle nötig, keiner
ist entbehrlich:

```python
import pikepdf
from pikepdf import Name, String, Dictionary, Array, Stream

pdf = pikepdf.open(briefpapier_norm)
ov  = pikepdf.open(blatt_bytes)          # reportlab-Overlay
pdf.pages[0].add_overlay(ov.pages[0])

# OutputIntent (sRGB-ICC einbetten)
icc_st = Stream(pdf, icc_bytes); icc_st.N = 3; icc_st.Alternate = Name.DeviceRGB
pdf.Root.OutputIntents = Array([Dictionary(
    Type=Name.OutputIntent, S=Name.GTS_PDFA1,
    OutputConditionIdentifier=String("sRGB IEC61966-2.1"),
    Info=String("sRGB IEC61966-2.1"), DestOutputProfile=icc_st)])

# XML als Anhang
fs = Stream(pdf, xml_bytes)
fs.Type = Name.EmbeddedFile
fs.Subtype = Name("/text/xml")            # <-- Fehlerklasse 1
fs.Params = Dictionary(ModDate=String("D:20260821120000+02'00'"), Size=len(xml_bytes))
spec = pdf.make_indirect(Dictionary(
    Type=Name.Filespec, F=String("factur-x.xml"), UF=String("factur-x.xml"),
    Desc=String("Factur-X/ZUGFeRD Invoice"),
    AFRelationship=Name.Alternative,       # zwingend
    EF=Dictionary(F=fs, UF=fs)))
pdf.Root.AF = Array([spec])
pdf.Root.Names = Dictionary(EmbeddedFiles=Dictionary(
    Names=Array([String("factur-x.xml"), spec])))
pdf.Root.MarkInfo = Dictionary(Marked=True)
pdf.Root.Lang = String("de-DE")
# + XMP-Metadaten, siehe unten
pdf.save(out)
```

**XMP muss enthalten:** `pdfaid:part=3`, `pdfaid:conformance=B`, `dc:title`,
`xmp:CreateDate`/`ModifyDate`/`CreatorTool`, `pdf:Producer` — und das
**Factur-X-Extension-Schema** (`urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#`)
mit den vier Eigenschaften `DocumentFileName`, `DocumentType`, `Version`,
`ConformanceLevel`. Ohne das Extension-Schema ist die Datei kein gültiges
ZUGFeRD. Vollständiges XMP-Muster liegt im Prototyp (`mk_zugferd.py`).

Der Anhang heißt **immer** `factur-x.xml`.

### Validiertes Ergebnis

Beide Testfälle (Briefbogen mit und ohne eingebettete Schriften):

```
PDF/A-3B validation profile — isCompliant="true"
passedRules=124  failedRules=0  failedChecks=0
XML: profile urn:cen.eu:en16931:2017 — status valid
```

---

## 6. Prüfaufbau (gehört in die CI)

```bash
curl -sL -o validator.jar \
  https://repo1.maven.org/maven2/org/mustangproject/validator/2.9.0/validator-2.9.0-shaded.jar
```

Die Jar hat **kein Main-Manifest**. Zum Aufruf ein Wrapper:

```java
import org.mustangproject.validator.ZUGFeRDValidator;
public class Val {
  public static void main(String[] a) throws Exception {
    System.out.println(new ZUGFeRDValidator().validate(a[0]));
  }
}
```

```bash
javac -cp validator.jar Val.java
java -cp .:validator.jar Val rechnung.pdf
```

Enthält veraPDF 1.22.2 für den PDF/A-Teil. Braucht ein **JDK**, nicht nur
JRE. Ergebnis ist XML; auf `<summary status=...>` und `isCompliant` prüfen.

**Jede erzeugte Rechnung läuft in der CI gegen den Validator, mit
Referenzfällen.** Eine einzige ungültige Rechnung beim Steuerprüfer eines
Kunden ruiniert das Produkt. Zusätzlich stichprobenweise im Betrieb.

Diese Notices sind **erwartbar und irrelevant** für reines B2B-ZUGFeRD:
`PEPPOL-EN16931-R001`, `R010`, `R020`, `BR-DE-15`, `BR-DE-2`, `BR-DE-21`
— das sind XRechnung-/Peppol-Regeln. Für Behördenkunden (XRechnung-Export)
müssen sie dagegen erfüllt werden.

---

## 7. Datenmodell und §14-Prüfung

Das Formular **erzwingt** Vollständigkeit — das ist der eigentliche Wert
gegenüber der Word-Vorlage. Blockierend, nicht als Hinweis.

**Stammdaten (einmalig):** Firmierung, Anschrift, Steuernummer und/oder
USt-IdNr., IBAN/BIC, Zahlungsziel-Vorgabe, Kontakt, optional
Kleinunternehmer §19 UStG (dann ohne Steuerausweis, mit Pflichthinweis).

**Je Rechnung:** Empfänger (Merkliste für Stammkunden), fortlaufende
Nummer (automatisch, überschreibbar), Rechnungsdatum, Leistungsdatum oder
-zeitraum, Positionen (Menge, Einheit, Einzelpreis, Steuersatz), Rabatt,
Freitext.

**Steuersätze:** 19 %, 7 %, 0 %, §19 UStG, Reverse Charge,
innergemeinschaftliche Lieferung, Ausfuhr.

**Beträge durchgängig `Decimal`, Rundung `ROUND_HALF_UP`, zwei
Nachkommastellen.** Keine Floats. Summen je Steuersatz aufschlüsseln.

**Schreibzone:** bewusst nur **zwei Werte** — wo endet der Kopf, wo
beginnt der Fuß. Kein Rechteck-Editor. Ein Nicht-Techniker muss das ohne
Erklärung schaffen; das ist das Abnahmekriterium.

---

## 8. MVP-Schnitt

**Rein:** Konto, Stammdaten, Briefpapier-Upload mit Normalisierung und
Ampel, Schreibzone (zwei Regler), Rechnungsformular mit
Pflichtfeld-Erzwingung, Kundenmerkliste, Nummernkreis, Vorschau,
ZUGFeRD-Download, XRechnung-Download, Ablage, Duplikat als Vorlage,
Gutschrift/Korrektur mit Bezug (Typ 381/384), Bezahlung je Rechnung.

**Raus:** Mailversand aus dem Werkzeug, Peppol/Behördenportale als
Versandweg, Eingangsrechnungen, zertifiziertes GoBD-Archiv, Mahnwesen,
Angebote, jede Art Buchhaltung, App.

Rechnungen sind 8 Jahre aufzubewahren. Das Produkt bietet Ablage an,
verspricht aber **keine** zertifizierte GoBD-Archivierung — das gehört
klar in Produkt und AGB, ebenso „keine Steuerberatung".

---

## 9. Marktbefund (Stand August 2026)

Der Markt ist **nicht leer**, und das Konzept hat ihn zu wohlwollend
beschrieben:

- **Konverter-Kategorie** (RechneX, erechnung.new/gotomaxx, EU-Rechnung,
  e-rechnung.tools, Rechnungshub, 7-PDF): PDF hochladen, KI liest aus,
  XML dranhängen. Löst „eigenes Layout" radikaler — man behält die
  Word-Vorlage komplett. Oft kostenlos.
- **Preisanker liegt bei null:** easybill FREE mit Archivierung,
  xrechnungs.de bis 50 Rechnungen/Monat gratis, sevdesk und BillingEngine
  je 3/Monat.
- **Pay-per-Invoice ist besetzt:** RechneX nimmt 3,99 €/Rechnung ohne Abo
  und ohne Konto.
- **winball/erechnungs-validator Pro** bietet bereits Briefpapier als
  Hintergrund-PDF plus Credits — aber nur 240 erzeugte Rechnungen seit
  März 2026.

**Die Lücke, die bleibt:** RechneX' eigene Beispieldatei ist technisch
sauber (PDF/A-3B, 0 Fehler), aber **Briefpapier ist dort ausdrücklich
Enterprise-Funktion**, und das Design bleibt sonst nur „in vielen Fällen"
erhalten. Vermutlich genau wegen der Farbraum-Falle aus §4: Wer das
Original anfasst, kann nicht mehr versprechen, dass es identisch aussieht.

**Wer die Normalisierung bewusst als Produktbestandteil baut statt sie zu
vermeiden, kann Briefpapier für alle anbieten, wo andere auf
Enterprise-Vertrieb verweisen.** Das ist die These, auf der Rechnungsblatt
steht.

Zweitens: Die Konverter können nur finden, was schon dasteht — sie können
Vollständigkeit nicht erzwingen und produzieren im Zweifel eine technisch
valide Rechnung mit inhaltlichem Mangel. Rechnungsblatt kann das nicht.
Dieser Vorteil ist real, aber unsichtbar. **Er muss erzählt werden,
sonst gewinnt der bequemere Ablauf.**

---

## 10. Offene Risiken

1. **Ghostscript ist AGPL.** Kommerzielle Artifex-Lizenz klären, *bevor*
   gebaut wird. Bei „je Rechnung 2–3 €" kann das die Kalkulation kippen.
   Alternativen (mutool, pdfium) können die Farbraumkonversion nur
   teilweise. **Höchste Priorität, blockierend.**
2. **Schriftersetzung** ist der einzige Punkt, an dem das Blatt optisch
   abweichen kann. Gehört sichtbar in die Vorschau: „Wir mussten Schriften
   ersetzen, bitte prüfen."
3. **Ungetestete Bogen-Sorten:** Sonderfarben, eingebettete ICC-Profile,
   verschlüsselte PDFs, mehrseitige Bögen. Dafür braucht es einen sauberen
   Ablehnungsweg statt einer kaputten Rechnung.
4. **Preis:** Wo liegt die Schmerzgrenze, wenn der Wettbewerb bei 0 € und
   3,99 € steht?
5. **Haftungsrahmen:** AGB, Gewährleistungsausschluss für steuerliche
   Richtigkeit, Impressum — wer betreibt es?
6. Zehn echte Testrechnungen mit echten Briefbögen von Bekannten. Die
   Zonen-Bedienung ist gut, wenn ein Nicht-Techniker sie ohne Erklärung
   schafft.

---

## 11. Erste Arbeitsschritte

1. Monorepo `rechnungsblatt` anlegen, Python-Kern als Paket.
2. Datenmodell + §14-Prüfung mit Tests (reine Logik, keine PDFs — schnell
   und wertvoll).
3. CII-XML-Erzeugung, EN-16931-Profil.
4. Normalisierung + Zusammenbau nach §4/§5 portieren.
5. Validator in die CI, mit Referenzfällen aus 2–4.
6. Erst danach die Web-Schicht.

Der Prototyp aus dem Vorgespräch (`mk_briefpapier.py`, `mk_zugferd.py`,
Testbögen, zwei validierte Beispiel-PDFs) existiert und kann als
Ausgangspunkt für Schritt 4 dienen.
