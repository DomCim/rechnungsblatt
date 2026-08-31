"""FastAPI-App: öffentliche Seite, Konten und der Arbeitsbereich je Mandant.

Die App ist eine schmale Schicht: jede fachliche Entscheidung (Prüfung,
Rechnen, Rendern, Zusammenbau) trifft der Kern, alles rund um Konto, Rolle
und Kontingent die Kontenschicht. Hier gibt es nur Ablage, Übersetzung von
Formulardaten in das Kern-Modell und die Auslieferung der Seiten.

Aufbau der Pfade:

    /                    öffentliche Seite (erklärt das Modell, zeigt Tarife)
    /anmelden            Anmeldung und Registrierung
    /app/…               Arbeitsbereich, nur mit freigegebenem Konto
    /app/verwaltung      Adminbereich
    /api/…               JSON-Schnittstelle, mandantengebunden

Die Nutzdaten liegen je Konto getrennt unter DATEN/nutzer/<id>/ — ein
Mandant sieht nie das Verzeichnis eines anderen.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import re
import shutil
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from rechnungsblatt_kern import (
    Anschrift,
    Belegtyp,
    Blattgestaltung,
    BlattUeberlauf,
    Empfaenger,
    Layoutvariante,
    NormalisierungAbgelehnt,
    NormalisierungFehlgeschlagen,
    Position,
    Rechnung,
    Schreibzone,
    Schriftgrad,
    Stammdaten,
    Steuerkategorie,
    UngueltigeRechnung,
    Zeitraum,
    erzeuge_gestaltungsvorschau,
    erzeuge_rechnung,
    erzeuge_vorschau_png,
    erzeuge_xrechnung,
    normalisiere_briefpapier,
    verfuegbare_schriften,
)

from . import konten, post, tresor
from .konten import KontingentErschoepft, KontoFehler, Nutzer

DATEN = Path(os.environ.get("DATEN_VERZEICHNIS", "/daten"))
_WEB_WURZEL = Path(__file__).resolve().parents[2]  # …/web
SEITEN = Path(__file__).resolve().parent / "seiten"
ZONEN_EDITOR = _WEB_WURZEL / "zonen-editor"

PLAUSIBLE_URL = os.environ.get("PLAUSIBLE_URL", "").rstrip("/")
PLAUSIBLE_DOMAIN = os.environ.get("PLAUSIBLE_DOMAIN", "")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SITZUNG_COOKIE = "rb_sitzung"
# Nur für die lokale Entwicklung: den Sitzungsschlüssel auch aus einer
# Kopfzeile lesen. iOS leert bei Web-Apps über HTTP den Cookie-Speicher
# beim Schließen — im Portainer-Stack (HTTPS) ist das nicht nötig und
# bleibt deshalb aus.
SITZUNG_KOPFZEILE = os.environ.get("SITZUNG_KOPFZEILE", "") == "1"

protokoll = logging.getLogger("rechnungsblatt")

# Wiederherstellungscodes zwischen Registrierung und Bestätigung.
# Bewusst nur im Speicher: Der Code darf nirgends abgelegt werden, sonst
# wäre der ganze Aufwand umsonst. Startet der Dienst dazwischen neu, ist
# er weg — dann hilft „neuen Code erzeugen" im Konto.
_SPAETER: dict[int, str] = {}


@contextlib.asynccontextmanager
async def _lebenszyklus(app: FastAPI):
    """Schema anlegen und den Admin aus der Umgebung einrichten."""
    konten.richte_schema_ein()
    ergebnis = konten.lege_admin_an()
    if ergebnis is not None:
        person, erzeugtes_passwort = ergebnis
        if erzeugtes_passwort:
            protokoll.warning(
                "Admin %s angelegt. Einmaliges Passwort: %s — bitte nach der "
                "ersten Anmeldung ändern.",
                person.email,
                erzeugtes_passwort,
            )
        else:
            protokoll.info("Admin %s steht bereit.", person.email)
    yield
    konten.schliesse_pool()


app = FastAPI(
    title="Rechnungsblatt", docs_url=None, redoc_url=None, lifespan=_lebenszyklus
)


# ---------------------------------------------------------------- Anmeldung

def _angemeldeter(anfrage: Request) -> Nutzer | None:
    schluessel = anfrage.cookies.get(SITZUNG_COOKIE)
    if not schluessel and SITZUNG_KOPFZEILE:
        # Ersatzweg, wenn der Browser das Cookie verworfen hat.
        schluessel = anfrage.headers.get("X-Rb-Sitzung")
    return konten.nutzer_zu_sitzung(schluessel)


def angemeldet(anfrage: Request) -> Nutzer:
    """Abhängigkeit für JSON-Endpunkte: 401, wenn keine gültige Sitzung."""
    person = _angemeldeter(anfrage)
    if person is None:
        raise HTTPException(401, detail={"grund": "Bitte zuerst anmelden."})
    return person


def freigegeben(person: Nutzer = Depends(angemeldet)) -> Nutzer:
    """Wie `angemeldet`, verlangt aber ein freigeschaltetes Konto."""
    if person.status == konten.STATUS_WARTET:
        raise HTTPException(
            403,
            detail={
                "code": "wartet_auf_freigabe",
                "grund": "Ihr Konto wartet noch auf die Freigabe.",
            },
        )
    if person.status == konten.STATUS_GESPERRT:
        raise HTTPException(
            403, detail={"code": "gesperrt", "grund": "Ihr Konto ist gesperrt."}
        )
    return person


def verwalter(person: Nutzer = Depends(angemeldet)) -> Nutzer:
    if not person.ist_admin:
        raise HTTPException(403, detail={"grund": "Dieser Bereich ist Admins vorbehalten."})
    return person


def _wurzel(person: Nutzer) -> Path:
    """Datenverzeichnis eines Mandanten."""
    return DATEN / "nutzer" / str(person.id)


def mandant(anfrage: Request, person: Nutzer = Depends(freigegeben)) -> Path:
    """Datenverzeichnis des Mandanten — und sein Schlüssel für diese Anfrage.

    Der Datenschlüssel liegt verpackt in der Sitzung und lässt sich nur
    mit dem Sitzungsschlüssel aus dem Cookie öffnen. Er wandert in eine
    Kontextvariable, aus der `_lies_datei` und `_schreibe_datei` ihn holen
    — sonst müsste er durch jede Hilfsfunktion durchgereicht werden.
    """
    wurzel = Mandantenpfad(_wurzel(person))
    wurzel.mkdir(parents=True, exist_ok=True)
    sitzung = anfrage.cookies.get(SITZUNG_COOKIE)
    if not sitzung and SITZUNG_KOPFZEILE:
        sitzung = anfrage.headers.get("X-Rb-Sitzung")
    wurzel.schluessel = konten.datenschluessel_der_sitzung(sitzung)
    return wurzel


def _setze_sitzungscookie(antwort: Response, schluessel: str, anfrage: Request) -> None:
    antwort.set_cookie(
        SITZUNG_COOKIE,
        schluessel,
        max_age=konten.SITZUNG_TAGE * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=anfrage.url.scheme == "https",
        path="/",
    )


# ---------------------------------------------------------------- Seiten

def _seite(name: str) -> HTMLResponse:
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


@app.get("/", response_class=HTMLResponse)
def startseite() -> HTMLResponse:
    return _seite("start.html")


@app.get("/anmelden", response_class=HTMLResponse)
def anmeldeseite() -> HTMLResponse:
    return _seite("anmelden.html")


# ---------------------------------------------------------------- App-Hülle
# Damit die Seite als App installiert werden kann. Der Service Worker muss
# von der Wurzel kommen: sein Geltungsbereich ist sonst auf /seiten/
# begrenzt und die Navigation unter /app/… liefe daran vorbei.

# ---------------------------------------------------------------- Suchmaschinen

def _oeffentliche_adresse(anfrage: Request) -> str:
    """Die Adresse, unter der die Seite von außen erreichbar ist.

    Steht im Adminbereich; ohne Eintrag fällt sie auf die Adresse zurück,
    über die die Anfrage kam. Hinter einem Reverse Proxy kann das die
    interne sein — deshalb ist der Eintrag dort die verlässlichere Quelle.
    """
    try:
        gesetzt = konten.einstellungen().get("oeffentliche_adresse", "")
    except Exception:
        gesetzt = ""
    return (gesetzt or str(anfrage.base_url)).rstrip("/")


@app.get("/robots.txt")
def robots(anfrage: Request) -> Response:
    """Was Suchmaschinen sehen dürfen — und was nicht.

    Nur die öffentliche Seite gehört in den Index. Der Arbeitsbereich
    verlangt ohnehin eine Anmeldung; ein Crawler bekäme dort nur
    Weiterleitungen und würde Kontingent kosten. Die Anmeldeseite selbst
    hat als Suchtreffer keinen Wert.
    """
    basis = _oeffentliche_adresse(anfrage)
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


@app.get("/sitemap.xml")
def sitemap(anfrage: Request) -> Response:
    """Eine einzige Seite — mehr ist öffentlich nicht zu holen.

    Die Sprachfassungen sind keine eigenen Adressen (der Umschalter
    tauscht nur Text im Browser), deshalb kein hreflang je URL.
    """
    basis = _oeffentliche_adresse(anfrage)
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


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(
        SEITEN / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
def dienstarbeiter() -> FileResponse:
    return FileResponse(
        SEITEN / "sw.js",
        media_type="application/javascript",
        # Nie zwischenspeichern, sonst bleibt eine alte Fassung hängen und
        # die App aktualisiert sich nie wieder.
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(SEITEN / "symbole" / "favicon.ico",
                        media_type="image/x-icon")


def _seite_mit_konto(anfrage: Request, name: str) -> Response:
    """Liefert eine Arbeitsseite oder schickt zur Anmeldung bzw. zum Wartehinweis."""
    person = _angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/anmelden", status_code=303)
    if not person.ist_frei:
        return _seite("warten.html")
    return _seite(name)


@app.get("/app")
def arbeitsbereich(anfrage: Request) -> Response:
    """Landung nach der Anmeldung: Formular, sobald die Einrichtung steht."""
    person = _angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/anmelden", status_code=303)
    if not person.ist_frei:
        return _seite("warten.html")
    ziel = "/app/rechnung" if _ist_bereit(_wurzel(person)) else "/app/einrichtung"
    return RedirectResponse(ziel, status_code=303)


@app.get("/app/einrichtung", response_class=HTMLResponse)
def einrichtungsseite(anfrage: Request) -> Response:
    return _seite_mit_konto(anfrage, "einrichtung.html")


@app.get("/app/rechnung", response_class=HTMLResponse)
def rechnungsformular(anfrage: Request) -> Response:
    return _seite_mit_konto(anfrage, "rechnung.html")


@app.get("/app/stamm", response_class=HTMLResponse)
def stammseite(anfrage: Request) -> Response:
    return _seite_mit_konto(anfrage, "stamm.html")


@app.get("/app/ablage", response_class=HTMLResponse)
def ablageseite(anfrage: Request) -> Response:
    return _seite_mit_konto(anfrage, "ablage.html")


@app.get("/app/konto", response_class=HTMLResponse)
def kontoseite(anfrage: Request) -> Response:
    person = _angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/anmelden", status_code=303)
    return _seite("konto.html")


@app.get("/app/verwaltung", response_class=HTMLResponse)
def verwaltungsseite(anfrage: Request) -> Response:
    person = _angemeldeter(anfrage)
    if person is None:
        return RedirectResponse("/anmelden", status_code=303)
    if not person.ist_admin:
        return RedirectResponse("/app", status_code=303)
    return _seite("verwaltung.html")


app.mount("/zonen-editor", StaticFiles(directory=str(ZONEN_EDITOR), html=True), name="editor")
app.mount("/seiten", StaticFiles(directory=str(SEITEN)), name="seiten")


# ---------------------------------------------------------------- Konten-API

def _nutzer_json(person: Nutzer) -> dict:
    kontingent = konten.kontingent(person)
    return {
        "id": person.id,
        "email": person.email,
        "rolle": person.rolle,
        "status": person.status,
        "passwort_wechseln": person.passwort_wechseln,
        "tarif": {
            "schluessel": kontingent.tarif.schluessel,
            "name": kontingent.tarif.name,
            "inklusiv_rechnungen": kontingent.inklusiv,
            "preis_je_rechnung_cent": kontingent.tarif.preis_je_rechnung_cent,
            "monatsbeitrag_cent": kontingent.tarif.monatsbeitrag_cent,
        },
        "verbraucht_monat": kontingent.verbraucht,
        "frei_uebrig": kontingent.frei_uebrig,
        "guthaben_cent": person.guthaben_cent,
        "naechste_kostet_cent": kontingent.naechste_kostet_cent,
        "darf_erzeugen": kontingent.darf_erzeugen,
    }


def _tarif_json(tarif: konten.Tarif) -> dict:
    return {
        "schluessel": tarif.schluessel,
        "name": tarif.name,
        "beschreibung": tarif.beschreibung,
        "monatsbeitrag_cent": tarif.monatsbeitrag_cent,
        "inklusiv_rechnungen": tarif.inklusiv_rechnungen,
        "preis_je_rechnung_cent": tarif.preis_je_rechnung_cent,
        "reihenfolge": tarif.reihenfolge,
        "sichtbar": tarif.sichtbar,
        "hervorheben": tarif.hervorheben,
    }


@app.get("/api/gesundheit")
def gesundheit() -> dict:
    """Für den Healthcheck: erreichbar ohne Konto, prüft aber die Datenbank."""
    try:
        with konten.verbindung() as verbindung:
            verbindung.execute("SELECT 1")
    except Exception as fehler:  # psycopg wirft je nach Ursache Verschiedenes
        raise HTTPException(
            503, detail={"grund": f"Datenbank nicht erreichbar: {fehler}"}
        ) from fehler
    return {"zustand": "gut"}


@app.get("/api/tarife")
def oeffentliche_tarife() -> list[dict]:
    """Die öffentliche Seite rendert ihre Preistafel hieraus."""
    return [_tarif_json(tarif) for tarif in konten.tarife(nur_sichtbare=True)]


@app.post("/api/registrieren")
def registrieren(daten: dict) -> JSONResponse:
    try:
        person, code = konten.registriere(
            daten.get("email", ""), daten.get("passwort", "")
        )
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    # Der Wiederherstellungscode wird NICHT sofort gezeigt: erst muss die
    # Adresse bestätigt sein. So steht er später allein auf der Seite,
    # statt neben einem Eingabefeld unterzugehen — und er erreicht nur
    # jemanden, der das Postfach wirklich hat.
    _SPAETER[person.id] = code
    nachweis = konten.lege_nachweis_an(person.id, konten.ZWECK_EMAIL)
    try:
        verschickt = post.sende_bestaetigungscode(person.email, nachweis)
    except post.PostFehler:
        # Konto steht, nur der Versand klemmt. Den Code kann der Kunde
        # neu anfordern; ein Rückbau der Registrierung hülfe niemandem.
        verschickt = False
    return JSONResponse(
        {"status": person.status, "email": person.email,
         "bestaetigung_noetig": True, "mail_verschickt": verschickt},
        status_code=201,
    )


@app.post("/api/email/bestaetigen")
def email_bestaetigen(daten: dict) -> JSONResponse:
    """Sechsstelligen Code einlösen und den Wiederherstellungscode zeigen."""
    person = konten.nutzer_zu_email(daten.get("email", ""))
    if person is None:
        raise HTTPException(422, detail={"grund": "Der Code stimmt nicht."})
    try:
        nutzer_id = konten.loese_nachweis_ein(
            str(daten.get("code", "")).strip(), konten.ZWECK_EMAIL
        )
    except KontoFehler as fehler:
        konten.zaehle_fehlversuch(person.id, konten.ZWECK_EMAIL)
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    konten.bestaetige_email(nutzer_id)
    # Jetzt, und nur jetzt, bekommt der Kunde seinen Wiederherstellungscode
    # zu sehen. Er steht nirgends in der Datenbank — nur seine Hülle.
    return JSONResponse({
        "bestaetigt": True,
        "wiederherstellungscode": _SPAETER.pop(nutzer_id, None),
    })


@app.post("/api/email/code-neu")
def email_code_neu(daten: dict) -> JSONResponse:
    """Neuen Bestätigungscode anfordern.

    Antwortet immer gleich — ob es die Adresse gibt, geht niemanden etwas
    an, der sie nicht ohnehin kennt.
    """
    person = konten.nutzer_zu_email(daten.get("email", ""))
    if person is not None and not person.ist_bestaetigt:
        nachweis = konten.lege_nachweis_an(person.id, konten.ZWECK_EMAIL)
        with contextlib.suppress(post.PostFehler):
            post.sende_bestaetigungscode(person.email, nachweis)
    return JSONResponse({"verschickt": True})


@app.post("/api/passwort/vergessen")
def passwort_vergessen(daten: dict, anfrage: Request) -> JSONResponse:
    """Schickt den Rücksetz-Link.

    Antwortet immer gleich, egal ob es die Adresse gibt: Sonst ließe sich
    hier abfragen, wer Kunde ist.
    """
    person = konten.nutzer_zu_email(daten.get("email", ""))
    if person is not None:
        marke = konten.lege_nachweis_an(person.id, konten.ZWECK_RUECKSETZEN)
        basis = konten.einstellungen().get("oeffentliche_adresse", "").rstrip("/")
        if not basis:
            # Fällt auf die Adresse zurück, über die die Anfrage kam.
            basis = str(anfrage.base_url).rstrip("/")
        with contextlib.suppress(post.PostFehler):
            post.sende_ruecksetzlink(person.email, f"{basis}/passwort-neu?marke={marke}")
    return JSONResponse({"verschickt": True})


@app.get("/passwort-neu", response_class=HTMLResponse)
def passwort_neu_seite() -> HTMLResponse:
    """Bestätigungsseite des Rücksetz-Links.

    Der Link führt hierher, nicht direkt ins Konto: Ein Klick allein soll
    nichts verändern — Mail-Scanner und Vorschaufunktionen öffnen Links
    ungefragt. Erst die Eingabe auf dieser Seite setzt das Passwort.
    """
    return _seite("passwort-neu.html")


@app.post("/api/passwort/neu")
def passwort_neu(daten: dict) -> JSONResponse:
    """Löst den Rücksetz-Nachweis ein und setzt das neue Passwort.

    **Die Daten bleiben dabei verschlüsselt.** Ein neues Passwort öffnet
    die alte Hülle nicht — dafür gibt es den Wiederherstellungscode. Wird
    er mitgeschickt, wandert der Datenschlüssel in die neue Hülle und die
    Belege bleiben lesbar; ohne ihn bekommt der Kunde nur den Zugang
    zurück. Die Oberfläche muss das deutlich sagen.
    """
    marke = str(daten.get("marke", "")).strip()
    neues = str(daten.get("passwort", ""))
    code = str(daten.get("wiederherstellungscode", "")).strip()
    try:
        nutzer_id = konten.loese_nachweis_ein(marke, konten.ZWECK_RUECKSETZEN)
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    person = konten.nutzer(nutzer_id)
    if person is None:
        raise HTTPException(422, detail={"grund": "Konto nicht gefunden."})

    if code:
        try:
            konten.stelle_mit_code_wieder_her(person.email, code, neues)
            return JSONResponse({"gesetzt": True, "daten_erhalten": True})
        except KontoFehler as fehler:
            raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    try:
        konten.setze_passwort(nutzer_id, neues)
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    # Die alte Hülle passt nun nicht mehr — die vorhandenen Belege sind
    # ohne Wiederherstellungscode nicht mehr zu öffnen. Ehrlich melden.
    return JSONResponse({"gesetzt": True, "daten_erhalten": False})


@app.post("/api/anmelden")
def anmelden(daten: dict, anfrage: Request) -> JSONResponse:
    passwort = daten.get("passwort", "")
    try:
        person, datenschluessel = konten.pruefe_anmeldung(
            daten.get("email", ""), passwort
        )
    except KontoFehler as fehler:
        raise HTTPException(401, detail={"grund": str(fehler)}) from fehler
    if person.status == konten.STATUS_GESPERRT:
        raise HTTPException(403, detail={"grund": "Ihr Konto ist gesperrt."})
    if not person.ist_bestaetigt:
        # Ohne bestätigte Adresse keine Sitzung — sonst wäre die
        # Bestätigung eine Empfehlung statt einer Bedingung. Bestandskonten
        # von vor dieser Änderung gelten als bestätigt (siehe Migration).
        raise HTTPException(
            403,
            detail={
                "code": "email_offen",
                "grund": "Bitte bestätigen Sie zuerst Ihre E-Mail-Adresse.",
            },
        )
    if datenschluessel is None:
        # Konto aus der Zeit vor der Verschlüsselung (oder der Startadmin,
        # der ohne Registrierung entsteht): Hülle jetzt nachlegen, solange
        # das Passwort vorliegt. Vorhandene Klartextdateien bleiben lesbar
        # und werden beim nächsten Schreiben umgestellt.
        datenschluessel = konten.lege_huellen_an(person.id, passwort)
    schluessel = konten.starte_sitzung(person.id, datenschluessel)
    nutzdaten = _nutzer_json(person)
    if SITZUNG_KOPFZEILE:
        # Nur lokal: die Seite legt den Schlüssel ab und reicht ihn nach,
        # falls iOS das Cookie verworfen hat.
        nutzdaten["sitzung"] = schluessel
    antwort = JSONResponse(nutzdaten)
    _setze_sitzungscookie(antwort, schluessel, anfrage)
    return antwort


@app.post("/api/abmelden")
def abmelden(anfrage: Request) -> JSONResponse:
    schluessel = anfrage.cookies.get(SITZUNG_COOKIE)
    if not schluessel and SITZUNG_KOPFZEILE:
        schluessel = anfrage.headers.get("X-Rb-Sitzung")
    konten.beende_sitzung(schluessel)
    antwort = JSONResponse({"abgemeldet": True})
    antwort.delete_cookie(SITZUNG_COOKIE, path="/")
    return antwort


@app.get("/api/ich")
def ich(person: Nutzer = Depends(angemeldet)) -> dict:
    return _nutzer_json(person)


@app.post("/api/ich/passwort")
def passwort_wechseln(daten: dict, person: Nutzer = Depends(angemeldet)) -> dict:
    try:
        konten.wechsle_passwort(
            person.id, daten.get("alt", ""), daten.get("neu", "")
        )
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    return {"gewechselt": True}


@app.get("/api/ich/verbrauch")
def eigener_verbrauch(person: Nutzer = Depends(angemeldet)) -> list[dict]:
    return [
        {
            "nummer": zeile["nummer"],
            "kosten_cent": zeile["kosten_cent"],
            "zeitpunkt": zeile["zeitpunkt"].isoformat(timespec="seconds"),
        }
        for zeile in konten.verbrauch_liste(person.id)
    ]


# ---------------------------------------------------------------- Verwaltung

@app.get("/api/verwaltung/nutzer")
def verwaltung_nutzer(_: Nutzer = Depends(verwalter)) -> list[dict]:
    return [
        {
            "id": person.id,
            "email": person.email,
            "rolle": person.rolle,
            "status": person.status,
            "tarif": person.tarif,
            "guthaben_cent": person.guthaben_cent,
            "angelegt": person.angelegt.isoformat(timespec="seconds"),
            "zuletzt_angemeldet": (
                person.zuletzt_angemeldet.isoformat(timespec="seconds")
                if person.zuletzt_angemeldet
                else None
            ),
            "verbraucht_monat": konten.verbrauch_monat(person.id),
        }
        for person in konten.nutzer_liste()
    ]


def _verwaltung_aendern(aufruf) -> dict:
    try:
        person = aufruf()
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    return {
        "id": person.id,
        "email": person.email,
        "rolle": person.rolle,
        "status": person.status,
        "tarif": person.tarif,
        "guthaben_cent": person.guthaben_cent,
    }


@app.post("/api/verwaltung/nutzer/{nutzer_id}/status")
def verwaltung_status(
    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)
) -> dict:
    return _verwaltung_aendern(
        lambda: konten.setze_status(nutzer_id, daten.get("status", ""))
    )


@app.post("/api/verwaltung/nutzer/{nutzer_id}/rolle")
def verwaltung_rolle(
    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)
) -> dict:
    return _verwaltung_aendern(
        lambda: konten.setze_rolle(nutzer_id, daten.get("rolle", ""))
    )


@app.post("/api/verwaltung/nutzer/{nutzer_id}/tarif")
def verwaltung_tarif(
    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)
) -> dict:
    return _verwaltung_aendern(
        lambda: konten.setze_tarif(nutzer_id, daten.get("tarif", ""))
    )


@app.post("/api/verwaltung/nutzer/{nutzer_id}/guthaben")
def verwaltung_guthaben(
    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)
) -> dict:
    try:
        cent = int(daten.get("cent", 0))
    except (TypeError, ValueError) as fehler:
        raise HTTPException(422, detail={"grund": "Betrag muss ganzzahlig sein."}) from fehler
    return _verwaltung_aendern(lambda: konten.buche_guthaben(nutzer_id, cent))


@app.delete("/api/verwaltung/nutzer/{nutzer_id}")
def verwaltung_loeschen(nutzer_id: int, _: Nutzer = Depends(verwalter)) -> dict:
    """Konto und Nutzdaten entfernen — beides, nicht nur der Datenbankeintrag.

    Bis hierher blieb ``DATEN/nutzer/<id>/`` nach dem Löschen vollständig
    liegen: Rechnungen, Briefpapier, Kundenadressen. Zwei Folgen, beide
    schlecht — die Daten eines gelöschten Kunden lagen weiter auf der
    Platte, und eine spätere Nutzer-ID konnte dasselbe Verzeichnis erben
    und damit fremde Belege sehen.

    Reihenfolge: erst die Dateien, dann die Zeile. Scheitert das Löschen
    der Dateien, bleibt das Konto bestehen und der Vorgang lässt sich
    wiederholen — andersherum gäbe es ein Verzeichnis ohne Besitzer.
    """
    verzeichnis = DATEN / "nutzer" / str(nutzer_id)
    # Pfad absichern: nutzer_id kommt aus der URL. FastAPI erzwingt zwar
    # int, aber der Check kostet nichts und hält auch künftige Umbauten
    # davon ab, hier versehentlich außerhalb von DATEN zu löschen.
    erwartet = (DATEN / "nutzer").resolve()
    if verzeichnis.exists() and verzeichnis.resolve().parent != erwartet:
        raise HTTPException(422, detail={"grund": "Ungültiges Datenverzeichnis."})
    if verzeichnis.exists():
        try:
            shutil.rmtree(verzeichnis)
        except OSError as fehler:
            protokoll.exception("Datenverzeichnis von %s nicht gelöscht", nutzer_id)
            raise HTTPException(
                500,
                detail={
                    "grund": "Die Nutzdaten ließen sich nicht löschen; das Konto "
                    "bleibt bestehen. Bitte erneut versuchen."
                },
            ) from fehler
    try:
        konten.loesche_nutzer(nutzer_id)
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    return {"geloescht": nutzer_id}


@app.get("/api/verwaltung/dubletten")
def verwaltung_dubletten(_: Nutzer = Depends(verwalter)) -> list[dict]:
    """Konten, die sich ein Steuermerkmal teilen.

    Nur eine Meldung — wer hier auftaucht, ist nicht zwingend ein
    Missbrauchsfall: Betriebsübergaben und Steuernummernwechsel sehen
    genauso aus.
    """
    return konten.konten_mit_gleichem_steuermerkmal()


@app.get("/api/verwaltung/zahlen")
def verwaltung_zahlen(_: Nutzer = Depends(verwalter)) -> dict:
    """Konten und Belege in Zahlen. Plausible zählt daneben die Aufrufe."""
    return konten.betriebszahlen()


@app.get("/api/verwaltung/einstellungen")
def verwaltung_einstellungen(_: Nutzer = Depends(verwalter)) -> dict:
    """Betriebseinstellungen. Das SMTP-Passwort kommt NUR als Punkte zurück."""
    werte = konten.einstellungen()
    werte["eingerichtet"] = post.ist_eingerichtet()
    return werte


@app.put("/api/verwaltung/einstellungen")
def verwaltung_einstellungen_setzen(
    daten: dict, _: Nutzer = Depends(verwalter)
) -> dict:
    konten.setze_einstellungen({k: str(v) for k, v in daten.items()})
    werte = konten.einstellungen()
    werte["eingerichtet"] = post.ist_eingerichtet()
    return werte


@app.post("/api/verwaltung/testmail")
def verwaltung_testmail(daten: dict, person: Nutzer = Depends(verwalter)) -> dict:
    """Probenachricht an den Admin — der einzige Weg, den Zugang zu prüfen."""
    ziel = str(daten.get("an", "")).strip() or person.email
    try:
        verschickt = post.sende(
            ziel,
            "Testnachricht von Rechnungsblatt",
            "Der Postausgang ist richtig eingerichtet.\n\nRechnungsblatt\n",
        )
    except post.PostFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    if not verschickt:
        raise HTTPException(
            422, detail={"grund": "Kein SMTP eingerichtet — nichts verschickt."}
        )
    return {"verschickt": True, "an": ziel}


@app.get("/api/verwaltung/tarife")
def verwaltung_tarife(_: Nutzer = Depends(verwalter)) -> list[dict]:
    return [_tarif_json(tarif) for tarif in konten.tarife()]


@app.put("/api/verwaltung/tarife/{schluessel}")
def verwaltung_tarif_speichern(
    schluessel: str, daten: dict, _: Nutzer = Depends(verwalter)
) -> dict:
    inklusiv = daten.get("inklusiv_rechnungen")
    try:
        neu = konten.Tarif(
            schluessel=schluessel,
            name=str(daten.get("name", "")).strip() or schluessel,
            beschreibung=str(daten.get("beschreibung", "")),
            monatsbeitrag_cent=int(daten.get("monatsbeitrag_cent", 0)),
            inklusiv_rechnungen=None if inklusiv in (None, "") else int(inklusiv),
            preis_je_rechnung_cent=int(daten.get("preis_je_rechnung_cent", 0)),
            reihenfolge=int(daten.get("reihenfolge", 0)),
            sichtbar=bool(daten.get("sichtbar", True)),
            hervorheben=bool(daten.get("hervorheben", False)),
        )
    except (TypeError, ValueError) as fehler:
        raise HTTPException(422, detail={"grund": f"Ungültiger Tarif: {fehler}"}) from fehler
    return _tarif_json(konten.speichere_tarif(neu))


# ---------------------------------------------------------------- Ablage

# --- Verschlüsselte Ablage --------------------------------------------
#
# Die Nutzdaten liegen verschlüsselt auf der Platte; der Schlüssel kommt
# aus der Sitzung (siehe `tresor`). Ohne Schlüssel wird im Klartext
# gelesen und geschrieben — das betrifft nur Konten aus der Zeit davor und
# die Tests.
#
# Der Schlüssel hängt am Mandantenverzeichnis, nicht an einer
# Kontextvariablen: FastAPI führt synchrone Endpunkte in einem Threadpool
# aus, und eine in `mandant` gesetzte ContextVar erreicht den Endpunkt
# dort nicht. `mandant` liefert ohnehin genau dieses Pfadobjekt an jeden
# Endpunkt — der Schlüssel reist damit mit, ohne durch jede
# Hilfsfunktion gereicht zu werden.
class Mandantenpfad(Path):
    """Pfad des Mandantenverzeichnisses samt seinem Datenschlüssel."""

    _flavour = type(Path())._flavour        # von pathlib verlangt
    schluessel: bytes | None = None

    def _make_child_relpath(self, name):    # noqa: N802 (pathlib-Vorgabe)
        kind = super()._make_child_relpath(name)
        kind.schluessel = self.schluessel
        return kind

    def __truediv__(self, andere):
        kind = super().__truediv__(andere)
        if isinstance(kind, Mandantenpfad):
            kind.schluessel = self.schluessel
        return kind


def _schluessel_zu(pfad: Path) -> bytes | None:
    """Findet den Schlüssel zu einem Pfad innerhalb des Mandantenordners."""
    if isinstance(pfad, Mandantenpfad):
        return pfad.schluessel
    for eltern in pfad.parents:
        if isinstance(eltern, Mandantenpfad):
            return eltern.schluessel
    return None


def _lies_datei(pfad: Path, schluessel: bytes | None = None) -> bytes:
    """Rohbytes einer Mandantendatei, entschlüsselt wenn nötig."""
    inhalt = pfad.read_bytes()
    if schluessel is None:
        schluessel = _schluessel_zu(pfad)
    if schluessel is None:
        if tresor.ist_verschluesselt(inhalt):
            raise HTTPException(
                409,
                detail={
                    "code": "kein_schluessel",
                    "grund": "Die Daten sind verschlüsselt, aber diese Sitzung "
                    "trägt keinen Schlüssel. Bitte neu anmelden.",
                },
            )
        return inhalt
    try:
        return tresor.entschluessle(inhalt, schluessel)
    except tresor.TresorFehler as fehler:
        raise HTTPException(
            409,
            detail={"code": "schluessel_passt_nicht",
                    "grund": "Diese Datei lässt sich nicht entschlüsseln."},
        ) from fehler


def _schreibe_datei(pfad: Path, inhalt: bytes,
                   schluessel: bytes | None = None) -> None:
    """Schreibt eine Mandantendatei, verschlüsselt wenn ein Schlüssel da ist."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    if schluessel is None:
        schluessel = _schluessel_zu(pfad)
    if schluessel is not None:
        inhalt = tresor.verschluessle(inhalt, schluessel)
    pfad.write_bytes(inhalt)


