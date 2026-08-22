# Rechnungsblatt

E-Rechnungen (ZUGFeRD/Factur-X, XRechnung) auf dem **eigenen Briefpapier** —
für Selbstständige und Kleinbetriebe. Das Abrechnungsmodell ist noch offen
(siehe „Offene Risiken" Nr. 4); die Tarife liegen deshalb als Datensatz vor,
nicht im Code.

Kein KI-Auslesen bestehender PDFs: Die Rechnung entsteht aus strukturierten
Formulardaten, das Briefpapier ist reine Unterlage. Das Formular **erzwingt**
die Pflichtangaben nach § 14 UStG — das ist die bewusste Abgrenzung zum
Konverter-Markt (siehe `docs/uebergabe.md`, §9).

## Aufbau des Monorepos

```
kern/       rechnungsblatt-kern (Python): Datenmodell, §14-Prüfung, CII-XML,
            Normalisierung, Blatt-Rendering, PDF/A-3B-Zusammenbau
web/        rechnungsblatt-web (FastAPI): öffentliche Seite, Konten und
            Adminbereich (PostgreSQL), je Mandant Einrichtung,
            Schreibzonen-Editor, Rechnungsformular, Ablage — DE/EN
deploy/     Dockerfile + Portainer-Stack (Traefik im Netz "edge",
            PostgreSQL, Plausible)
scripts/    Referenzfälle erzeugen und gegen den Validator prüfen
validator/  Mustang-Validator-Wrapper für die CI
prototyp/   der unveränderte, validierte Prototyp aus dem Vorgespräch
docs/       Projektübergabe und Prototyp-Befund
```

## Der bewiesene Kern — Ablauf

```
Briefpapier-Upload (einmalig, beim Einrichten)
   └─> NORMALISIEREN (Ghostscript)   ← ohne diesen Schritt scheitert alles
   └─> Ampelprüfung
   └─> normalisierte Fassung speichern, Original verwerfen

Je Rechnung:
   Formulardaten
   ├─> §14-Prüfung (blockierend)
   ├─> Blatt rendern (reportlab, in die Schreibzone)
   ├─> CII-XML erzeugen (EN 16931)
   └─> Zusammenbau: normalisiertes Briefpapier + Blatt + XML + XMP
       └─> PDF/A-3B
```

Kernregel: PDF und XML entstehen aus denselben Daten im selben Vorgang.
Details und Begründung: `docs/uebergabe.md` (§3–§5) und
`docs/befund-pdfa3-briefpapier.md`.

## Entwicklung

```bash
# Voraussetzungen: Python ≥ 3.11, Ghostscript, Liberation-/DejaVu-Schriften
pip install -e "./kern[test]"
python -m pytest kern/tests

# Web-Schicht: braucht zusätzlich PostgreSQL, sonst überspringt sich die
# Konten- und Mandantenprüfung stillschweigend
pip install -e "./web[test]"
docker compose -f deploy/docker-compose.local.yml up -d datenbank
python -m pytest web/tests

# Referenzfälle erzeugen und validieren (braucht JDK + validator.jar,
# siehe validator/README.md):
python scripts/erzeuge_referenzfaelle.py referenzfaelle
python scripts/pruefe_referenzfaelle.py referenzfaelle --jar validator.jar --klasse .
```

## Branches und Veröffentlichen

`feature/…` → PR → `develop` → PR → `main`. Auf `main` und `develop` wird
nicht direkt committet. Ein Push auf `main` löst den Workflow
„Veröffentlichen" aus, der das Image nach `ghcr.io/domcim/rechnungsblatt`
schiebt; ausgerollt wird danach von Hand in Portainer. Einzelheiten in
[`CLAUDE.md`](CLAUDE.md) und [`deploy/README.md`](deploy/README.md).

Der CI-Workflow (`.github/workflows/ci.yml`) fährt beides — Kern-Tests und
vollständige Validierung aller Referenzfälle mit dem Mustang-Validator
(PDF/A-3B via veraPDF + EN-16931-/XRechnung-Schematron) — ist aber bewusst
**nur manuell startbar** (Actions → CI → „Run workflow"), um keine
Actions-Minuten zu verbrauchen. Getestet und validiert wird lokal vor jedem
Push. Stand der Referenzfälle: **alle gültig** — `isCompliant="true"`,
124 passedRules, 0 failedRules, XML `status valid` (identisch mit dem
Prototyp-Befund).

## Offene Risiken (vor Produktivbetrieb klären)

1. **Ghostscript ist AGPL** — kommerzielle Artifex-Lizenz klären, *bevor*
   die Web-Schicht gebaut wird. Höchste Priorität, blockierend
   (`docs/uebergabe.md`, §10).
2. Schriftersetzung sichtbar in die Vorschau (der Kern meldet sie bereits
   über `NormalisierungsErgebnis.schriften_ersetzt`).
3. Ungetestete Bogen-Sorten (Sonderfarben, eingebettete ICC-Profile) —
   der Ablehnungsweg existiert (`NormalisierungAbgelehnt`), die Liste der
   abgelehnten Fälle wird mit echten Bögen wachsen.
4. **Abrechnungsmodell offen.** Der Markt liegt laut Übergabe §9 bei null
   (easybill FREE, xrechnungs.de bis 50/Monat gratis) und Pay-per-Invoice ist
   mit RechneX zu 3,99 € besetzt; das Konzept in §1 grenzt sich ausdrücklich
   als „je Rechnung statt im Abo" ab. Die Tarifzeilen erlauben Monatsbeitrag,
   Inklusivmenge und Preis je Rechnung zugleich — entschieden ist damit
   nichts. Hängt an Nr. 1: Solange die Ghostscript-Lizenz offen ist, steht
   jede Kalkulation auf Sand.
5. Haftungsrahmen (AGB, „keine Steuerberatung", keine zertifizierte
   GoBD-Archivierung), Domain-/Markenprüfung vor Kauf.

## Nächste Schritte

- [x] Monorepo, Python-Kern als Paket
- [x] Datenmodell + §14-Prüfung mit Tests
- [x] CII-XML (EN 16931), XRechnung-3.0-Profil
- [x] Normalisierung + Zusammenbau portiert (aus `prototyp/`)
- [x] Validator in der CI mit Referenzfällen
- [x] Web-Schicht, erster Stand (FastAPI: Einrichtung mit Upload/Ampel/
      Zwei-Regler-Schreibzone, Rechnungsformular mit Befund-Anzeige,
      Ablage, Merkliste, Nummernkreis; DE/EN, eigenes Design)
- [x] Deployment: Dockerfile + Portainer-Stack (Traefik „edge", Plausible)
- [x] Gestaltung: kuratierte Schriften (Liberation, Carlito, Caladea,
      DejaVu), Schriftgrad, drei geprüfte Layoutvarianten mit
      Musterrechnungs-Vorschau — bewusst keine freie Positionierung
      (Produktentscheidung, siehe web/README.md)
- [x] Öffentliche Seite, die das Modell erklärt, mit Preistafel aus der
      Datenbank
- [x] Konten und Mandantentrennung (PostgreSQL): Registrierung mit
      Freischaltung durch den Admin, Sitzungen, Rollen, je Konto getrennte
      Daten unter `nutzer/<id>/`, Adminbereich für Freigabe, Tarif und
      Guthaben; Landung nach der Anmeldung ist das Rechnungsformular
- [ ] Artifex-Lizenzfrage klären (blockiert Produktivbetrieb, nicht die Entwicklung)
- [ ] Abrechnungsmodell entscheiden und einen Bezahlweg anbinden — bis dahin
      bucht der Admin Tarif und Guthaben von Hand
- [ ] Zehn echte Testrechnungen mit echten Briefbögen
