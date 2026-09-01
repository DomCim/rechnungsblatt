"""Die HTML-Seiten, das Manifest und was Suchmaschinen lesen.

Alles, was ein Browser direkt aufruft. Die Seiten sind handgeschriebenes
HTML ohne Build-Schritt; hier wird nur das Zählskript eingesetzt und die
Kontokennung mitgegeben, damit die Oberfläche nicht erst nachfragen muss.
"""

from __future__ import annotations

import json
import datetime as dt

from fastapi import APIRouter, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
)

from . import konten
from .basis import (
    wurzel_von,
    PLAUSIBLE_DOMAIN,
    PLAUSIBLE_URL,
    SEITEN,
    angemeldeter,
    oeffentliche_adresse,
)
from .ablage import ist_bereit
from .darstellung import nutzer_json

wege = APIRouter()


def seite(name: str) -> HTMLResponse:
    inhalt = (SEITEN / name).read_text(encoding="utf-8")
    schnipsel = ""
    # Zuerst die Verwaltung, dann die Umgebung: So lässt sich Plausible im
    # laufenden Betrieb ein- und ausschalten, ohne dass ein Stack ohne
    # Eintrag plötzlich ohne Zählung dasteht.
    try:
        werte = konten.einstellungen()
    except Exception:          # Datenbank noch nicht erreichbar
        werte = {}
    url = (werte.get("plausible_url") or PLAUSIBLE_URL).rstrip("/")
    domain = werte.get("plausible_domain") or PLAUSIBLE_DOMAIN
    if url and domain:
        schnipsel = (
            f'<script defer data-domain="{domain}" '
            f'src="{url}/js/script.js"></script>'
        )
    return HTMLResponse(inhalt.replace("<!--PLAUSIBLE-->", schnipsel))


@wege.get("/", response_class=HTMLResponse)
def startseite() -> HTMLResponse:
    return seite("start.html")


@wege.get("/app/anmelden", response_class=HTMLResponse)
def anmeldeseite() -> HTMLResponse:
    """Die Anmeldung — innerhalb des App-Bereichs.

    **Unter ``/app/``, weil der Scope im Manifest dort endet.** Alles
    darunter bleibt in der installierten App, alles darüber öffnet der
    Browser daneben — so verlässt „Öffentliche Seite" die App und kommt
    als eigenes Fenster. Läge die Anmeldung außerhalb, spränge die App
    bei jeder abgelaufenen Sitzung mit hinaus und käme nicht zurück.
    """
    return seite("anmelden.html")


@wege.get("/anmelden")
def anmelden_alt() -> RedirectResponse:
    """Alte Adresse — die Anmeldung liegt jetzt unter ``/app/anmelden``.

    Bleibt als Weiterleitung stehen: Lesezeichen und Verweise von außen
    sollen nicht ins Leere laufen.
    """
    return RedirectResponse("/app/anmelden", status_code=308)


@wege.get("/robots.txt")
def robots(anfrage: Request) -> Response:
    """Was Suchmaschinen sehen dürfen — und was nicht.

    Nur die öffentliche Seite gehört in den Index. Der Arbeitsbereich
    verlangt ohnehin eine Anmeldung; ein Crawler bekäme dort nur
    Weiterleitungen und würde Kontingent kosten. Die Anmeldeseite selbst
    hat als Suchtreffer keinen Wert.
    """
    basis = oeffentliche_adresse(anfrage)
    return Response(
        "User-agent: *\n"
        "Allow: /$\n"
        "Disallow: /app/\n"
        "Disallow: /api/\n"
        "Disallow: /anmelden\n"
        "Disallow: /passwort-neu\n"
        "Disallow: /seiten/\n"
        "\n"
        f"Sitemap: {basis}/sitemap.xml\n",
        media_type="text/plain; charset=utf-8",
    )