def _lese_json(pfad: Path) -> dict | None:
    if not pfad.exists():
        return None
    return json.loads(_lies_datei(pfad).decode("utf-8"))


def _schreibe_json(pfad: Path, daten: dict) -> None:
    _schreibe_datei(
        pfad, json.dumps(daten, ensure_ascii=False, indent=2).encode("utf-8")
    )


@contextlib.contextmanager
def _im_klartext(pfad: Path):
    """Stellt eine Mandantendatei kurz entschlüsselt bereit.

    Der Kern nimmt Pfade, keine Bytes — er öffnet das Briefpapier selbst.
    Ein Schlüssel ist ihm fremd und soll es bleiben: Verschlüsselung ist
    Sache der Web-Schicht (``docs/uebergabe.md`` §2).

    Die Kopie liegt in einem Temporärverzeichnis **innerhalb** des
    Mandantenordners und verschwindet mit dem Block — auch bei einer
    Ausnahme. Nicht in /tmp: dort läge Klartext außerhalb des Volumes.
    """
    if not pfad.exists():
        yield pfad
        return
    inhalt = _lies_datei(pfad)
    with tempfile.TemporaryDirectory(dir=pfad.parent) as arbeit:
        klar = Path(arbeit) / pfad.name
        klar.write_bytes(inhalt)
        yield klar


