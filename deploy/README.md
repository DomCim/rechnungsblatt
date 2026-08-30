# Veröffentlichen mit Portainer + Traefik

Zielbild: Docker-Stack in Portainer hinter der vorhandenen Kette

```
Nginx Proxy Manager  ──HTTP──>  Traefik  ──>  Container
   (Zertifikat)                 (Netz `edge`)
```

NPM ist der Eintrittspunkt und hält das Zertifikat; Traefik verteilt
dahinter auf die Container — eine Docker-Sock für alle Stacks. Deshalb
trägt der Router hier **kein** TLS-Label: Verschlüsselt wird eine Schicht
davor. Dieselbe Schreibweise wie in den Stacks `DiD0m-Verwaltung` und
`vh-website`.

Plausible-Analytics wird seit dem Umbau **im Adminbereich** eingetragen,
nicht mehr über den Stack.

## Erst lokal testen (Docker Desktop)

Kein Traefik, kein Plausible, keine GitHub-Minuten — einfach:

```bash
git clone https://github.com/DomCim/rechnungsblatt.git
cd rechnungsblatt
git checkout claude/rechnungsblatt-repo-setup-qc7mvu   # solange nicht gemerged
docker compose -f deploy/docker-compose.local.yml up --build
```

Dann **http://localhost:8000** öffnen. Dort liegt zuerst die öffentliche
Seite; anmelden unter `/anmelden` mit dem lokalen Admin:

    admin@rechnungsblatt.local / rechnungsblatt-admin

Danach Einrichtung durchklicken, Rechnung erzeugen, PDF prüfen. Die
Nutzdaten liegen im Volume `rechnungsblatt-daten-lokal`, die Konten in
`rechnungsblatt-db-lokal`; beide überleben Neustarts, komplett zurücksetzen
mit `docker compose -f deploy/docker-compose.local.yml down -v`.

Nur die Datenbank starten, etwa für `pytest web/tests`:

```bash
docker compose -f deploy/docker-compose.local.yml up -d datenbank
```

Nach Code-Änderungen reicht erneut `up --build` (Docker baut nur die
geänderten Schichten neu). Wenn das lokal rund läuft, denselben Stand über
den Portainer-Stack unten veröffentlichen — gleiche Dockerfile, gleiches
Image, nur mit Traefik-Labels und Plausible obendrauf.

## Stack anlegen (Portainer)

1. **Stacks → Add stack → Repository**
   - Repository-URL: `https://github.com/DomCim/rechnungsblatt.git`
   - **Repository reference:** `refs/heads/main` — nicht `develop`. Nur was
     auf `main` liegt, gehört auf den Server (`CLAUDE.md`,
     Branch-Strategie); und nur für `main` baut der Workflow das Image,
     das dieser Stack zieht.
   - Compose path: `deploy/docker-compose.yml`
   - Ist das Repository privat: **Authentication** einschalten und ein
     GitHub-Token mit `repo`-Leserecht hinterlegen. Das ist ein anderes
     Token als das der Registry-Anmeldung weiter unten — das eine holt die
     Compose-Datei, das andere das Image.
2. **Environment variables** setzen:
   | Variable | Beispiel | Zweck |
   |---|---|---|
   | `RECHNUNGSBLATT_DOMAIN` | `rechnungsblatt.example.de` | Traefik-Host-Regel **und** Plausible-`data-domain` |
   | `DB_PASSWORT` | (lang und zufällig) | Passwort der PostgreSQL-Instanz im Stack |
   | `ADMIN_EMAIL` | `sie@example.de` | Anmeldung des ersten Admins |
   | `ADMIN_PASSWORT` | (mind. 10 Zeichen) | dessen Startpasswort — nach der ersten Anmeldung unter „Konto" ändern |
   | `RECHNUNGSBLATT_SCHLUESSEL` | (`openssl rand -base64 32`) | verschlüsselt das SMTP-Passwort in der Datenbank |

   Alle fünf sind Pflicht; fehlt eine, verweigert der Stack den Start mit
   einer Meldung statt still einen Standardwert zu verwenden.

   Optional: `RECHNUNGSBLATT_VERSION` (auf einem Stand bleiben statt
   `latest`) und `TRAEFIK_ENTRYPOINT` (Vorgabe `web`, siehe oben).
   Plausible steht im Adminbereich, nicht mehr hier.

   Bequemer als Feld für Feld: in Portainer **Advanced mode** wählen und
   `deploy/stack.env.beispiel` hineinkopieren, dann die Werte ersetzen.
   Die Datei liegt nur als Vorlage im Repository — beim Repo-Deploy löst
   Portainer `${…}` ausschließlich aus diesen Formularfeldern auf, eine
   `.env` neben der Compose-Datei wird **nicht** gelesen.

   **`DB_PASSWORT` nur aus Buchstaben und Ziffern wählen.** Es wird in die
   Verbindungs-URL `postgresql://…:PASSWORT@datenbank:5432/…` eingesetzt;
   ein `@`, `:`, `/`, `#` oder `%` darin zerlegt die URL und die App findet
   die Datenbank nicht mehr. Länge statt Sonderzeichen.
