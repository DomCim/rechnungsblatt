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

Dann **http://localhost:8000** öffnen — Einrichtung durchklicken, Rechnung
erzeugen, PDF prüfen. Die Daten liegen im Volume
`rechnungsblatt-daten-lokal` und überleben Neustarts; komplett zurücksetzen
mit `docker compose -f deploy/docker-compose.local.yml down -v`.

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
   | `PLAUSIBLE_URL` | `http://192.168.178.129:8001` (Vorgabe) | Woher der Browser das Plausible-Skript lädt |
3. **Deploy the stack** — das Image wird aus `deploy/Dockerfile` gebaut
   (Python 3.12 + Ghostscript + Ersatzschriften, App als Nicht-Root).

Erzeugte Belege und die Einrichtung liegen im benannten Volume `daten`
(`/daten` im Container) — bei Stack-Updates bleibt alles erhalten.
Rechnungen sind 8 Jahre aufzubewahren: dieses Volume in die Server-Sicherung
aufnehmen.

## Zwei Punkte, bevor es öffentlich wird

1. **Kein Login eingebaut.** Die App ist bewusst Einzelmandant ohne Konto
   (Konten kommen laut MVP-Schnitt später). Hinter Traefik gehört deshalb
   ein Schutz davor — im Compose liegt ein auskommentiertes
   BasicAuth-Middleware-Beispiel (`htpasswd -nB benutzer`, `$` als `$$`
   maskieren). Ohne Schutz kann jeder Belege anlegen und lesen.
2. **Plausible und HTTPS.** Läuft die Seite über HTTPS (Traefik
   `websecure`), blockt der Browser das Skript von
   `http://192.168.178.129:8001` als Mixed Content. Dann Plausible ebenfalls
   über Traefik mit eigener HTTPS-Domain veröffentlichen und diese als
   `PLAUSIBLE_URL` setzen. Im reinen LAN-Betrieb über HTTP funktioniert die
   IP-Adresse direkt.

## Lokal ausprobieren ohne Compose (nur docker run)

```bash
docker build -f deploy/Dockerfile -t rechnungsblatt .
docker run --rm -p 8000:8000 -v rechnungsblatt-daten:/daten rechnungsblatt
# → http://localhost:8000
```

## Lizenzhinweis

Ghostscript (Normalisierung + Vorschau) ist **AGPL**. Für den internen
Betrieb unkritisch; vor einem kommerziellen Angebot die Artifex-Lizenzfrage
klären — offenes Risiko Nr. 1 der Übergabe.