def _briefpapier_pfad(wurzel: Path) -> Path:
    return wurzel / "briefpapier_norm.pdf"


def _vorschau_pfad(wurzel: Path) -> Path:
    return wurzel / "briefpapier_vorschau.png"


def _ist_bereit(wurzel: Path) -> bool:
    return bool(
        _lese_json(wurzel / "briefpapier.json")
        and _lese_json(wurzel / "schreibzone.json")
        and _lese_json(wurzel / "stammdaten.json")
    )


# ---------------------------------------------------------------- Status

@app.get("/api/status")
def status(
    person: Nutzer = Depends(freigegeben), wurzel: Path = Depends(mandant)
) -> dict:
    zone = _lese_json(wurzel / "schreibzone.json")
    briefpapier = _lese_json(wurzel / "briefpapier.json")
    return {
        "briefpapier": briefpapier,
        "schreibzone": zone,
        "stammdaten": _lese_json(wurzel / "stammdaten.json"),
        "gestaltung": _lese_json(wurzel / "gestaltung.json"),
        "bereit": bool(briefpapier and zone and _lese_json(wurzel / "stammdaten.json")),
        "konto": _nutzer_json(person),
    }


# ---------------------------------------------------------------- Briefpapier

_WORD_ENDUNGEN = (".doc", ".docx", ".odt", ".rtf")
_PDF_ANLEITUNG = (
    "Bitte einmal als PDF speichern und die PDF hochladen: in Word "
    "„Datei → Speichern unter → Dateityp: PDF“ (oder „Datei → Exportieren → "
    "PDF/XPS-Dokument erstellen“), in LibreOffice „Datei → Als PDF exportieren“."
)