3. **Deploy the stack** — der Stack zieht das fertige Image
   `ghcr.io/domcim/rechnungsblatt:latest` (Python 3.12 + Ghostscript +
   Ersatzschriften, App als Nicht-Root). Gebaut hat es der Workflow
   „Veröffentlichen" beim letzten Push auf `main`; auf dem Server wird
   nichts mehr kompiliert.

   Ist das GHCR-Paket privat — die Voreinstellung —, braucht Portainer
   einmalig eine **Registry-Anmeldung** (Registries → Add registry →
   Custom, `ghcr.io`, GitHub-Benutzername, Personal Access Token mit
   `read:packages`). Alternativ das Paket in GitHub unter Packages →
   Package settings auf öffentlich stellen.

   Optional `RECHNUNGSBLATT_VERSION` setzen (z. B. `sha-<commit>` oder ein
   Datum wie `2026-08-22`), um auf einem bestimmten Stand zu bleiben statt
   `latest` zu folgen. Das ist zugleich der Rückweg, wenn ein Release
   schiefgeht: alten Wert eintragen, Stack neu deployen.

Erzeugte Belege und die Einrichtung liegen im Volume `daten` (`/daten` im
Container), getrennt je Konto unter `nutzer/<id>/`; die Konten selbst im
Volume `db`. Bei Stack-Updates bleibt beides erhalten. Rechnungen sind 8
Jahre aufzubewahren: **beide** Volumes in die Server-Sicherung aufnehmen —
ohne die Datenbank lässt sich später nicht mehr zuordnen, wem welches
Verzeichnis gehört.

## Ein Release ausrollen

```
develop ──PR──> main ──Push löst Workflow aus──> Image in ghcr.io
                                                        │
                                        Portainer: Stack neu deployen
```

Der Push auf `main` baut und veröffentlicht nur das Image — **ausgerollt
ist damit nichts.** Der letzte Schritt bleibt bewusst manuell. Vor dem
Merge einmal den CI-Workflow von Hand starten; er ist die letzte Prüfung,
bevor der Stand auf den Server geht. Näheres in `CLAUDE.md`.

Beim Repo-Stack heißt „neu deployen" **Stack → Pull and redeploy**. Das
holt zweierlei auf einmal: die Compose-Datei aus `main` und, wegen
`pull_policy: always`, das neue Image. Eine Änderung an der Compose-Datei
gehört damit ins Repository, nicht ins Portainer-Textfeld — wer dort
editiert, verliert es beim nächsten Pull.

Automatisch geht es auch: Im Stack **Webhook** einschalten, die erzeugte
URL kopieren und in GitHub unter Settings → Webhooks eintragen (Content
type `application/json`, nur das Push-Ereignis). Dann rollt jeder Push auf
`main` sofort aus. Das nimmt die letzte Handbremse heraus — reizvoll,
solange die Testabdeckung trägt, aber es gibt keinen Moment mehr, in dem
jemand „nein" sagen kann. Erst einschalten, wenn `ci.yml` vor dem Merge
verlässlich läuft.

## Zwei Punkte, bevor es öffentlich wird

1. **Konten sind eingebaut, Bezahlung nicht.** Öffentlich erreichbar sind
   nur Startseite und Anmeldung; alles unter `/app` und `/api` verlangt ein
   freigeschaltetes Konto, und die Nutzdaten sind je Konto getrennt. Die
   frühere BasicAuth-Notlösung ist damit hinfällig. **Neue Registrierungen
   stehen auf „wartet"** und müssen unter `/app/verwaltung` von Hand
   freigeschaltet werden — ohne diesen Schritt kommt niemand hinein. Ein
   Bezahlweg ist nicht angebunden: Tarif und Guthaben setzt der Admin.
2. **Plausible und HTTPS.** Die Seite läuft über HTTPS (NPM terminiert
   es). Zeigt die Plausible-Adresse auf `http://…`, blockt der Browser das
   Skript als Mixed Content — sichtbar nur in der Konsole, die Zählung
   bleibt einfach leer. Plausible also ebenfalls über NPM mit eigener
   HTTPS-Domain veröffentlichen.

   Eingetragen wird die Adresse im **Adminbereich** unter
   `/app/verwaltung` → Zählung, nicht mehr im Stack. Ohne Eintrag wird gar
   kein Skript eingebunden. Die Stack-Variable `PLAUSIBLE_URL` gibt es
   weiterhin als Rückfall, damit ältere Stacks nicht plötzlich ohne
   Zählung dastehen.

## Lokal ausprobieren ohne Compose (nur docker run)

Die App braucht jetzt eine Datenbank, also zwei Container:

```bash
docker build -f deploy/Dockerfile -t rechnungsblatt .
docker network create rb-netz
docker run -d --name rb-db --network rb-netz \
  -e POSTGRES_USER=rechnungsblatt -e POSTGRES_PASSWORD=rechnungsblatt \
  -e POSTGRES_DB=rechnungsblatt postgres:16-alpine
docker run --rm --network rb-netz -p 8000:8000 \
  -v rechnungsblatt-daten:/daten \
  -e DATENBANK_URL=postgresql://rechnungsblatt:rechnungsblatt@rb-db:5432/rechnungsblatt \
  -e ADMIN_EMAIL=admin@rechnungsblatt.local -e ADMIN_PASSWORT=rechnungsblatt-admin \
  rechnungsblatt
# → http://localhost:8000
```

Einfacher ist der lokale Compose-Stack oben.

## Lizenzhinweis

Ghostscript (Normalisierung + Vorschau) ist **AGPL**. Für den internen
Betrieb unkritisch; vor einem kommerziellen Angebot die Artifex-Lizenzfrage
klären — offenes Risiko Nr. 1 der Übergabe.
