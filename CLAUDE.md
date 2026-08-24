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
docker compose -f deploy/docker-compose.local.yml up -d datenbank
python -m pytest kern/tests web/tests
```

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