@app.post("/api/briefpapier")
async def briefpapier_hochladen(
    datei: UploadFile, wurzel: Path = Depends(mandant)
) -> dict:
    inhalt = await datei.read()
    if len(inhalt) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail={"grund": "Datei größer als 20 MB."})
    name = (datei.filename or "").lower()
    if name.endswith(_WORD_ENDUNGEN):
        raise HTTPException(
            422,
            detail={
                "code": "word_datei",
                "grund": "Das ist eine Word-/Textverarbeitungs-Datei. " + _PDF_ANLEITUNG,
            },
        )
    if b"%PDF-" not in inhalt[:1024]:  # PDF-Kennung darf laut Norm bis Offset 1024 liegen
        raise HTTPException(
            422,
            detail={
                "code": "kein_pdf",
                "grund": "Die Datei ist kein PDF. " + _PDF_ANLEITUNG,
            },
        )
    wurzel.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=wurzel) as arbeit:
        upload = Path(arbeit) / "upload.pdf"
        upload.write_bytes(inhalt)
        try:
            ergebnis = normalisiere_briefpapier(upload, _briefpapier_pfad(wurzel))
        except NormalisierungAbgelehnt as fehler:
            raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
        except NormalisierungFehlgeschlagen as fehler:
            raise HTTPException(500, detail={"grund": str(fehler)}) from fehler
    # Original bewusst verwerfen — gespeichert wird nur die normalisierte Fassung.
    erzeuge_vorschau_png(_briefpapier_pfad(wurzel), _vorschau_pfad(wurzel), dpi=150)
    # Der Kern kennt keinen Schlüssel und legt beide Dateien im Klartext ab.
    # Sie tragen den Briefbogen der Firma, also die Identität des Mandanten —
    # hier nachträglich verschlüsseln, sobald sie fertig sind.
    for datei_pfad in (_briefpapier_pfad(wurzel), _vorschau_pfad(wurzel)):
        if datei_pfad.exists():
            _schreibe_datei(datei_pfad, datei_pfad.read_bytes())
    meta = {
        "dateiname": datei.filename,
        "schriften_ersetzt": ergebnis.schriften_ersetzt,
        "hochgeladen": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    _schreibe_json(wurzel / "briefpapier.json", meta)
    return meta


@app.get("/api/briefpapier/vorschau.png")
def briefpapier_vorschau(wurzel: Path = Depends(mandant)) -> FileResponse:
    if not _vorschau_pfad(wurzel).exists():
        raise HTTPException(404, detail={"grund": "Kein Briefpapier eingerichtet."})
    # Verschlüsselt abgelegt — FileResponse würde Geheimtext ausliefern.
    return Response(_lies_datei(_vorschau_pfad(wurzel)), media_type="image/png")


# ---------------------------------------------------------------- Schreibzone

@app.put("/api/schreibzone")
def schreibzone_setzen(zone: dict, wurzel: Path = Depends(mandant)) -> dict:
    try:
        geprueft = Schreibzone(
            kopf_ende_mm=float(zone["kopf_ende_mm"]),
            fuss_beginn_mm=float(zone["fuss_beginn_mm"]),
        )
    except (KeyError, TypeError, ValueError) as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    daten = {
        "kopf_ende_mm": geprueft.kopf_ende_mm,
        "fuss_beginn_mm": geprueft.fuss_beginn_mm,
    }
    _schreibe_json(wurzel / "schreibzone.json", daten)
    return daten


# ---------------------------------------------------------------- Gestaltung

_FARBE_MUSTER = re.compile(r"#[0-9a-fA-F]{6}")


def _gestaltung_aus_json(daten: dict) -> Blattgestaltung:
    schrift = daten.get("schrift", "liberation-sans")
    if schrift not in {s.schluessel for s in verfuegbare_schriften()}:
        raise HTTPException(422, detail={"grund": f"Unbekannte Schrift: {schrift!r}."})
    try:
        schriftgrad = Schriftgrad[str(daten.get("schriftgrad", "normal")).upper()]
        layout = Layoutvariante(str(daten.get("layout", "klassisch")).lower())
    except (KeyError, ValueError) as fehler:
        raise HTTPException(
            422, detail={"grund": f"Ungültige Gestaltung: {fehler}"}
        ) from fehler
    farbe = str(daten.get("akzentfarbe") or "#136f83").strip()
    if not _FARBE_MUSTER.fullmatch(farbe):
        raise HTTPException(
            422, detail={"grund": f"Ungültige Akzentfarbe: {farbe!r} (erwartet #rrggbb)."}
        )
    return Blattgestaltung(
        schrift=schrift,
        schriftgrad=schriftgrad,
        layout=layout,
        belegdaten_als_zeile=bool(daten.get("belegdaten_als_zeile", False)),
        akzent_an=bool(daten.get("akzent_an", False)),
        akzentfarbe=farbe,
    )


def _gestaltung_laden(wurzel: Path) -> Blattgestaltung:
    daten = _lese_json(wurzel / "gestaltung.json")
    if daten is None:
        return Blattgestaltung()
    return _gestaltung_aus_json(daten)


@app.get("/api/gestaltung/schriften")
def gestaltung_schriften(_: Nutzer = Depends(freigegeben)) -> list[dict]:
    return [
        {"schluessel": schrift.schluessel, "name": schrift.name}
        for schrift in verfuegbare_schriften()
    ]


@app.put("/api/gestaltung")
def gestaltung_setzen(daten: dict, wurzel: Path = Depends(mandant)) -> dict:
    _gestaltung_aus_json(daten)  # validieren, bevor gespeichert wird
    gespeichert = {
        "schrift": daten.get("schrift", "liberation-sans"),
        "schriftgrad": str(daten.get("schriftgrad", "normal")).lower(),
        "layout": str(daten.get("layout", "klassisch")).lower(),
        "belegdaten_als_zeile": bool(daten.get("belegdaten_als_zeile", False)),
        "akzent_an": bool(daten.get("akzent_an", False)),
        "akzentfarbe": str(daten.get("akzentfarbe") or "#136f83").strip(),
    }
    _schreibe_json(wurzel / "gestaltung.json", gespeichert)
    return gespeichert


@app.get("/api/gestaltung/vorschau.png")
def gestaltung_vorschau(
    schrift: str | None = None,
    schriftgrad: str | None = None,
    layout: str | None = None,
    zeile: bool = False,
    akzent: bool = False,
    farbe: str | None = None,
    wurzel: Path = Depends(mandant),
) -> Response:
    """Musterrechnung mit der (ggf. noch ungespeicherten) Gestaltung als PNG."""
    if schrift or schriftgrad or layout:
        gestaltung = _gestaltung_aus_json(
            {
                "schrift": schrift or "liberation-sans",
                "schriftgrad": schriftgrad or "normal",
                "layout": layout or "klassisch",
                "belegdaten_als_zeile": zeile,
                "akzent_an": akzent,
                "akzentfarbe": farbe or "#136f83",
            }
        )
    else:
        gestaltung = _gestaltung_laden(wurzel)
    zone_json = _lese_json(wurzel / "schreibzone.json")
    zone = (
        Schreibzone(
            kopf_ende_mm=zone_json["kopf_ende_mm"],
            fuss_beginn_mm=zone_json["fuss_beginn_mm"],
        )
        if zone_json
        else Schreibzone()
    )
    stammdaten_json = _lese_json(wurzel / "stammdaten.json")
    stammdaten = _stammdaten_aus_json(stammdaten_json) if stammdaten_json else None
    with _im_klartext(_briefpapier_pfad(wurzel)) as bogen:
        briefpapier = bogen if _briefpapier_pfad(wurzel).exists() else None
        pdf = erzeuge_gestaltungsvorschau(
            zone, gestaltung, stammdaten, briefpapier,
            girocode=_girocode_aktiv(wurzel),
        )
    wurzel.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=wurzel) as arbeit:
        pdf_pfad = Path(arbeit) / "vorschau.pdf"
        pdf_pfad.write_bytes(pdf)
        png_pfad = Path(arbeit) / "vorschau.png"
        erzeuge_vorschau_png(pdf_pfad, png_pfad, dpi=110)
        return Response(png_pfad.read_bytes(), media_type="image/png")


