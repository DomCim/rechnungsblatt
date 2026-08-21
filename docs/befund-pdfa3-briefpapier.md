# Befund: PDF/A-3 über beliebigem Briefpapier

*Prototyp-Test, 21.08.2026. Beantwortet „Offene Frage 1" des Konzepts.*

## Ergebnis in einem Satz

Es geht — **aber nicht, indem man das hochgeladene Briefpapier so nimmt,
wie es kommt.** Zwischen Upload und Überlagerung muss zwingend ein
Normalisierungsschritt liegen. Ohne den scheitert praktisch jeder echte
Briefbogen an der PDF/A-3-Prüfung.

## Aufbau des Tests

Zwei künstliche, aber realistische Briefbögen (A4, CMYK-Farbflächen,
halbtransparenter Zierbalken, Logo als PNG mit Alphakanal, Producer
„Adobe InDesign") — einmal mit eingebetteten Schriften, einmal mit
Base-14-Schriften ohne Einbettung.

Pipeline: Briefpapier als Unterlage → Rechnungsinhalt darüber
(pikepdf `add_overlay`) → OutputIntent + XMP inkl. Factur-X-Extension-
Schema → EN-16931-CII-XML als `AFRelationship /Alternative` eingebettet.

Geprüft mit Mustangproject-Validator 2.9.0 (enthält veraPDF 1.22.2),
PDF/A-3B-Profil.

## Die drei Fehlerklassen, die auftraten

| # | Fehler | Ursache | Lösung |
|---|--------|---------|--------|
| 1 | `MIME type ... of an embedded file is missing or invalid` | Subtype-Name des Anhangs falsch escaped | `/text/xml` korrekt kodieren — Einzeiler |
| 2 | `DeviceCMYK colour space is used without CMYK output intent profile` | Briefbogen kommt aus der Druckvorstufe in CMYK, ZUGFeRD-PDF hat sRGB-Ausgabebedingung | **strukturell** — s.u. |
| 3 | `The font program is not embedded` | Briefbogen benutzt Base-14-Schriften | Schrift beim Normalisieren ersetzen und einbetten |

## Fehler 2 ist der eigentliche Punkt

PDF/A erlaubt **genau eine** Ausgabebedingung. Die Gegenprobe mit
CMYK-OutputIntent (FOGRA39) statt sRGB kippt den Fehler nur um:

- sRGB-OutputIntent → `DeviceCMYK ... without CMYK output intent` (4 Verstöße)
- FOGRA39-OutputIntent → `DeviceRGB ... without RGB output intent` (36 Verstöße)

Ein typischer Briefbogen mischt beides: CMYK-Flächen aus der Druckerei,
RGB-Logo aus dem Web. Beides zugleich ist in PDF/A nicht zulässig.
**Der Farbraum des Kunden-Uploads muss vereinheitlicht werden, bevor
überhaupt etwas darübergelegt wird.**

## Was funktioniert hat

Vorschaltschritt mit Ghostscript:

```
gs -dBATCH -dNOPAUSE -sDEVICE=pdfwrite \
   -dColorConversionStrategy=/sRGB -dProcessColorModel=/DeviceRGB \
   -dConvertCMYKImagesToRGB=true \
   -dEmbedAllFonts=true -dSubsetFonts=true \
   -sFONTPATH=<verzeichnis mit ersatzschriften> \
   -sOutputFile=briefpapier_norm.pdf <upload>.pdf
```

Danach beide Fälle:

```
PDF/A-3B validation profile — isCompliant="true"
passedRules=124  failedRules=0  failedChecks=0
XML: profile urn:cen.eu:en16931:2017 — status valid
```

Transparenz und Alphakanal waren unkritisch; die überlebten die
Normalisierung ohne Beanstandung. Das Blatt sieht danach unverändert aus.

## Konsequenzen fürs Produkt

1. **Der Normalisierungsschritt gehört ins Produkt, nicht in die
   Fehlermeldung.** Kein Handwerker versteht „DeviceCMYK ohne
   Ausgabebedingung". Er lädt hoch, das Werkzeug räumt auf.
2. **Ghostscript im Container** — damit hängt am Stack eine AGPL-Komponente.
   Kommerzielle Lizenz von Artifex prüfen oder Alternative suchen
   (pdfium/mutool können das nur teilweise). **Das ist zu klären, bevor
   gebaut wird.**
3. **Schriftersetzung ist der einzige Punkt, an dem das Blatt sich
   optisch ändern kann.** Bei nicht eingebetteten Schriften wird ersetzt —
   meist unauffällig, aber nicht garantiert. Gehört in die Vorschau:
   „Wir mussten Schriften ersetzen, bitte prüfen."
4. **Der Upload braucht eine Ampel.** Nach dem Normalisieren einmal gegen
   veraPDF prüfen und dem Nutzer sofort sagen, ob sein Bogen trägt —
   einmalig beim Einrichten, nicht bei jeder Rechnung.
5. Ein Rest bleibt: Bögen mit Sonderfarben, eingebetteten ICC-Profilen
   oder verschlüsselten PDFs sind nicht getestet. Für die braucht es
   einen sauberen Ablehnungsweg statt einer kaputten Rechnung.

## Nebenbefund Wettbewerb

RechneX (3,99 €/Rechnung, kein Abo) liefert ein sauberes Ergebnis —
deren Beispieldatei ist PDF/A-3B-konform, 0 Fehler. Briefpapier ist
dort aber ausdrücklich **Enterprise-Funktion**, das Design bleibt sonst
nur „in vielen Fällen" erhalten. Vermutlich genau wegen der oben
beschriebenen Farbraum-Falle: Man kann es nicht zuverlässig
automatisieren, ohne den Upload anzufassen — und wer das Original
anfasst, kann nicht mehr versprechen, dass es identisch aussieht.

**Das ist die Lücke.** Wer den Normalisierungsschritt bewusst als
Produktbestandteil baut (statt ihn zu vermeiden), kann Briefpapier für
alle anbieten, wo andere auf Enterprise verweisen.
