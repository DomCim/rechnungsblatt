# Web-Schicht

FastAPI-App (`src/rechnungsblatt_web/`) über der schmalen Kern-Schnittstelle
(`rechnungsblatt_kern.api`). Zwei Module: `main.py` liefert Seiten und
JSON-Schnittstelle, `konten.py` kapselt alles, was mit Konto, Rolle,
Sitzung, Tarif und Kontingent zu tun hat (PostgreSQL).

## Pfade

| Pfad | Zugang | Inhalt |
|---|---|---|
| `/` | offen | Öffentliche Seite: erklärt das Modell, rendert die Tarife aus der Datenbank |
| `/anmelden` | offen | Anmeldung und Registrierung |
| `/app` | Konto | Verteiler — leitet auf `/app/rechnung`, sobald die Einrichtung steht, sonst auf `/app/einrichtung` |
| `/app/einrichtung` | Konto | Briefpapier, Schreibzone, Stammdaten, Gestaltung |
| `/app/rechnung` | Konto | Rechnungsformular |
| `/app/ablage` | Konto | Erzeugte Belege mit PDF und XML |
| `/app/konto` | Anmeldung | Tarif, Verbrauch, Guthaben, Passwortwechsel |
| `/app/verwaltung` | Admin | Konten freischalten und sperren, Rolle, Tarif, Guthaben, Tarife pflegen |
| `/api/gesundheit` | offen | Healthcheck inkl. Datenbankprüfung |

**Landung nach der Anmeldung ist das Rechnungsformular**, sobald Briefpapier,
Schreibzone und Stammdaten vorliegen — die Einrichtung ist nur der Umweg
davor. Wer noch nicht freigeschaltet ist, sieht statt der Seite den
Wartehinweis.

## Konten und Mandanten

- Registrierung ist offen, das Konto steht danach aber auf **`wartet`** und
  kommt erst nach Freigabe im Adminbereich in den Arbeitsbereich.
  Statuswerte: `wartet`, `frei`, `gesperrt` — Sperren beendet zugleich alle
  offenen Sitzungen.
- Rollen: `kunde` und `admin`. Der letzte Admin lässt sich weder
  degradieren noch löschen.
- Der Start-Admin kommt aus `ADMIN_EMAIL` / `ADMIN_PASSWORT`. Ohne gesetztes
  Passwort erzeugt die App eines und schreibt es **einmalig als Warnung ins
  Log**. Existiert das Konto bereits, bleibt sein Passwort unangetastet — ein
  Neustart dreht eine Änderung also nicht zurück.
- Passwörter: `hashlib.scrypt` mit eigenem Salz je Hash, mindestens zehn
  Zeichen. Sitzungsschlüssel liegen nur als SHA-256 in der Datenbank; das
  Cookie ist `HttpOnly`, `SameSite=Lax` und über HTTPS `Secure`.
- **Nutzdaten sind je Konto getrennt**: `DATEN/nutzer/<id>/`. Kein Endpunkt
  greift noch auf ein gemeinsames Verzeichnis zu.

## Tarife und Kontingent

Tarife stehen als Tabelle in der Datenbank, nicht im Code — mit
Monatsbeitrag, Inklusivmenge und Preis je Rechnung zugleich. Damit lässt
sich Abo, Prepaid oder eine Mischung abbilden, ohne etwas umzubauen; die
öffentliche Seite rendert daraus ihre Preistafel, der Adminbereich pflegt
sie. Ausgeliefert wird ein Vorschlag (`probe`, `guthaben`, `monat`,
`unbegrenzt`) — **die Preisentscheidung ist damit ausdrücklich noch nicht
gefallen** (siehe `docs/uebergabe.md` §9 und §10.4).

Beim Erzeugen einer Rechnung wird der Monatsverbrauch gezählt. Über der
Inklusivmenge zieht die App den Preis je Rechnung vom Guthaben ab; reicht
das nicht, antwortet `/api/rechnung` mit **402** und es entsteht kein PDF.
Guthaben bucht bis auf Weiteres der Admin — ein Zahlungsanbieter ist nicht
angebunden.

## Oberfläche

- **Einrichtung** (`/app/einrichtung`): Briefpapier-Upload → Normalisierung → Ampel
  (inkl. Schriftersetzungs-Warnung), Schreibzone (eingebetteter
  [`zonen-editor/`](zonen-editor/)), Stammdaten, **Gestaltung** (kuratierte
  Schriften, Schriftgrad, drei geprüfte Layoutvarianten, Belegdaten-Schalter)
  mit Live-Vorschau einer Musterrechnung auf dem echten Briefpapier.
  **Bewusst keine freie Positionierung** — Produktentscheidung: wenige
  verständliche Optionen statt eines Layout-Editors (Übergabe §7); jede
  angebotene Kombination ist gegen den Validator geprüft.