# ---------------------------------------------------------------- Stammdaten

@app.put("/api/stammdaten")
def stammdaten_setzen(
    daten: dict,
    person: Nutzer = Depends(freigegeben),
    wurzel: Path = Depends(mandant),
) -> dict:
    try:
        _stammdaten_aus_json(daten)  # Strukturprüfung; §14 blockiert erst je Rechnung
    except (KeyError, TypeError) as fehler:
        raise HTTPException(422, detail={"grund": f"Unvollständige Stammdaten: {fehler}"}) from fehler
    if daten.get("nummern_muster"):
        try:
            _muster_zerlegen(daten["nummern_muster"])
        except ValueError as fehler:
            raise HTTPException(
                422, detail={"code": "nummern_muster", "grund": str(fehler)}
            ) from fehler
    _schreibe_json(wurzel / "stammdaten.json", daten)
    # Blind Index nachziehen: Er erlaubt die Frage, ob ein anderes Konto
    # dasselbe Steuermerkmal führt, ohne die Nummer lesbar abzulegen.
    # Bei jedem Speichern neu — Firmen wechseln ihre Steuernummer, etwa
    # beim Umzug in einen anderen Finanzamtsbezirk.
    konten.setze_steuer_index(
        person.id,
        konten.steuer_index(daten.get("ust_idnr"), daten.get("steuernummer")),
    )
    return daten


