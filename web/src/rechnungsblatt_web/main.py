"""FastAPI-App: Einrichtung (Briefpapier → Zone → Stammdaten) und Rechnungen.

Die App ist eine schmale Schicht: jede fachliche Entscheidung (Prüfung,
Rechnen, Rendern, Zusammenbau) trifft der Kern. Hier gibt es nur Ablage,
Übersetzung von Formulardaten in das Kern-Modell und die Auslieferung der
Seiten.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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

DATEN = Path(os.environ.get("DATEN_VERZEICHNIS", "/daten"))
_WEB_WURZEL = Path(__file__).resolve().parents[2]  # …/web
SEITEN = Path(__file__).resolve().parent / "seiten"
ZONEN_EDITOR = _WEB_WURZEL / "zonen-editor"

PLAUSIBLE_URL = os.environ.get("PLAUSIBLE_URL", "").rstrip("/")
PLAUSIBLE_DOMAIN = os.environ.get("PLAUSIBLE_DOMAIN", "")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = FastAPI(title="Rechnungsblatt", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- Seiten

def _seite(name: str) -> HTMLResponse:
    inhalt = (SEITEN / name).read_text(encoding="utf-8")
    schnipsel = ""
    if PLAUSIBLE_URL and PLAUSIBLE_DOMAIN:
        schnipsel = (
            f'<script defer data-domain="{PLAUSIBLE_DOMAIN}" '
            f'src="{PLAUSIBLE_URL}/js/script.js"></script>'
        )
    return HTMLResponse(inhalt.replace("<!--PLAUSIBLE-->", schnipsel))


@app.get("/", response_class=HTMLResponse)
def einrichtung() -> HTMLResponse:
    return _seite("einrichtung.html")


@app.get("/rechnung", response_class=HTMLResponse)
def rechnungsformular() -> HTMLResponse:
    return _seite("rechnung.html")


app.mount("/zonen-editor", StaticFiles(directory=str(ZONEN_EDITOR), html=True), name="editor")
app.mount("/seiten", StaticFiles(directory=str(SEITEN)), name="seiten")


# ---------------------------------------------------------------- Ablage

def _lese_json(pfad: Path) -> dict | None:
    if not pfad.exists():
        return None
    return json.loads(pfad.read_text(encoding="utf-8"))


def _schreibe_json(pfad: Path, daten: dict) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")


def _briefpapier_pfad() -> Path:
    return DATEN / "briefpapier_norm.pdf"


def _vorschau_pfad() -> Path:
    return DATEN / "briefpapier_vorschau.png"


# ---------------------------------------------------------------- Status

@app.get("/api/status")
def status() -> dict:
    zone = _lese_json(DATEN / "schreibzone.json")
    briefpapier = _lese_json(DATEN / "briefpapier.json")
    return {
        "briefpapier": briefpapier,
        "schreibzone": zone,
        "stammdaten": _lese_json(DATEN / "stammdaten.json"),
        "gestaltung": _lese_json(DATEN / "gestaltung.json"),
        "bereit": bool(briefpapier and zone and _lese_json(DATEN / "stammdaten.json")),
    }


# ---------------------------------------------------------------- Briefpapier

_WORD_ENDUNGEN = (".doc", ".docx", ".odt", ".rtf")
_PDF_ANLEITUNG = (
    "Bitte einmal als PDF speichern und die PDF hochladen: in Word "
    "„Datei → Speichern unter → Dateityp: PDF“ (oder „Datei → Exportieren → "
    "PDF/XPS-Dokument erstellen“), in LibreOffice „Datei → Als PDF exportieren“."
)


@app.post("/api/briefpapier")
async def briefpapier_hochladen(datei: UploadFile) -> dict:
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
    DATEN.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATEN) as arbeit:
        upload = Path(arbeit) / "upload.pdf"
        upload.write_bytes(inhalt)
        try:
            ergebnis = normalisiere_briefpapier(upload, _briefpapier_pfad())
        except NormalisierungAbgelehnt as fehler:
            raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
        except NormalisierungFehlgeschlagen as fehler:
            raise HTTPException(500, detail={"grund": str(fehler)}) from fehler
    # Original bewusst verwerfen — gespeichert wird nur die normalisierte Fassung.
    erzeuge_vorschau_png(_briefpapier_pfad(), _vorschau_pfad(), dpi=150)
    meta = {
        "dateiname": datei.filename,
        "schriften_ersetzt": ergebnis.schriften_ersetzt,
        "hochgeladen": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    _schreibe_json(DATEN / "briefpapier.json", meta)
    return meta


@app.get("/api/briefpapier/vorschau.png")
def briefpapier_vorschau() -> FileResponse:
    if not _vorschau_pfad().exists():
        raise HTTPException(404, detail={"grund": "Kein Briefpapier eingerichtet."})
    return FileResponse(_vorschau_pfad(), media_type="image/png")


# ---------------------------------------------------------------- Schreibzone

@app.put("/api/schreibzone")
def schreibzone_setzen(zone: dict) -> dict:
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
    _schreibe_json(DATEN / "schreibzone.json", daten)
    return daten


# ---------------------------------------------------------------- Gestaltung

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
    return Blattgestaltung(
        schrift=schrift,
        schriftgrad=schriftgrad,
        layout=layout,
        belegdaten_als_zeile=bool(daten.get("belegdaten_als_zeile", False)),
    )


def _gestaltung_laden() -> Blattgestaltung:
    daten = _lese_json(DATEN / "gestaltung.json")
    if daten is None:
        return Blattgestaltung()
    return _gestaltung_aus_json(daten)


@app.get("/api/gestaltung/schriften")
def gestaltung_schriften() -> list[dict]:
    return [
        {"schluessel": schrift.schluessel, "name": schrift.name}
        for schrift in verfuegbare_schriften()
    ]


@app.put("/api/gestaltung")
def gestaltung_setzen(daten: dict) -> dict:
    _gestaltung_aus_json(daten)  # validieren, bevor gespeichert wird
    gespeichert = {
        "schrift": daten.get("schrift", "liberation-sans"),
        "schriftgrad": str(daten.get("schriftgrad", "normal")).lower(),
        "layout": str(daten.get("layout", "klassisch")).lower(),
        "belegdaten_als_zeile": bool(daten.get("belegdaten_als_zeile", False)),
    }
    _schreibe_json(DATEN / "gestaltung.json", gespeichert)
    return gespeichert


@app.get("/api/gestaltung/vorschau.png")
def gestaltung_vorschau(
    schrift: str | None = None,
    schriftgrad: str | None = None,
    layout: str | None = None,
    zeile: bool = False,
) -> Response:
    """Musterrechnung mit der (ggf. noch ungespeicherten) Gestaltung als PNG."""
    if schrift or schriftgrad or layout:
        gestaltung = _gestaltung_aus_json(
            {
                "schrift": schrift or "liberation-sans",
                "schriftgrad": schriftgrad or "normal",
                "layout": layout or "klassisch",
                "belegdaten_als_zeile": zeile,
            }
        )
    else:
        gestaltung = _gestaltung_laden()
    zone_json = _lese_json(DATEN / "schreibzone.json")
    zone = (
        Schreibzone(
            kopf_ende_mm=zone_json["kopf_ende_mm"],
            fuss_beginn_mm=zone_json["fuss_beginn_mm"],
        )
        if zone_json
        else Schreibzone()
    )
    stammdaten_json = _lese_json(DATEN / "stammdaten.json")
    stammdaten = _stammdaten_aus_json(stammdaten_json) if stammdaten_json else None
    briefpapier = _briefpapier_pfad() if _briefpapier_pfad().exists() else None

    pdf = erzeuge_gestaltungsvorschau(zone, gestaltung, stammdaten, briefpapier)
    DATEN.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATEN) as arbeit:
        pdf_pfad = Path(arbeit) / "vorschau.pdf"
        pdf_pfad.write_bytes(pdf)
        png_pfad = Path(arbeit) / "vorschau.png"
        erzeuge_vorschau_png(pdf_pfad, png_pfad, dpi=110)
        return Response(png_pfad.read_bytes(), media_type="image/png")


# ---------------------------------------------------------------- Stammdaten

@app.put("/api/stammdaten")
def stammdaten_setzen(daten: dict) -> dict:
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
    _schreibe_json(DATEN / "stammdaten.json", daten)
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


def _nummern_muster() -> str:
    daten = _lese_json(DATEN / "stammdaten.json") or {}
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


def _nummern_stand(jahr: int, jahr_zaehlt: bool) -> dict:
    stand = _lese_json(DATEN / "nummernkreis.json") or {"jahr": jahr, "laufend": 0}
    if jahr_zaehlt and stand["jahr"] != jahr:
        stand = {"jahr": jahr, "laufend": 0}  # Jahreswechsel: Zähler beginnt neu
    return stand


@app.get("/api/nummer/vorschlag")
def nummern_vorschlag() -> dict:
    muster = _nummern_muster()
    _, _, hat_jahr = _muster_zerlegen(muster)
    jahr = dt.date.today().year
    stand = _nummern_stand(jahr, hat_jahr)
    return {"nummer": _formatiere_nummer(muster, jahr, stand["laufend"] + 1)}


def _nummernkreis_fortschreiben(nummer: str) -> None:
    muster = _nummern_muster()
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
    stand = _nummern_stand(jahr, hat_jahr)
    stand["jahr"] = jahr
    stand["laufend"] = max(stand["laufend"], int(gruppen["lfd"]))
    _schreibe_json(DATEN / "nummernkreis.json", stand)


# ---------------------------------------------------------------- Verwendungszweck

def _verwendungszweck(rechnung: Rechnung, angegeben: str | None) -> str | None:
    """Verwendungszweck: explizit angegeben oder aus dem Muster erzeugt."""
    if angegeben and angegeben.strip():
        return angegeben.strip()
    daten = _lese_json(DATEN / "stammdaten.json") or {}
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

@app.get("/api/kunden")
def kunden_liste() -> list[dict]:
    return _lese_json(DATEN / "kunden.json") or []


def _kunde_merken(rechnung: Rechnung) -> None:
    """Merkliste: Empfänger jeder erzeugten Rechnung wird gepflegt (Upsert)."""
    kunden = _lese_json(DATEN / "kunden.json") or []
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
    _schreibe_json(DATEN / "kunden.json", kunden)


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


def _voraussetzungen() -> tuple[Stammdaten, Schreibzone]:
    stammdaten_json = _lese_json(DATEN / "stammdaten.json")
    zone_json = _lese_json(DATEN / "schreibzone.json")
    fehlend = []
    if stammdaten_json is None:
        fehlend.append("Stammdaten")
    if zone_json is None:
        fehlend.append("Schreibzone")
    if not _briefpapier_pfad().exists():
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
def rechnung_erzeugen(daten: dict) -> JSONResponse:
    stammdaten, zone = _voraussetzungen()
    rechnung = _rechnung_aus_json(daten)
    rechnung = dataclasses.replace(
        rechnung,
        verwendungszweck=_verwendungszweck(rechnung, daten.get("verwendungszweck")),
    )
    try:
        ergebnis = erzeuge_rechnung(
            rechnung,
            stammdaten,
            _briefpapier_pfad(),
            zone,
            zeitpunkt=dt.datetime.now(dt.timezone.utc).astimezone(),
            gestaltung=_gestaltung_laden(),
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

    ordner = DATEN / "ablage" / rechnung.nummer
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "rechnung.pdf").write_bytes(ergebnis.pdf)
    (ordner / "factur-x.xml").write_bytes(ergebnis.xml)
    _schreibe_json(ordner / "daten.json", daten)
    _nummernkreis_fortschreiben(rechnung.nummer)
    _kunde_merken(rechnung)
    return JSONResponse(
        {
            "nummer": rechnung.nummer,
            "brutto": str(ergebnis.summen.brutto),
            "pdf": f"/api/ablage/{rechnung.nummer}/pdf",
            "xml": f"/api/ablage/{rechnung.nummer}/xml",
        }
    )


@app.post("/api/rechnung/xrechnung")
def xrechnung_erzeugen(daten: dict) -> Response:
    stammdaten, _ = _voraussetzungen()
    rechnung = _rechnung_aus_json(daten)
    rechnung = dataclasses.replace(
        rechnung,
        verwendungszweck=_verwendungszweck(rechnung, daten.get("verwendungszweck")),
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

def _ablage_ordner(nummer: str) -> Path:
    ordner = (DATEN / "ablage" / nummer).resolve()
    if not ordner.is_relative_to((DATEN / "ablage").resolve()) or not ordner.is_dir():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    return ordner


@app.get("/api/ablage")
def ablage_liste() -> list[dict]:
    wurzel = DATEN / "ablage"
    if not wurzel.exists():
        return []
    belege = []
    for ordner in sorted(wurzel.iterdir(), reverse=True):
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


@app.get("/api/ablage/{nummer}/pdf")
def ablage_pdf(nummer: str) -> FileResponse:
    return FileResponse(
        _ablage_ordner(nummer) / "rechnung.pdf",
        media_type="application/pdf",
        filename=f"{nummer}.pdf",
        content_disposition_type="inline",
    )


@app.get("/api/ablage/{nummer}/xml")
def ablage_xml(nummer: str) -> FileResponse:
    return FileResponse(
        _ablage_ordner(nummer) / "factur-x.xml",
        media_type="application/xml",
        filename=f"{nummer}-factur-x.xml",
    )


@app.get("/api/ablage/{nummer}/daten")
def ablage_daten(nummer: str) -> dict:
    return _lese_json(_ablage_ordner(nummer) / "daten.json") or {}
