# Hinweise für Claude Code

Arbeitsanweisungen für dieses Repository. Was hier steht, geht Gewohnheiten
vor.

## Branch-Strategie

Drei Ebenen, in dieser Richtung:

```
feature-branch  ──PR──>  develop  ──PR──>  main
```

| Branch | Rolle |
|---|---|
| `main` | Veröffentlichter Stand. Nur was hier liegt, geht auf den Server. Kein direkter Push. |
| `develop` | Sammelbecken. Hier laufen die fertigen Feature-Branches zusammen und reifen gemeinsam. |
| `claude/…`, `feature/…` | Ein Branch je Vorhaben, immer **von `develop`** abgezweigt. |

**Regeln**

1. **Niemals direkt auf `main` oder `develop` committen.** Beides bekommt
   Änderungen ausschließlich über Pull Requests.
2. **Feature-Branches gehen von `develop` aus**, nicht von `main`:
   `git fetch origin && git checkout -b feature/… origin/develop`
3. **Ein PR je Vorhaben, Ziel `develop`.** Er wird erst gestellt, wenn die
   Tests lokal grün sind (siehe unten) — nicht als Zwischenstand.
4. **`develop` → `main` nur zum Veröffentlichen.** Dieser PR ist die
   bewusste Entscheidung „das geht jetzt raus"; er fasst mehrere Features
   zusammen und wird nicht nebenbei gemerged.
5. Nach dem Merge nach `main` wird `main` zurück nach `develop` gezogen,
   falls am Release noch etwas korrigiert wurde — damit die beiden nicht
   auseinanderlaufen.
6. **Kein Force-Push** auf `main` oder `develop`. Auf einem eigenen
   Feature-Branch ist Rebase in Ordnung, solange niemand sonst darauf
   arbeitet.

**Vor jedem PR**

- Tests grün (Kern **und** Web, siehe unten) — die Web-Tests brauchen eine
  laufende Datenbank, sonst überspringen sie sich stillschweigend und der
  PR sieht grüner aus, als er ist.
- Bei Änderungen am Beleg zusätzlich die Referenzfälle gegen den
  Mustang-Validator prüfen (`scripts/`). Eine ungültige Rechnung beim
  Steuerprüfer eines Kunden ruiniert das Produkt — das ist die Begründung
  aus `docs/uebergabe.md` §6.
- README und die betroffenen Bereichs-READMEs mitziehen.

## Bauen und Veröffentlichen

Zwei Workflows mit klarer Aufgabenteilung:

| Workflow | Auslöser | Tut |
|---|---|---|
| `ci.yml` | **nur manuell** (Actions → CI → „Run workflow") | Kern- und Web-Tests mit Postgres-Dienst, Referenzfälle gegen den Mustang-Validator |
| `veroeffentlichen.yml` | Push auf `main`, zusätzlich manuell | Baut `deploy/Dockerfile` und schiebt das Image nach `ghcr.io/domcim/rechnungsblatt` |

`ci.yml` bleibt manuell, um Actions-Minuten zu sparen; getestet wird lokal
vor jedem Push.

**Der Ablauf eines Release**

1. Release-PR `develop` → `main` stellen.
2. `ci.yml` von Hand auf dem PR-Stand starten — die letzte Prüfung, bevor
   etwas auf den Server geht.
3. Mergen. Der Push auf `main` löst `veroeffentlichen.yml` aus; das Image
   erscheint als `latest`, als Datum und als `sha-<commit>`.
4. **Ausgerollt ist damit noch nichts.** In Portainer den Stack neu
   deployen — er zieht das Image (`pull_policy: always`).

`RECHNUNGSBLATT_VERSION` im Stack setzen, um auf einen bestimmten Stand
festzunageln statt `latest` zu folgen; das ist zugleich der Rückweg, wenn
ein Release schiefgeht.

## Konto und Anmeldung

Dieses Repository gehört dem privaten Konto **DomCim**, nicht dem
Arbeitskonto. Auf dem Entwicklungsrechner sind beide in `gh` angemeldet,
aktiv ist das Arbeitskonto — deshalb ist hier einiges lokal umgestellt.

| Was | Wert |
|---|---|
| `user.name` | `Dominik Dill` |
| `user.email` | `92850574+DomCim@users.noreply.github.com` |
| `credential.helper` (lokal) | `store --file=~/.git-credentials-domcim` |

Die Anmeldedaten liegen **nur** in dieser einen Datei und enthalten allein
das DomCim-Token. Das globale `gh`-Anmeldeverfahren ist absichtlich
ausgeschaltet (leerer `credential.helper` davor), weil es immer das aktive —
also das falsche — Konto liefert.

**Regeln**

1. Vor dem ersten Commit prüfen, dass die Zuordnung stimmt:
   `git log -1 --format='%an <%ae>'` muss die `…+DomCim@…`-Adresse zeigen.
   Ein Commit mit der Arbeitsadresse gehört nicht in dieses Repository.
2. **`gh` niemals direkt aufrufen.** Bare `gh` benutzt das Arbeitskonto und
   hat hier nur Leserechte; `gh pr create` scheitert damit. Stattdessen:
   `scripts/gh-domcim.sh pr create --base develop --fill`
3. Das aktive `gh`-Konto **nicht** global umstellen (`gh auth switch`) — das
   bricht die Arbeit an den Cimatron-Repos.
4. Läuft das Token ab, `gh auth login` für DomCim wiederholen und die
   Datei neu schreiben; sie wird nicht automatisch nachgezogen.

## Projekt

Monorepo. Der **Kern** ist der Wert, die Oberfläche ist austauschbar
(`docs/uebergabe.md` §2). Fachliche Entscheidungen gehören in `kern/`, nie
in die Web-Schicht.

```
kern/   Datenmodell, §14-Prüfung, CII-XML, Normalisierung, PDF/A-3B
web/    FastAPI: öffentliche Seite, Konten (PostgreSQL), Mandantenbereich
deploy/ Dockerfile, lokaler Compose-Stack, Portainer-Stack
docs/   Projektübergabe (§-Verweise im Code beziehen sich darauf)
```

**Kernregel, die nicht verhandelbar ist:** PDF und XML entstehen aus
denselben Daten im selben Vorgang. Ein bestehendes PDF wird nie nachträglich
angereichert.

## Tests

```bash
pip install -e "./kern[test]" -e "./web[test]"

# Kern allein — braucht Ghostscript und die Ersatzschriften
python -m pytest kern/tests

# Web braucht zusätzlich PostgreSQL, sonst werden die Konten- und
# Mandantentests übersprungen statt zu scheitern
docker compose -f deploy/docker-compose.local.yml --profile test up -d testdatenbank
TEST_DATENBANK_URL=postgresql://rechnungsblatt:rechnungsblatt@127.0.0.1:5433/rechnungsblatt_test   python -m pytest kern/tests web/tests
```

**Die Tests niemals gegen den Dienst `datenbank` laufen lassen.** Sie machen
vor jedem Fall ein `TRUNCATE verbrauch, sitzungen, nutzer RESTART IDENTITY`
(`web/tests/conftest.py`). Trifft das die Entwicklungsdatenbank, ist die
Anmeldung weg — und schlimmer: die neu vergebenen Nutzer-IDs passen nicht
mehr zu den Verzeichnissen unter `DATEN/nutzer/<id>/`, die Einrichtung eines
Mandanten wird also verwaist. Dafür gibt es `testdatenbank` auf Port 5433:
eigener Dienst, eigene Datenbank, `tmpfs` statt Volume.

Fehlen `fonts-crosextra-carlito` und `fonts-crosextra-caladea`, scheitern
die Gestaltungstests — das ist ein Umgebungsproblem, kein Defekt.

Eine abweichende Datenbank über `TEST_DATENBANK_URL`.

## Konventionen

- **Deutsch** in Code, Kommentaren, Commit-Nachrichten und Oberfläche.
  Bezeichner sind deutsch (`erzeuge_rechnung`, `Schreibzone`, `wurzel`).
  Englisch nur, wo die Norm es vorgibt (`AFRelationship`, `UST_19`).
- **Kein Frontend-Framework, kein Build-Schritt.** Die Seiten sind
  handgeschriebenes HTML mit `basis.css` und `werkzeuge.js`; Texte laufen
  über `data-i18n` und existieren in DE und EN.
- Beträge durchgängig `Decimal`, `ROUND_HALF_UP`, zwei Nachkommastellen.
  Keine Floats.
- Befunde der §14-Prüfung tragen **stabile Codes** (`S1`…, `R1`…, `P0`…).
  Die Oberfläche übersetzt über den Code; die deutschen Texte im Kern sind
  Fallback.
- Nutzdaten liegen je Mandant unter `DATEN/nutzer/<id>/`. Kein neuer
  Endpunkt darf auf ein gemeinsames Verzeichnis zugreifen.

## Offene Entscheidungen — nicht eigenmächtig festlegen

- **Abrechnungsmodell.** Tarife stehen als Datensatz in der Datenbank, damit
  Abo, Prepaid oder eine Mischung möglich bleiben. Preise nicht in den Code
  schreiben (Hintergrund: `README.md`, Risiko 4).
- **Ghostscript ist AGPL.** Die Artifex-Lizenzfrage blockiert den
  Produktivbetrieb (`docs/uebergabe.md` §10.1).

## Handoff — Stand 2026-08-30

Arbeitsstand für einen frischen Chat. **Beim Aktualisieren ersetzen, nicht
anhängen.**

**Aufgabe.** Rechnungsblatt lokal in Docker betreiben (Test auch vom Handy
im LAN unter `http://192.168.178.62:8000`), Beleg-Kern und Oberfläche
schrittweise verbessern, Portainer-Ausrollung über Repository vorbereiten.

### Erledigt in dieser Sitzung

| Bereich | Änderung |
|---|---|
| Portainer | `deploy/stack.env.beispiel` als Abschriftvorlage; README um Repo-Deploy ergänzt (Branch `refs/heads/main`, zwei Tokens bei privatem Repo, „Pull and redeploy", Webhook). `.dockerignore` war bereits vollständig. |
| Kern/Web | **Rechnungsvorlagen**: `GET/PUT /api/vorlagen` → `vorlagen.json` je Mandant. Benannte Positionslisten **ohne** Empfänger — dieselbe Leistung an wechselnde Kunden. In `rechnung.html` Auswahlfeld „Vorlage laden …" + „Als Vorlage sichern"; Löschen über dieselbe Auswahl (Einträge mit ✕). |
| Kern/Web | **Nummernsperre**: Eine vergebene Rechnungsnummer wird nicht mehr überschrieben (409 `nummer_vergeben`), Prüfung **vor** der Kontingentbuchung. |
| Web | **Storno-Weg**: „Stornieren" je Rechnung in der Ablage bereitet eine Gutschrift vor (Positionen übernommen, Bezugsnummer/-datum gesetzt, neue eigene Nummer). Nur bei `typ === "RECHNUNG"`. |
| Gestaltung | `basis.css`: Doppelrand über `.karte::before`, zwei Bewegungskurven als Token (`--kurve`, `--kurve-kurz`), Knopf-Physik (`:active` scale 0.975), gestaffelter Auftritt beim Laden, Pillenknöpfe. |
| Gestaltung | **Akzentfarben vereinheitlicht** (siehe unten). |
| Startseite | Scroll-Auftritt für die sechs Abschnitte unter dem Auftakt via `IntersectionObserver`; Knöpfe auf Pille + `:active`. |
| Anmeldeseite | Registrierung als `<details>`-Aufklapper (nur < 761px), Marke nicht mehr rot. |

### Die Farbentscheidung — nicht rückgängig machen

Startseite und Arbeitsbereich zeigten unterschiedliche Rottöne. Gemessen
(WCAG): **keine einzelne Farbe kann beides** — als Text auf dunklem Grund
braucht sie Helligkeit, als Fläche unter weißer Schrift Tiefe.

| Token | Wert (dunkel) | Rolle | Kontrast |
|---|---|---|---|
| `--akzent` | `#c8452d` | Flächen, weiße Schrift darauf | 4,83:1 |
| `--akzent-tinte` | `#e2694c` | Text auf dem Grund | 5,14:1 |

`--akzent` **nie** als Textfarbe verwenden (nur 3,5:1). `nav.reiter a:hover`
wurde deshalb auf `--akzent-tinte` umgestellt.

### Zwei Bereiche, bewusst getrennt

Das ist **kein** Fehler und kam mehrfach als Frage auf: Die Startseite hat
eine eigene Handschrift (Papier-Thema, `--stempel: #c8452d`, eigener
Stilblock **nach** `basis.css`, gewinnt daher bei Konflikten). Der
Arbeitsbereich bleibt nüchtern. Wer dort etwas ändert, muss prüfen, ob
`start.html` es überschreibt — so blieben die Knöpfe dort zunächst eckig.

### Stand

**142 Tests grün** (vorher 140; zwei neue in `web/tests/test_app.py`:
`test_vergebene_nummer_wird_nicht_ueberschrieben`,
`test_gutschrift_traegt_bezug_zur_ursprungsrechnung`). Alles **uncommitted**
auf `claude/konto-einrichtung` — thematisch der falsche Branch.

Gemessen, nicht geschätzt: Bei 390 px ist `scrollWidth == clientWidth == 390`
auf `/app/rechnung` und `/anmelden` — kein horizontaler Überlauf.

### Als Nächstes

1. **Landing Page erweitern.** Sie verschweigt rund zehn fertige Funktionen:
   Gutschrift/Korrektur/Storno, Kleinunternehmer (§ 19), GiroCode, sechs
   Layouts + Akzentfarbe, mehrseitige Belege mit Übertrag, Reverse Charge,
   Kunden- und Artikelstamm, Rechnungsvorlagen, DE/EN, Installation als
   App aufs Handy. Alles im Code belegt, nichts davon steht auf der Seite.
2. **Änderungsprotokoll** unter `/neuerungen` plus einmaliger Hinweisstreifen
   im Arbeitsbereich (Konto merkt sich den zuletzt gesehenen Stand). E-Mail
   bewusst nicht — Versand, Abmeldung und Rechtsgrundlage lohnen bei
   handfreigeschalteten Konten nicht.
3. Branch von `develop` abzweigen, Änderungen umhängen, PR stellen
   (`scripts/gh-domcim.sh pr create --base develop`). Mehrfach angeboten,
   noch nicht entschieden.
4. Gültige IBAN in die Stammdaten — dort steht `DE00 00000000000000`, damit
   lehnt die §14-Prüfung jede Rechnung ab (Befund `S6`).

### Stolpersteine

- **Nur im Scratchpad arbeiten, nie in `/tmp`.** Git Bash schreibt den Pfad
  um; ein Skript hat so `start.html` überschrieben. Wiederhergestellt aus
  dem laufenden Container (`docker cp rechnungsblatt-lokal:/srv/…`) — das
  Image ist die Rückfallebene, solange nicht neu gebaut wurde.
- **`MSYS_NO_PATHCONV=1`** vor jedes `docker exec/run/cp` mit absoluten
  Container-Pfaden, sonst wird `/daten` zu `C:/Program Files/Git/daten`.
- **Bash-Heredocs fressen `\\n`.** Python-Skripte mit Escape-Sequenzen in
  eine Datei schreiben und `python datei.py` aufrufen, nicht per Heredoc.
- **Port 5433 ist von `did0m-verwaltung` belegt** (fremdes Projekt, nicht
  anfassen). Wegwerf-Testdatenbank auf 5434 starten:
  `docker run -d --name rb-testdb-5434 -p 127.0.0.1:5434:5432 -e POSTGRES_USER=rechnungsblatt -e POSTGRES_PASSWORD=rechnungsblatt -e POSTGRES_DB=rechnungsblatt_test --tmpfs /var/lib/postgresql/data postgres:16-alpine`
- Tests laufen nur im Container (Ghostscript, pytest, Referenzfälle):
  `docker run --rm --network host -v "$(pwd -W)":/quelle -w /quelle --entrypoint sh deploy-rechnungsblatt -c 'pip install -q -e "./kern[test]" -e "./web[test]"; TEST_DATENBANK_URL=…5434… python -m pytest kern/tests web/tests -q'`
- Die Web-Tests leeren vor jedem Fall `nutzer`, `sitzungen`, `verbrauch`.
  Niemals gegen den Dienst `datenbank` richten.
- **Nach jeder Codeänderung neu bauen**, sonst prüft man den alten Stand:
  `docker compose -f deploy/docker-compose.local.yml up --build -d rechnungsblatt`
- Die Gestaltung wandert durch **drei** Stellen in `web/.../main.py`:
  `_gestaltung_aus_json`, das PUT auf `/api/gestaltung` (filtert die Felder
  einzeln!) und die Vorschau. Wird eine vergessen, verschwindet ein Feld
  stillschweigend.
- Der Beleg entsteht in **zwei Durchläufen** (zählen, dann zeichnen) — anders
  ist „Seite 1 von 3" nicht möglich.
- `werkzeuge.js` kennt nur `data-i18n` und `data-i18n-platzhalter`. Es gibt
  **kein** `RB.melde`; Rückmeldungen laufen über
  `el("aktionMeldung").textContent`. `RB.api(pfad, optionen)` nimmt echte
  `fetch`-Optionen (`method`, `headers`, `body`).
- Edge headless meldet auf diesem Rechner 492 px Viewport unabhängig von
  `--window-size` und fotografiert schmaler als er rendert. Breiten **messen**
  (`scrollWidth`/`clientWidth`), nicht am Screenshot beurteilen. Ein
  `IntersectionObserver` im iframe meldet zudem falsch — direkt aufrufen.
- Kein Löschweg für Belege über die API (8 Jahre Aufbewahrung) — Testbelege
  direkt im Volume entfernen (`docker exec -u root …`, die App läuft als
  Nicht-Root und darf ihre eigenen Seiten nicht löschen).