def _stammdaten_aus_json(daten: dict) -> Stammdaten:
    return Stammdaten(
        firmierung=daten.get("firmierung", ""),
        anschrift=_anschrift_aus_json(daten.get("anschrift", {})),
        steuernummer=daten.get("steuernummer") or None,
        ust_idnr=daten.get("ust_idnr") or None,
        iban=daten.get("iban", ""),
        bic=daten.get("bic") or None,
        zahlungsziel_tage=int(daten.get("zahlungsziel_tage") or 14),
        kontakt_name=daten.get("kontakt_name") or None,
        kontakt_email=daten.get("kontakt_email") or None,
        kontakt_telefon=daten.get("kontakt_telefon") or None,
        kleinunternehmer=bool(daten.get("kleinunternehmer", False)),
        artikelnummern=bool(daten.get("artikelnummern", False)),
    )


def _anschrift_aus_json(daten: dict) -> Anschrift:
    return Anschrift(
        strasse=daten.get("strasse", ""),
        plz=daten.get("plz", ""),
        ort=daten.get("ort", ""),
        land=daten.get("land") or "DE",
    )


# ---------------------------------------------------------------- Nummernkreis

STANDARD_NUMMERN_MUSTER = "RE-{JJJJ}-{NNNN}"
STANDARD_VERWENDUNGSZWECK = "{NUMMER}"


def _nummern_muster(wurzel: Path) -> str:
    daten = _lese_json(wurzel / "stammdaten.json") or {}
    return daten.get("nummern_muster") or STANDARD_NUMMERN_MUSTER


def _muster_zerlegen(muster: str) -> tuple[re.Pattern, int, bool]:
    """Zerlegt ein Nummern-Muster ({JJJJ}, {JJ}, genau ein {N…}-Zähler).

    Liefert (Erkennungs-Regex, Zählerbreite, enthält Jahresanteil).
    """
    zaehler = re.findall(r"\{(N+)\}", muster)
    if len(zaehler) != 1:
        raise ValueError(
            "Das Nummern-Muster braucht genau einen Zähler-Platzhalter "
            "({N}, {NN}, {NNN} …), z. B. RE-{JJJJ}-{NNNN}."
        )
    breite = len(zaehler[0])
    ausdruck = ""
    for teil in re.split(r"(\{JJJJ\}|\{JJ\}|\{N+\})", muster):
        if teil == "{JJJJ}":
            ausdruck += r"(?P<jahr>\d{4})"
        elif teil == "{JJ}":
            ausdruck += r"(?P<jahr2>\d{2})"
        elif teil and re.fullmatch(r"\{N+\}", teil):
            ausdruck += r"(?P<lfd>\d{" + str(breite) + r",})"
        elif teil:
            ausdruck += re.escape(teil)
    hat_jahr = "{JJJJ}" in muster or "{JJ}" in muster
    return re.compile(f"^{ausdruck}$"), breite, hat_jahr


def _formatiere_nummer(muster: str, jahr: int, laufend: int) -> str:
    _, breite, _ = _muster_zerlegen(muster)
    return (
        muster.replace("{JJJJ}", f"{jahr:04d}")
        .replace("{JJ}", f"{jahr % 100:02d}")
        .replace("{" + "N" * breite + "}", str(laufend).zfill(breite))
    )


def _nummern_stand(wurzel: Path, jahr: int, jahr_zaehlt: bool) -> dict:
    stand = _lese_json(wurzel / "nummernkreis.json") or {"jahr": jahr, "laufend": 0}
    if jahr_zaehlt and stand["jahr"] != jahr:
        stand = {"jahr": jahr, "laufend": 0}  # Jahreswechsel: Zähler beginnt neu
    return stand


@app.get("/api/nummer/vorschlag")
def nummern_vorschlag(wurzel: Path = Depends(mandant)) -> dict:
    muster = _nummern_muster(wurzel)
    _, _, hat_jahr = _muster_zerlegen(muster)
    jahr = dt.date.today().year
    stand = _nummern_stand(wurzel, jahr, hat_jahr)
    return {"nummer": _formatiere_nummer(muster, jahr, stand["laufend"] + 1)}


def _nummernkreis_fortschreiben(wurzel: Path, nummer: str) -> None:
    muster = _nummern_muster(wurzel)
    ausdruck, _, hat_jahr = _muster_zerlegen(muster)
    treffer = ausdruck.match(nummer)
    if not treffer:
        return  # überschriebene, freie Nummern zählen nicht mit
    gruppen = treffer.groupdict()
    jahr = dt.date.today().year
    if gruppen.get("jahr") and int(gruppen["jahr"]) != jahr:
        return
    if gruppen.get("jahr2") and int(gruppen["jahr2"]) != jahr % 100:
        return
    stand = _nummern_stand(wurzel, jahr, hat_jahr)
    stand["jahr"] = jahr
    stand["laufend"] = max(stand["laufend"], int(gruppen["lfd"]))
    _schreibe_json(wurzel / "nummernkreis.json", stand)


def _girocode_aktiv(wurzel: Path) -> bool:
    daten = _lese_json(wurzel / "stammdaten.json") or {}
    return bool(daten.get("girocode", True))


# ---------------------------------------------------------------- Verwendungszweck

def _verwendungszweck(wurzel: Path, rechnung: Rechnung, angegeben: str | None) -> str | None:
    """Verwendungszweck: explizit angegeben oder aus dem Muster erzeugt."""
    if angegeben and angegeben.strip():
        return angegeben.strip()
    daten = _lese_json(wurzel / "stammdaten.json") or {}
    muster = daten.get("verwendungszweck_muster", STANDARD_VERWENDUNGSZWECK)
    if not muster:
        return None
    text = (
        muster.replace("{NUMMER}", rechnung.nummer)
        .replace("{DATUM}", rechnung.rechnungsdatum.strftime("%d.%m.%Y"))
        .replace("{KUNDE}", rechnung.empfaenger.name)
    )
    return text.strip() or None


# ---------------------------------------------------------------- Kundenstamm

def _leer_zu_none(wert) -> str | None:
    """Leere Eingaben als None speichern, nicht als Leerzeichenkette —
    der Kern unterscheidet zwischen 'nicht angegeben' und 'leer'."""
    text = str(wert or "").strip()
    return text or None


@app.get("/api/kunden")
def kunden_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    return _lese_json(wurzel / "kunden.json") or []


@app.put("/api/kunden")
def kunden_setzen(daten: list[dict], wurzel: Path = Depends(mandant)) -> list[dict]:
    """Ganze Liste ersetzen — das Adressbuch schickt seinen Stand zurück."""
    bereinigt = []
    for eintrag in daten:
        name = str(eintrag.get("name", "")).strip()
        if not name:
            continue  # namenlose Einträge sind niemandem nützlich
        anschrift = eintrag.get("anschrift") or {}
        bereinigt.append({
            "name": name,
            "anschrift": {
                "strasse": str(anschrift.get("strasse", "")).strip(),
                "plz": str(anschrift.get("plz", "")).strip(),
                "ort": str(anschrift.get("ort", "")).strip(),
                "land": str(anschrift.get("land") or "DE").strip().upper()[:2],
            },
            "ust_idnr": _leer_zu_none(eintrag.get("ust_idnr")),
            "email": _leer_zu_none(eintrag.get("email")),
            "leitweg_id": _leer_zu_none(eintrag.get("leitweg_id")),
            "zuletzt": eintrag.get("zuletzt"),
        })
    _schreibe_json(wurzel / "kunden.json", bereinigt)
    return bereinigt


