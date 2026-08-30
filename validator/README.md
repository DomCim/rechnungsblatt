# Validator-Aufbau

Jede erzeugte Rechnung läuft in der CI gegen den Mustangproject-Validator
(enthält veraPDF 1.22.2 für den PDF/A-Teil). Eine einzige ungültige Rechnung
beim Steuerprüfer eines Kunden ruiniert das Produkt.

```bash
curl -sL -o validator.jar \
  https://repo1.maven.org/maven2/org/mustangproject/validator/2.9.0/validator-2.9.0-shaded.jar
javac -cp validator.jar Val.java          # braucht ein JDK, nicht nur JRE
java -cp .:validator.jar Val rechnung.pdf # Ergebnis ist XML
```

Geprüft wird auf `<summary status="valid">` und (beim PDF-Teil)
`isCompliant="true"` — das übernimmt `scripts/pruefe_referenzfaelle.py`.

## Erwartbare, irrelevante Notices (reines B2B-ZUGFeRD)

`PEPPOL-EN16931-R001`, `R010`, `R020`, `BR-DE-15`, `BR-DE-2`, `BR-DE-21` —
das sind XRechnung-/Peppol-Regeln. Für Behördenkunden (XRechnung-Export)
müssen sie dagegen erfüllt werden; der XRechnung-Referenzfall deckt das ab.
