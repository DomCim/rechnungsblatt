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
import mimetypes
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
from fastapi.middleware.gzip import GZipMiddleware
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

from . import (
    ablage,
    bezahlen,
    dkim,
    konten,
    post,
    statistik,
    tresor,
    wege_beleg,
    wege_einrichtung,
    wege_konto,
    wege_seiten,
    wege_verwaltung,
    wege_zahlung,
)
from .darstellung import nutzer_json, tarif_json
from .basis import (
    DATEN,
    MAX_UPLOAD_BYTES,
    PLAUSIBLE_DOMAIN,
    PLAUSIBLE_URL,
    SEITEN,
    SITZUNG_COOKIE,
    SITZUNG_KOPFZEILE,
    SPAETER,
    ZONEN_EDITOR,
    angemeldet,
    angemeldeter,
    freigegeben,
    mandant,
    oeffentliche_adresse,
    protokoll,
    setze_sitzungscookie,
    verwalter,
    wurzel_von,
)
from .ablage import (
    Mandantenpfad,
    ablage_ordner,
    briefpapier_pfad,
    im_klartext,
    ist_bereit,
    lese_json,
    lies_datei,
    schreibe_datei,
    schreibe_json,
    vorschau_pfad,
)
from .konten import KontingentErschoepft, KontoFehler, Nutzer


# Nur für die lokale Entwicklung: den Sitzungsschlüssel auch aus einer
# Kopfzeile lesen. iOS leert bei Web-Apps über HTTP den Cookie-Speicher
# beim Schließen — im Portainer-Stack (HTTPS) ist das nicht nötig und
# bleibt deshalb aus.


# Wiederherstellungscodes zwischen Registrierung und Bestätigung.
# Bewusst nur im Speicher: Der Code darf nirgends abgelegt werden, sonst
# wäre der ganze Aufwand umsonst. Startet der Dienst dazwischen neu, ist
# er weg — dann hilft „neuen Code erzeugen" im Konto.


@contextlib.asynccontextmanager
async def _lebenszyklus(app: FastAPI):
    """Schema anlegen und den Admin aus der Umgebung einrichten."""
    konten.richte_schema_ein()
    # Abgelaufene Sitzungen wegräumen. Sie tragen den verpackten
    # Datenschlüssel des Kunden; ungenutzt liegen zu bleiben ist kein
    # Zustand, den man einer Tabelle mit Schlüsseln wünscht.
    entfernt = konten.raeume_sitzungen_auf()
    if entfernt:
        protokoll.info("%d abgelaufene Sitzungen entfernt.", entfernt)
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

# Ohne Kompression gingen die Seiten roh über die Leitung. Gemessen am
# 01.09.2026: start.html 62,8 -> 18,2 KB (71 %), basis.css 30,6 -> 9,4 KB,
# werkzeuge.js 20,3 -> 7,0 KB.
#
# Die Mindestgröße hält kleine Antworten heraus — bei einer JSON-Antwort
# von 200 Bytes kostet das Komprimieren mehr, als es einspart. PDF, ZIP
# und woff2 sind bereits komprimiert; sie werden anhand ihres Medientyps
# ohnehin übersprungen (bei woff2 nachgemessen: gzip macht die Datei
# minimal größer).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Die Wege je Fachbereich. Die Pfade stehen in den Modulen selbst, nicht
# als Präfix hier — so bleibt jeder Endpunkt an seiner Adresse auffindbar,
# auch wenn man nur den Pfad kennt.
app.include_router(wege_seiten.wege)
app.include_router(wege_konto.wege)
app.include_router(wege_einrichtung.wege)
app.include_router(wege_beleg.wege)
app.include_router(wege_verwaltung.wege)
app.include_router(wege_zahlung.wege)


# ---------------------------------------------------------------- Seiten


# ---------------------------------------------------------------- App-Hülle
# Damit die Seite als App installiert werden kann. Der Service Worker muss
# von der Wurzel kommen: sein Geltungsbereich ist sonst auf /seiten/
# begrenzt und die Navigation unter /app/… liefe daran vorbei.

# ---------------------------------------------------------------- Suchmaschinen


app.mount("/zonen-editor", StaticFiles(directory=str(ZONEN_EDITOR), html=True), name="editor")
# woff2 kennt Pythons mimetypes-Tabelle nicht; ohne diesen Eintrag
# liefert StaticFiles application/octet-stream, und Browser behandeln die
# Schriften dann als beliebige Downloads statt als Schriften.
mimetypes.add_type("font/woff2", ".woff2")

app.mount("/seiten", StaticFiles(directory=str(SEITEN)), name="seiten")


# ---------------------------------------------------------------- Konten-API


# ---------------------------------------------------------------- Ablage

# ---------------------------------------------------------------- Status


# ---------------------------------------------------------------- Briefpapier


# ---------------------------------------------------------------- Schreibzone


# ---------------------------------------------------------------- Gestaltung


# ---------------------------------------------------------------- Stammdaten


# ---------------------------------------------------------------- Nummernkreis


# ---------------------------------------------------------------- Verwendungszweck


# ---------------------------------------------------------------- Kundenstamm


# ---------------------------------------------------------------- Artikel


# -------------------------------------------------------- Rechnungsvorlagen


# ---------------------------------------------------------------- Rechnung


# ---------------------------------------------------------------- Ablage-Zugriff