# ---------------------------------------------------------------- Artikel

@app.get("/api/artikel")
def artikel_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    return _lese_json(wurzel / "artikel.json") or []


@app.put("/api/artikel")
def artikel_setzen(daten: list[dict], wurzel: Path = Depends(mandant)) -> list[dict]:
    """Wiederkehrende Leistungen und Waren. Preise als Zeichenkette, damit
    aus 19,90 kein Fließkommawert wird — gerechnet wird erst im Kern."""
    bereinigt = []
    for eintrag in daten:
        bezeichnung = str(eintrag.get("bezeichnung", "")).strip()
        if not bezeichnung:
            continue
        preis = str(eintrag.get("einzelpreis", "")).replace(",", ".").strip()
        if preis:
            try:
                Decimal(preis)  # nur prüfen, gespeichert wird der Text
            except InvalidOperation:
                raise HTTPException(422, detail={
                    "grund": f"{bezeichnung}: {preis!r} ist kein Preis."
                })
        steuer = str(eintrag.get("steuer") or "UST_19").strip()
        if steuer not in {k.name for k in Steuerkategorie}:
            raise HTTPException(422, detail={
                "grund": f"{bezeichnung}: unbekannte Steuerkategorie {steuer!r}."
            })
        bereinigt.append({
            "artikelnummer": _leer_zu_none(eintrag.get("artikelnummer")),
            "bezeichnung": bezeichnung,
            "beschreibung": _leer_zu_none(eintrag.get("beschreibung")),
            "einheit": str(eintrag.get("einheit") or "C62").strip(),
            "einzelpreis": preis or "0.00",
            "steuer": steuer,
        })
    _schreibe_json(wurzel / "artikel.json", bereinigt)
    return bereinigt


# -------------------------------------------------------- Rechnungsvorlagen

@app.get("/api/vorlagen")
def vorlagen_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    return _lese_json(wurzel / "vorlagen.json") or []


@app.put("/api/vorlagen")
def vorlagen_setzen(daten: list[dict], wurzel: Path = Depends(mandant)) -> list[dict]:
    """Benannte Positionslisten — dieselbe Leistung an wechselnde Kunden.

    Bewusst OHNE Empfänger: das ist der Unterschied zu „Beleg als Vorlage"
    aus der Ablage, die den alten Kunden mitschleppt. Preise werden wie im
    Artikelstamm als Zeichenkette gehalten, gerechnet wird erst im Kern.
    """
    bereinigt = []
    for eintrag in daten:
        name = str(eintrag.get("name", "")).strip()
        if not name:
            continue  # namenlose Vorlagen findet später niemand wieder
        positionen = []
        for p in eintrag.get("positionen") or []:
            bezeichnung = str(p.get("bezeichnung", "")).strip()
            if not bezeichnung:
                continue
            for feld in ("menge", "einzelpreis"):
                wert = str(p.get(feld, "")).replace(",", ".").strip()
                if wert:
                    try:
                        Decimal(wert)
                    except InvalidOperation:
                        raise HTTPException(422, detail={
                            "grund": f"{name} / {bezeichnung}: "
                                     f"{wert!r} ist keine Zahl."
                        })
            steuer = str(p.get("steuer") or "UST_19").strip()
            if steuer not in {k.name for k in Steuerkategorie}:
                raise HTTPException(422, detail={
                    "grund": f"{name} / {bezeichnung}: "
                             f"unbekannte Steuerkategorie {steuer!r}."
                })
            positionen.append({
                "artikelnummer": _leer_zu_none(p.get("artikelnummer")),
                "bezeichnung": bezeichnung,
                "beschreibung": _leer_zu_none(p.get("beschreibung")),
                "menge": str(p.get("menge", "")).replace(",", ".").strip() or "1",
                "einheit": str(p.get("einheit") or "C62").strip(),
                "einzelpreis": str(p.get("einzelpreis", "")).replace(",", ".").strip() or "0.00",
                "steuer": steuer,
            })
        if not positionen:
            continue  # eine Vorlage ohne Positionen spart keine Arbeit
        rabatt = str(eintrag.get("rabatt", "")).replace(",", ".").strip()
        if rabatt:
            try:
                Decimal(rabatt)
            except InvalidOperation:
                raise HTTPException(422, detail={
                    "grund": f"{name}: {rabatt!r} ist kein Rabattwert."
                })
        bereinigt.append({
            "name": name,
            "positionen": positionen,
            "rabatt": rabatt or None,
            "rabatt_art": "prozent" if eintrag.get("rabatt_art") == "prozent" else "betrag",
            "rabatt_grund": _leer_zu_none(eintrag.get("rabatt_grund")),
            "freitext": _leer_zu_none(eintrag.get("freitext")),
        })
    _schreibe_json(wurzel / "vorlagen.json", bereinigt)
    return bereinigt


def _kunde_merken(wurzel: Path, rechnung: Rechnung) -> None:
    """Merkliste: Empfänger jeder erzeugten Rechnung wird gepflegt (Upsert)."""
    kunden = _lese_json(wurzel / "kunden.json") or []
    eintrag = {
        "name": rechnung.empfaenger.name,
        "anschrift": {
            "strasse": rechnung.empfaenger.anschrift.strasse,
            "plz": rechnung.empfaenger.anschrift.plz,
            "ort": rechnung.empfaenger.anschrift.ort,
            "land": rechnung.empfaenger.anschrift.land,
        },
        "ust_idnr": rechnung.empfaenger.ust_idnr,
        "email": rechnung.empfaenger.email,
        "leitweg_id": rechnung.empfaenger.leitweg_id,
        "zuletzt": rechnung.rechnungsdatum.isoformat(),
    }
    schluessel = rechnung.empfaenger.name.casefold()
    kunden = [k for k in kunden if k.get("name", "").casefold() != schluessel]
    kunden.insert(0, eintrag)
    _schreibe_json(wurzel / "kunden.json", kunden)


# ---------------------------------------------------------------- Rechnung

