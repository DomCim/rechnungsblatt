# Veröffentlichen mit Portainer + Traefik

Zielbild: Docker-Stack in Portainer, Traefik im externen Netz `edge`,
Plausible-Analytics auf `192.168.178.129:8001`.

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
   - Repository-URL: dieses Repo, Branch wie gewünscht
   - Compose path: `deploy/docker-compose.yml`
2. **Environment variables** setzen:
   | Variable | Beispiel | Zweck |
   |---|---|---|
   | `RECHNUNGSBLATT_DOMAIN` | `rechnungsblatt.example.de` | Traefik-Host-Regel **und** Plausible-`data-domain` |
   | `DB_PASSWORT` | (lang und zufällig) | Passwort der PostgreSQL-Instanz im Stack |
   | `ADMIN_EMAIL` | `sie@example.de` | Anmeldung des ersten Admins |
   | `ADMIN_PASSWORT` | (mind. 10 Zeichen) | dessen Startpasswort — nach der ersten Anmeldung unter „Konto" ändern |
   | `PLAUSIBLE_URL` | `http://192.168.178.129:8001` (Vorgabe) | Woher der Browser das Plausible-Skript lädt |

   Die drei mittleren Variablen sind Pflicht; fehlt eine, verweigert der
   Stack den Start mit einer Meldung statt still ein Standardpasswort zu
   verwenden.

   **`DB_PASSWORT` nur aus Buchstaben und Ziffern wählen.** Es wird in die
   Verbindungs-URL `postgresql://…:PASSWORT@datenbank:5432/…` eingesetzt;
   ein `@`, `:`, `/`, `#` oder `%` darin zerlegt die URL und die App findet
   die Datenbank nicht mehr. Länge statt Sonderzeichen.
3. **Deploy the stack** — das Image wird aus `deploy/Dockerfile` gebaut
   (Python 3.12 + Ghostscript + Ersatzschriften, App als Nicht-Root).

Erzeugte Belege und die Einrichtung liegen im Volume `daten` (`/daten` im
Container), getrennt je Konto unter `nutzer/<id>/`; die Konten selbst im
Volume `db`. Bei Stack-Updates bleibt beides erhalten. Rechnungen sind 8
Jahre aufzubewahren: **beide** Volumes in die Server-Sicherung aufnehmen —
ohne die Datenbank lässt sich später nicht mehr zuordnen, wem welches
Verzeichnis gehört.

## Zwei Punkte, bevor es öffentlich wird

1. **Konten sind eingebaut, Bezahlung nicht.** Öffentlich erreichbar sind
   nur Startseite und Anmeldung; alles unter `/app` und `/api` verlangt ein
   freigeschaltetes Konto, und die Nutzdaten sind je Konto getrennt. Die
   frühere BasicAuth-Notlösung ist damit hinfällig. **Neue Registrierungen
   stehen auf „wartet"** und müssen unter `/app/verwaltung` von Hand
   freigeschaltet werden — ohne diesen Schritt kommt niemand hinein. Ein
   Bezahlweg ist nicht angebunden: Tarif und Guthaben setzt der Admin.
2. **Plausible und HTTPS.** Läuft die Seite über HTTPS (Traefik
   `websecure`), blockt der Browser das Skript von
   `http://192.168.178.129:8001` als Mixed Content. Dann Plausible ebenfalls
   über Traefik mit eigener HTTPS-Domain veröffentlichen und diese als
   `PLAUSIBLE_URL` setzen. Im reinen LAN-Betrieb über HTTP funktioniert die
   IP-Adresse direkt.

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