- **Neue Rechnung** (`/app/rechnung`): Formular mit Pflichtfeld-Erzwingung
  (Befund-Codes vom Kern, feldgenau angezeigt), Positionen, Rabatt,
  Gutschrift/Korrektur mit Bezug, Nummernkreis, Merkliste + Duplikat als
  Vorlage aus der Ablage, ZUGFeRD-PDF- und XRechnung-Download.
- **Ablage** (`/app/ablage`): alle Belege des Kontos mit Suche, PDF und XML.
  Ein stornierter Beleg ist in der Liste als solcher gekennzeichnet.
- **Für die Betriebsprüfung** (im Konto): alle Belege eines Zeitraums als ZIP
  (PDF, XML, Eingabedaten, Belegprotokoll je Beleg, dazu `uebersicht.csv`,
  die Siegelkette und eine Erläuterung), ein Entwurf der
  Verfahrensdokumentation mit den eigenen Stammdaten, und die Nachprüfung
  der Siegelkette.

```bash
pip install -e ./kern -e "./web[test]"

# Die Web-Tests brauchen eine echte Datenbank; ohne sie werden sie
# übersprungen statt zu scheitern.
docker compose -f deploy/docker-compose.local.yml up -d datenbank
python -m pytest web/tests

DATEN_VERZEICHNIS=/tmp/rb-daten \
DATENBANK_URL=postgresql://rechnungsblatt:rechnungsblatt@127.0.0.1:5432/rechnungsblatt \
ADMIN_EMAIL=admin@rechnungsblatt.local ADMIN_PASSWORT=rechnungsblatt-admin \
uvicorn rechnungsblatt_web.main:app --reload
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

## Besucherzählung

Plausible läuft im internen Netz — ohne Portfreigabe, ohne Zertifikat, für
den Browser eines Besuchers nicht erreichbar. Rechnungsblatt liefert das
Zählskript deshalb selbst aus und reicht die Ereignisse nach innen weiter:

    Besucher → rechnungsblatt.de/statistik/zaehler.js → Plausible
    Besucher → rechnungsblatt.de/statistik/ereignis   → Plausible

Zwei Dinge fallen dabei nebenbei ab: Ein Skript, dessen Adresse
`plausible` enthält, schlucken die gängigen Werbeblockerlisten — über die
eigene Adresse ist es eine Datei wie jede andere. Und die
Sicherheitsrichtlinie braucht keine Ausnahme für einen fremden Host.

**`PLAUSIBLE_URL` trägt die interne Adresse** (`http://plausible:8000`),
nicht eine öffentliche. Bis zum 01.09.2026 stand dort die Adresse eines
Containers, die der Browser nicht auflösen konnte, und die Anfrage wurde
zusätzlich als Mixed Content blockiert — gezählt wurde nichts, aufgefallen
ist es erst in einem PageSpeed-Bericht.

Fällt Plausible aus, liefert `/statistik/zaehler.js` ein leeres Skript und
`/statistik/ereignis` antwortet mit 202. Ein verlorener Seitenaufruf in der
Statistik ist das kleinere Übel gegenüber einem Fehler in der Konsole des
Kunden.

Unter Fernsteuerung (`navigator.webdriver`, Headless Chrome) zählt das
Skript nicht mit — sonst verfälschten die eigenen Messläufe die Statistik.

## MVP-Umfang

Siehe `docs/uebergabe.md` §8 — Konto (steht), Stammdaten, Briefpapier-Upload,
Schreibzone, Rechnungsformular, Kundenmerkliste, Nummernkreis, Vorschau,
ZUGFeRD- und XRechnung-Download, Ablage, Duplikat als Vorlage,
Gutschrift/Korrektur, Bezahlung je Rechnung. Kein Mailversand, kein Peppol,
kein Mahnwesen, keine Buchhaltung.

**Weiterhin kein GoBD-Archiv-Versprechen.** Belegprotokoll, Siegelkette und
Gesamtexport sind Maßnahmen im Sinne der GoBD Rz. 110 — sie machen
nachträgliche Änderungen sichtbar. Ob sie im Einzelfall genügen, beurteilt
der steuerliche Berater; die Verantwortung für die Ordnungsmäßigkeit liegt
ohnehin allein beim Steuerpflichtigen (Rz. 21). Eine Zertifizierung durch
die Finanzverwaltung gibt es nicht (Rz. 179–181), und „GoBD-konform" darf
deshalb nirgends unbedingt zugesichert werden.
