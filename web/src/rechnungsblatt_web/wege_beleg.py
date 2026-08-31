"""Der Beleg: Stammlisten, Nummernkreis, Erzeugung, Ablage.

**PDF und XML entstehen aus denselben Daten im selben Vorgang** — die
Kernregel des Projekts (``docs/uebergabe.md`` §2). Ein bestehendes PDF
wird nie nachträglich angereichert.
"""

from __future__ import annotations

import datetime as dt
import dataclasses
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from rechnungsblatt_kern import (
    BlattUeberlauf,
    Belegtyp,
    Empfaenger,
    Position,
    Rechnung,
    Schreibzone,
    Stammdaten,
    Steuerkategorie,
    UngueltigeRechnung,
    Zeitraum,
    erzeuge_rechnung,
    erzeuge_xrechnung,
)

from . import konten
from .ablage import (
    ablage_ordner,
    briefpapier_pfad,
    im_klartext,
    lese_json,
    lies_datei,
    schreibe_datei,
    schreibe_json,
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
from .basis import freigegeben, mandant, protokoll
from .konten import KontingentErschoepft, KontoFehler, Nutzer

wege = APIRouter()


@wege.get("/api/nummer/vorschlag")
def nummern_vorschlag(wurzel: Path = Depends(mandant)) -> dict:
    muster = _nummern_muster(wurzel)
    _, _, hat_jahr = _muster_zerlegen(muster)
    jahr = dt.date.today().year
    stand = _nummern_stand(wurzel, jahr, hat_jahr)
    return {"nummer": _formatiere_nummer(muster, jahr, stand["laufend"] + 1)}


@wege.get("/api/kunden")
def kunden_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    return lese_json(wurzel / "kunden.json") or []


@wege.put("/api/kunden")
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
    schreibe_json(wurzel / "kunden.json", bereinigt)
    return bereinigt


@wege.get("/api/artikel")
def artikel_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    return lese_json(wurzel / "artikel.json") or []


@wege.put("/api/artikel")
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
    schreibe_json(wurzel / "artikel.json", bereinigt)
    return bereinigt


@wege.get("/api/vorlagen")
def vorlagen_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    return lese_json(wurzel / "vorlagen.json") or []


@wege.put("/api/vorlagen")
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
    schreibe_json(wurzel / "vorlagen.json", bereinigt)
    return bereinigt


@wege.post("/api/rechnung")
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
        with im_klartext(briefpapier_pfad(wurzel)) as bogen:
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
    schreibe_datei(ordner / "rechnung.pdf", ergebnis.pdf)
    schreibe_datei(ordner / "factur-x.xml", ergebnis.xml)
    schreibe_json(ordner / "daten.json", daten)
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


@wege.post("/api/rechnung/xrechnung")
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


@wege.get("/api/ablage")
def ablage_liste(wurzel: Path = Depends(mandant)) -> list[dict]:
    basis = wurzel / "ablage"
    if not basis.exists():
        return []
    belege = []
    for ordner in sorted(basis.iterdir(), reverse=True):
        daten = lese_json(ordner / "daten.json") or {}
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
# ausliefern. Sie gehen deshalb durch lies_datei und als Response
# hinaus. Rechnungen sind ein paar hundert Kilobyte; sie dabei einmal in
# den Speicher zu nehmen, ist unkritisch.
@wege.get("/api/ablage/{nummer}/pdf")
def ablage_pdf(nummer: str, wurzel: Path = Depends(mandant)) -> Response:
    pfad = ablage_ordner(wurzel, nummer) / "rechnung.pdf"
    if not pfad.exists():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    return Response(
        lies_datei(pfad),
        media_type="application/pdf",
        headers={"content-disposition": f'inline; filename="{nummer}.pdf"'},
    )


@wege.get("/api/ablage/{nummer}/xml")
def ablage_xml(nummer: str, wurzel: Path = Depends(mandant)) -> Response:
    pfad = ablage_ordner(wurzel, nummer) / "factur-x.xml"
    if not pfad.exists():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    return Response(
        lies_datei(pfad),
        media_type="application/xml",
        headers={
            "content-disposition": f'attachment; filename="{nummer}-factur-x.xml"'
        },
    )


@wege.get("/api/ablage/{nummer}/daten")
def ablage_daten(nummer: str, wurzel: Path = Depends(mandant)) -> dict:
    return lese_json(ablage_ordner(wurzel, nummer) / "daten.json") or {}


def _nummern_muster(wurzel: Path) -> str:
    daten = lese_json(wurzel / "stammdaten.json") or {}
    return daten.get("nummern_muster") or STANDARD_NUMMERN_MUSTER


def _formatiere_nummer(muster: str, jahr: int, laufend: int) -> str:
    _, breite, _ = _muster_zerlegen(muster)
    return (
        muster.replace("{JJJJ}", f"{jahr:04d}")
        .replace("{JJ}", f"{jahr % 100:02d}")
        .replace("{" + "N" * breite + "}", str(laufend).zfill(breite))
    )


def _nummern_stand(wurzel: Path, jahr: int, jahr_zaehlt: bool) -> dict:
    stand = lese_json(wurzel / "nummernkreis.json") or {"jahr": jahr, "laufend": 0}
    if jahr_zaehlt and stand["jahr"] != jahr:
        stand = {"jahr": jahr, "laufend": 0}  # Jahreswechsel: Zähler beginnt neu
    return stand


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
    schreibe_json(wurzel / "nummernkreis.json", stand)


def _verwendungszweck(wurzel: Path, rechnung: Rechnung, angegeben: str | None) -> str | None:
    """Verwendungszweck: explizit angegeben oder aus dem Muster erzeugt."""
    if angegeben and angegeben.strip():
        return angegeben.strip()
    daten = lese_json(wurzel / "stammdaten.json") or {}
    muster = daten.get("verwendungszweck_muster", STANDARD_VERWENDUNGSZWECK)
    if not muster:
        return None
    text = (
        muster.replace("{NUMMER}", rechnung.nummer)
        .replace("{DATUM}", rechnung.rechnungsdatum.strftime("%d.%m.%Y"))
        .replace("{KUNDE}", rechnung.empfaenger.name)
    )
    return text.strip() or None


def _leer_zu_none(wert) -> str | None:
    """Leere Eingaben als None speichern, nicht als Leerzeichenkette —
    der Kern unterscheidet zwischen 'nicht angegeben' und 'leer'."""
    text = str(wert or "").strip()
    return text or None


def _kunde_merken(wurzel: Path, rechnung: Rechnung) -> None:
    """Merkliste: Empfänger jeder erzeugten Rechnung wird gepflegt (Upsert)."""
    kunden = lese_json(wurzel / "kunden.json") or []
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
    schreibe_json(wurzel / "kunden.json", kunden)


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
    stammdaten_json = lese_json(wurzel / "stammdaten.json")
    zone_json = lese_json(wurzel / "schreibzone.json")
    fehlend = []
    if stammdaten_json is None:
        fehlend.append("Stammdaten")
    if zone_json is None:
        fehlend.append("Schreibzone")
    if not briefpapier_pfad(wurzel).exists():
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


STANDARD_NUMMERN_MUSTER = "RE-{JJJJ}-{NNNN}"


STANDARD_VERWENDUNGSZWECK = "{NUMMER}"


