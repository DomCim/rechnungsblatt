"""Einrichtung eines Mandanten: Briefpapier, Schreibzone, Gestaltung.

Was einmal eingestellt wird und danach für jede Rechnung gilt. Der
Briefbogen wird beim Hochladen normalisiert (CMYK → sRGB, Schriften
eingebettet) — ohne das ließe sich daraus kein PDF/A-3B bauen.
"""

from __future__ import annotations

import json
import datetime as dt
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from rechnungsblatt_kern import (
    NormalisierungAbgelehnt,
    NormalisierungFehlgeschlagen,
    Blattgestaltung,
    Layoutvariante,
    Schreibzone,
    Schriftgrad,
    erzeuge_gestaltungsvorschau,
    erzeuge_vorschau_png,
    normalisiere_briefpapier,
    verfuegbare_schriften,
)

from . import konten
from .ablage import (
    briefpapier_pfad,
    im_klartext,
    lese_json,
    lies_datei,
    schreibe_datei,
    schreibe_json,
    vorschau_pfad,
)
from .umwandlung import (
    _FARBE_MUSTER,
    _gestaltung_aus_json,
    _gestaltung_laden,
    _stammdaten_aus_json,
    _anschrift_aus_json,
    _muster_zerlegen,
    _girocode_aktiv,
)
from .basis import MAX_UPLOAD_BYTES, freigegeben, mandant, protokoll
from .darstellung import nutzer_json
from .konten import Nutzer

wege = APIRouter()


@wege.get("/api/status")
def status(
    person: Nutzer = Depends(freigegeben), wurzel: Path = Depends(mandant)
) -> dict:
    zone = lese_json(wurzel / "schreibzone.json")
    briefpapier = lese_json(wurzel / "briefpapier.json")
    return {
        "briefpapier": briefpapier,
        "schreibzone": zone,
        "stammdaten": lese_json(wurzel / "stammdaten.json"),
        "gestaltung": lese_json(wurzel / "gestaltung.json"),
        "bereit": bool(briefpapier and zone and lese_json(wurzel / "stammdaten.json")),
        "konto": nutzer_json(person),
    }


@wege.post("/api/briefpapier")
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
            ergebnis = normalisiere_briefpapier(upload, briefpapier_pfad(wurzel))
        except NormalisierungAbgelehnt as fehler:
            raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
        except NormalisierungFehlgeschlagen as fehler:
            raise HTTPException(500, detail={"grund": str(fehler)}) from fehler
    # Original bewusst verwerfen — gespeichert wird nur die normalisierte Fassung.
    erzeuge_vorschau_png(briefpapier_pfad(wurzel), vorschau_pfad(wurzel), dpi=150)
    # Der Kern kennt keinen Schlüssel und legt beide Dateien im Klartext ab.
    # Sie tragen den Briefbogen der Firma, also die Identität des Mandanten —
    # hier nachträglich verschlüsseln, sobald sie fertig sind.
    for datei_pfad in (briefpapier_pfad(wurzel), vorschau_pfad(wurzel)):
        if datei_pfad.exists():
            schreibe_datei(datei_pfad, datei_pfad.read_bytes())
    meta = {
        "dateiname": datei.filename,
        "schriften_ersetzt": ergebnis.schriften_ersetzt,
        "hochgeladen": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    schreibe_json(wurzel / "briefpapier.json", meta)
    return meta


@wege.get("/api/briefpapier/vorschau.png")
def briefpapier_vorschau(wurzel: Path = Depends(mandant)) -> FileResponse:
    if not vorschau_pfad(wurzel).exists():
        raise HTTPException(404, detail={"grund": "Kein Briefpapier eingerichtet."})
    # Verschlüsselt abgelegt — FileResponse würde Geheimtext ausliefern.
    return Response(lies_datei(vorschau_pfad(wurzel)), media_type="image/png")


@wege.put("/api/schreibzone")
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
    schreibe_json(wurzel / "schreibzone.json", daten)
    return daten


@wege.get("/api/gestaltung/schriften")
def gestaltung_schriften(_: Nutzer = Depends(freigegeben)) -> list[dict]:
    return [
        {"schluessel": schrift.schluessel, "name": schrift.name}
        for schrift in verfuegbare_schriften()
    ]


@wege.put("/api/gestaltung")
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
    schreibe_json(wurzel / "gestaltung.json", gespeichert)
    return gespeichert


@wege.get("/api/gestaltung/vorschau.png")
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
    zone_json = lese_json(wurzel / "schreibzone.json")
    zone = (
        Schreibzone(
            kopf_ende_mm=zone_json["kopf_ende_mm"],
            fuss_beginn_mm=zone_json["fuss_beginn_mm"],
        )
        if zone_json
        else Schreibzone()
    )
    stammdaten_json = lese_json(wurzel / "stammdaten.json")
    stammdaten = _stammdaten_aus_json(stammdaten_json) if stammdaten_json else None
    with im_klartext(briefpapier_pfad(wurzel)) as bogen:
        briefpapier = bogen if briefpapier_pfad(wurzel).exists() else None
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


@wege.put("/api/stammdaten")
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
    schreibe_json(wurzel / "stammdaten.json", daten)
    # Blind Index nachziehen: Er erlaubt die Frage, ob ein anderes Konto
    # dasselbe Steuermerkmal führt, ohne die Nummer lesbar abzulegen.
    # Bei jedem Speichern neu — Firmen wechseln ihre Steuernummer, etwa
    # beim Umzug in einen anderen Finanzamtsbezirk.
    konten.setze_steuer_index(
        person.id,
        konten.steuer_index(daten.get("ust_idnr"), daten.get("steuernummer")),
    )
    return daten


_WORD_ENDUNGEN = (".doc", ".docx", ".odt", ".rtf")


_PDF_ANLEITUNG = (
    "Bitte einmal als PDF speichern und die PDF hochladen: in Word "
    "„Datei → Speichern unter → Dateityp: PDF“ (oder „Datei → Exportieren → "
    "PDF/XPS-Dokument erstellen“), in LibreOffice „Datei → Als PDF exportieren“."
)