def _dezimal(wert, feld: str) -> Decimal:
    try:
        return Decimal(str(wert).replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as fehler:
        raise HTTPException(
            422, detail={"grund": f"{feld}: {wert!r} ist keine Zahl."}
        ) from fehler


def _datum(wert, feld: str) -> dt.date:
    try:
        return dt.date.fromisoformat(wert)
    except (TypeError, ValueError) as fehler:
        raise HTTPException(
            422, detail={"grund": f"{feld}: {wert!r} ist kein Datum (JJJJ-MM-TT)."}
        ) from fehler


def _rechnung_aus_json(daten: dict) -> Rechnung:
    empfaenger_daten = daten.get("empfaenger", {})
    empfaenger = Empfaenger(
        name=empfaenger_daten.get("name", ""),
        anschrift=_anschrift_aus_json(empfaenger_daten.get("anschrift", {})),
        ust_idnr=empfaenger_daten.get("ust_idnr") or None,
        leitweg_id=empfaenger_daten.get("leitweg_id") or None,
        email=empfaenger_daten.get("email") or None,
    )
    positionen = []
    for index, position in enumerate(daten.get("positionen", []), start=1):
        try:
            steuer = Steuerkategorie[position.get("steuer", "UST_19")]
        except KeyError as fehler:
            raise HTTPException(
                422, detail={"grund": f"Position {index}: unbekannte Steuerkategorie."}
            ) from fehler
        positionen.append(
            Position(
                bezeichnung=position.get("bezeichnung", ""),
                menge=_dezimal(position.get("menge", "0"), f"Position {index} Menge"),
                einheit=position.get("einheit", "C62"),
                einzelpreis=_dezimal(
                    position.get("einzelpreis", "0"), f"Position {index} Einzelpreis"
                ),
                steuer=steuer,
                beschreibung=position.get("beschreibung") or None,
                artikelnummer=position.get("artikelnummer") or None,
            )
        )
    zeitraum = None
    if daten.get("leistungszeitraum"):
        zeitraum = Zeitraum(
            von=_datum(daten["leistungszeitraum"].get("von"), "Leistungszeitraum von"),
            bis=_datum(daten["leistungszeitraum"].get("bis"), "Leistungszeitraum bis"),
        )
    try:
        typ = Belegtyp[daten.get("typ", "RECHNUNG")]
    except KeyError as fehler:
        raise HTTPException(422, detail={"grund": "Unbekannter Belegtyp."}) from fehler
    return Rechnung(
        nummer=daten.get("nummer", ""),
        rechnungsdatum=_datum(daten.get("rechnungsdatum"), "Rechnungsdatum"),
        empfaenger=empfaenger,
        positionen=tuple(positionen),
        leistungsdatum=(
            _datum(daten["leistungsdatum"], "Leistungsdatum")
            if daten.get("leistungsdatum")
            else None
        ),
        leistungszeitraum=zeitraum,
        rabatt_betrag=(
            _dezimal(daten["rabatt_betrag"], "Rabatt") if daten.get("rabatt_betrag") else None
        ),
        rabatt_prozent=(
            _dezimal(daten["rabatt_prozent"], "Rabattsatz")
            if daten.get("rabatt_prozent")
            else None
        ),
        rabatt_grund=daten.get("rabatt_grund") or "Rabatt",
        freitext=daten.get("freitext") or None,
        typ=typ,
        bezugs_nummer=daten.get("bezugs_nummer") or None,
        bezugs_datum=(
            _datum(daten["bezugs_datum"], "Bezugsdatum") if daten.get("bezugs_datum") else None
        ),
        faelligkeit=(
            _datum(daten["faelligkeit"], "Fälligkeit") if daten.get("faelligkeit") else None
        ),
    )


def _voraussetzungen(wurzel: Path) -> tuple[Stammdaten, Schreibzone]:
    stammdaten_json = _lese_json(wurzel / "stammdaten.json")
    zone_json = _lese_json(wurzel / "schreibzone.json")
    fehlend = []
    if stammdaten_json is None:
        fehlend.append("Stammdaten")
    if zone_json is None:
        fehlend.append("Schreibzone")
    if not _briefpapier_pfad(wurzel).exists():
        fehlend.append("Briefpapier")
    if fehlend:
        raise HTTPException(
            409, detail={"grund": f"Einrichtung unvollständig: {', '.join(fehlend)} fehlt."}
        )
    return (
        _stammdaten_aus_json(stammdaten_json),
        Schreibzone(
            kopf_ende_mm=zone_json["kopf_ende_mm"],
            fuss_beginn_mm=zone_json["fuss_beginn_mm"],
        ),
    )


@app.post("/api/rechnung")
def rechnung_erzeugen(
    daten: dict,
    person: Nutzer = Depends(freigegeben),
    wurzel: Path = Depends(mandant),
) -> JSONResponse:
    stammdaten, zone = _voraussetzungen(wurzel)
    rechnung = _rechnung_aus_json(daten)
    rechnung = dataclasses.replace(
        rechnung,
        verwendungszweck=_verwendungszweck(wurzel, rechnung, daten.get("verwendungszweck")),
    )
    # Eine vergebene Nummer ist vergeben. Eine erteilte Rechnung darf nicht
    # geändert werden — wer korrigieren will, storniert per Gutschrift und
    # schreibt eine neue. Ohne diese Sperre überschriebe ein zweiter Aufruf
    # mit derselben Nummer PDF, XML und Daten des ersten Belegs spurlos;
    # die fortlaufende Nummerierung wäre wertlos, weil hinter einer Nummer
    # nacheinander verschiedene Rechnungen stehen könnten.
    if (wurzel / "ablage" / rechnung.nummer).exists():
        return JSONResponse(
            status_code=409,
            content={
                "code": "nummer_vergeben",
                "grund": f"Die Nummer {rechnung.nummer} ist bereits vergeben. "
                "Eine erteilte Rechnung wird nicht geändert: stornieren Sie "
                "sie per Gutschrift und schreiben Sie eine neue.",
            },
        )
    # Kontingent vorab prüfen, damit kein PDF gebaut wird, das niemand bekommt.
    if not konten.kontingent(person).darf_erzeugen:
        return JSONResponse(
            status_code=402,
            content={
                "code": "kontingent",
                "grund": "Die Inklusivmenge dieses Monats ist aufgebraucht und das "
                "Guthaben reicht nicht für eine weitere Rechnung.",
            },
        )
    try:
        with _im_klartext(_briefpapier_pfad(wurzel)) as bogen:
            ergebnis = erzeuge_rechnung(
                rechnung,
                stammdaten,
                bogen,
                zone,
                zeitpunkt=dt.datetime.now(dt.timezone.utc).astimezone(),
                gestaltung=_gestaltung_laden(wurzel),
                girocode=_girocode_aktiv(wurzel),
            )
    except UngueltigeRechnung as fehler:
        return JSONResponse(
            status_code=422,
            content={
                "befunde": [dataclasses.asdict(befund) for befund in fehler.befunde]
            },
        )
    except BlattUeberlauf as fehler:
        return JSONResponse(status_code=422, content={"grund": str(fehler)})

    try:
        kontingent = konten.buche_rechnung(person, rechnung.nummer)
    except KontingentErschoepft as fehler:
        return JSONResponse(
            status_code=402, content={"code": "kontingent", "grund": str(fehler)}
        )

    ordner = wurzel / "ablage" / rechnung.nummer
    ordner.mkdir(parents=True, exist_ok=True)
    # Auch der Beleg selbst wird verschlüsselt — er ist die Rechnung, nicht
    # bloss ihre Beschreibung.
    _schreibe_datei(ordner / "rechnung.pdf", ergebnis.pdf)
    _schreibe_datei(ordner / "factur-x.xml", ergebnis.xml)
    _schreibe_json(ordner / "daten.json", daten)
    _nummernkreis_fortschreiben(wurzel, rechnung.nummer)
    _kunde_merken(wurzel, rechnung)
    return JSONResponse(
        {
            "nummer": rechnung.nummer,
            "brutto": str(ergebnis.summen.brutto),
            "pdf": f"/api/ablage/{rechnung.nummer}/pdf",
            "xml": f"/api/ablage/{rechnung.nummer}/xml",
            "verbraucht_monat": kontingent.verbraucht,
            "frei_uebrig": kontingent.frei_uebrig,
            "guthaben_cent": kontingent.guthaben_cent,
        }
    )


@app.post("/api/rechnung/xrechnung")
def xrechnung_erzeugen(daten: dict, wurzel: Path = Depends(mandant)) -> Response:
    stammdaten, _ = _voraussetzungen(wurzel)
    rechnung = _rechnung_aus_json(daten)
    rechnung = dataclasses.replace(
        rechnung,
        verwendungszweck=_verwendungszweck(wurzel, rechnung, daten.get("verwendungszweck")),
    )
    try:
        xml = erzeuge_xrechnung(rechnung, stammdaten)
    except UngueltigeRechnung as fehler:
        return JSONResponse(
            status_code=422,
            content={
                "befunde": [dataclasses.asdict(befund) for befund in fehler.befunde]
            },
        )
    return Response(
        xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="xrechnung-{rechnung.nummer}.xml"'
        },
    )


# ---------------------------------------------------------------- Ablage-Zugriff

def _ablage_ordner(wurzel: Path, nummer: str) -> Path:
    ordner = (wurzel / "ablage" / nummer).resolve()
    if not ordner.is_relative_to((wurzel / "ablage").resolve()) or not ordner.is_dir():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    # resolve() baut ein neues Pfadobjekt und verliert dabei den Schlüssel
    # — hier wieder anheften, sonst stehen die Belege ohne ihn da.
    if isinstance(wurzel, Mandantenpfad):
        ordner = Mandantenpfad(ordner)
        ordner.schluessel = wurzel.schluessel
    return ordner


@app.get("/api/ablage")
def ablage_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    basis = wurzel / "ablage"
    if not basis.exists():
        return []
    belege = []
    for ordner in sorted(basis.iterdir(), reverse=True):
        daten = _lese_json(ordner / "daten.json") or {}
        belege.append(
            {
                "nummer": ordner.name,
                "typ": daten.get("typ", "RECHNUNG"),
                "rechnungsdatum": daten.get("rechnungsdatum"),
                "empfaenger": (daten.get("empfaenger") or {}).get("name"),
                "pdf": f"/api/ablage/{ordner.name}/pdf",
                "xml": f"/api/ablage/{ordner.name}/xml",
            }
        )
    return belege


# Belege liegen verschlüsselt — FileResponse würde den Geheimtext
# ausliefern. Sie gehen deshalb durch _lies_datei und als Response
# hinaus. Rechnungen sind ein paar hundert Kilobyte; sie dabei einmal in
# den Speicher zu nehmen, ist unkritisch.
@app.get("/api/ablage/{nummer}/pdf")
def ablage_pdf(nummer: str, wurzel: Path = Depends(mandant)) -> Response:
    pfad = _ablage_ordner(wurzel, nummer) / "rechnung.pdf"
    if not pfad.exists():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    return Response(
        _lies_datei(pfad),
        media_type="application/pdf",
        headers={"content-disposition": f'inline; filename="{nummer}.pdf"'},
    )


@app.get("/api/ablage/{nummer}/xml")
def ablage_xml(nummer: str, wurzel: Path = Depends(mandant)) -> Response:
    pfad = _ablage_ordner(wurzel, nummer) / "factur-x.xml"
    if not pfad.exists():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    return Response(
        _lies_datei(pfad),
        media_type="application/xml",
        headers={
            "content-disposition": f'attachment; filename="{nummer}-factur-x.xml"'
        },
    )


@app.get("/api/ablage/{nummer}/daten")
def ablage_daten(nummer: str, wurzel: Path = Depends(mandant)) -> dict:
    return _lese_json(_ablage_ordner(wurzel, nummer) / "daten.json") or {}
