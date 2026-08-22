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

Der Workflow `.github/workflows/ci.yml` ist **bewusst nur manuell startbar**
(Actions → CI → „Run workflow"), um keine Actions-Minuten zu verbrauchen.
Er fährt zwei Jobs: Kern- und Web-Tests (mit Postgres-Dienst) sowie die
vollständige Validierung der Referenzfälle.

**Der Workflow baut derzeit kein Image und veröffentlicht nichts.** Gebaut
wird beim Deploy: Der Portainer-Stack zieht den Branch und baut aus
`deploy/Dockerfile` selbst (`build: context: ..`). „Veröffentlichen" heißt
also: nach `main` mergen, dann in Portainer den Stack neu ausrollen.

Vor dem Ausrollen den Workflow einmal von Hand auf `main` starten — das ist
die letzte Prüfung, bevor der Stand auf den Server geht.

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