@wege.get("/sitemap.xml")
def sitemap(anfrage: Request) -> Response:
    """Eine einzige Seite — mehr ist öffentlich nicht zu holen.

    Die Sprachfassungen sind keine eigenen Adressen (der Umschalter
    tauscht nur Text im Browser), deshalb kein hreflang je URL.
    """
    basis = oeffentliche_adresse(anfrage)
    heute = dt.date.today().isoformat()
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{basis}/</loc>\n"
        f"    <lastmod>{heute}</lastmod>\n"
        "    <changefreq>monthly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "  </url>\n"
        "</urlset>\n",
        media_type="application/xml",
    )


@wege.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(
        SEITEN / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@wege.get("/sw.js")
def dienstarbeiter() -> FileResponse:
    return FileResponse(
        SEITEN / "sw.js",
        media_type="application/javascript",
        # Nie zwischenspeichern, sonst bleibt eine alte Fassung hängen und
        # die App aktualisiert sich nie wieder.
        headers={"Cache-Control": "no-cache"},
    )


@wege.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(SEITEN / "symbole" / "favicon.ico",
                        media_type="image/x-icon")


def seite_mit_konto(anfrage: Request, name: str) -> Response:
    """Liefert eine Arbeitsseite oder schickt zur Anmeldung bzw. zum Wartehinweis."""
    person = angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/app/anmelden", status_code=303)
    if not person.ist_frei:
        return seite("warten.html")
    return seite(name)


@wege.get("/app")
def arbeitsbereich(anfrage: Request) -> Response:
    """Landung nach der Anmeldung: Formular, sobald die Einrichtung steht."""
    person = angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/app/anmelden", status_code=303)
    if not person.ist_frei:
        return seite("warten.html")
    # Wer noch nicht eingerichtet ist, landet im Assistenten — nicht auf
    # der Einrichtungsseite. Die zeigt alle vier Schritte nebeneinander
    # und setzt voraus, dass man weiß, womit man anfängt.
    ziel = "/app/rechnung" if ist_bereit(wurzel_von(person)) else "/app/willkommen"
    return RedirectResponse(ziel, status_code=303)


@wege.get("/app/willkommen", response_class=HTMLResponse)
def willkommensassistent(anfrage: Request) -> Response:
    """Führt Schritt für Schritt durch die Einrichtung.

    Dieselben Endpunkte wie die Einrichtungsseite, nur einer nach dem
    anderen. Wer schon etwas gemacht hat, steigt beim ersten offenen
    Schritt ein — der Stand kommt vom Server, nicht aus dem Browser.
    """
    return seite_mit_konto(anfrage, "willkommen.html")


@wege.get("/app/einrichtung", response_class=HTMLResponse)
def einrichtungsseite(anfrage: Request) -> Response:
    return seite_mit_konto(anfrage, "einrichtung.html")


@wege.get("/app/rechnung", response_class=HTMLResponse)
def rechnungsformular(anfrage: Request) -> Response:
    return seite_mit_konto(anfrage, "rechnung.html")


@wege.get("/app/stamm", response_class=HTMLResponse)
def stammseite(anfrage: Request) -> Response:
    return seite_mit_konto(anfrage, "stamm.html")


@wege.get("/app/ablage", response_class=HTMLResponse)
def ablageseite(anfrage: Request) -> Response:
    return seite_mit_konto(anfrage, "ablage.html")


@wege.get("/app/konto", response_class=HTMLResponse)
def kontoseite(anfrage: Request) -> Response:
    person = angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/app/anmelden", status_code=303)
    return seite("konto.html")


@wege.get("/app/verwaltung", response_class=HTMLResponse)
def verwaltungsseite(anfrage: Request) -> Response:
    person = angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/app/anmelden", status_code=303)
    if not person.ist_admin:
        return RedirectResponse("/app", status_code=303)
    return seite("verwaltung.html")


@wege.get("/passwort-neu", response_class=HTMLResponse)
def passwort_neu_seite() -> HTMLResponse:
    """Bestätigungsseite des Rücksetz-Links.

    Der Link führt hierher, nicht direkt ins Konto: Ein Klick allein soll
    nichts verändern — Mail-Scanner und Vorschaufunktionen öffnen Links
    ungefragt. Erst die Eingabe auf dieser Seite setzt das Passwort.
    """
    return seite("passwort-neu.html")
