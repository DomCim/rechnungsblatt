"""Der Beleg: Stammlisten, Nummernkreis, Erzeugung, Ablage.

**PDF und XML entstehen aus denselben Daten im selben Vorgang** — die
Kernregel des Projekts (``docs/uebergabe.md`` §2). Ein bestehendes PDF
wird nie nachträglich angereichert.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import io
import json
import re
import zipfile
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

from . import konten, protokoll_beleg, siegel, verfahrensdokumentation
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

# Als chr() geschrieben und nicht als Escape: Beim Erzeugen dieser Datei
# wuerde ein Backslash-n leicht zum echten Umbruch — dann stuende der
# Zeilenwechsel mitten im Quelltext statt in der Ausgabe.
CRLF = chr(13) + chr(10)
BOM = chr(65279)          # damit Excel die CSV als UTF-8 liest


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
    # Ins Protokoll, bevor der Nummernkreis fortschreibt: Scheitert das
    # Schreiben, ist die Nummer noch frei und der Vorgang wiederholbar.
    protokoll_beleg.haenge_an(
        ordner,
        "erzeugt",
        nummer=rechnung.nummer,
        typ=rechnung.typ.name,
        brutto=str(ergebnis.summen.brutto),
        waehrung=rechnung.waehrung,
        empfaenger=rechnung.empfaenger.name,
        # Bei Gutschrift und Korrektur haelt der Bezug fest, worauf sich
        # der Beleg bezieht — das ist die Spur, die ein Pruefer sucht.
        **({"bezug": rechnung.bezugs_nummer} if rechnung.bezugs_nummer else {}),
    )
    # Erst jetzt siegeln: Der Abdruck soll die Dateien so erfassen, wie
    # sie am Ende liegen — Protokoll eingeschlossen waere zirkulaer, denn
    # das Protokoll waechst spaeter noch (Storno).
    siegel.siegle(wurzel, rechnung.nummer)

    if rechnung.bezugs_nummer:
        # Auch am Urbeleg vermerken, dass er aufgehoben oder berichtigt
        # wurde. Sonst stuende die Spur nur auf einer Seite.
        urbeleg = wurzel / "ablage" / rechnung.bezugs_nummer
        if urbeleg.is_dir():
            protokoll_beleg.haenge_an(
                urbeleg,
                "storniert" if rechnung.typ is Belegtyp.GUTSCHRIFT else "berichtigt",
                durch=rechnung.nummer,
                typ=rechnung.typ.name,
            )
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
        # Nur Verzeichnisse sind Belege. Neben ihnen liegt die
        # Siegelkette als Datei — sie waere sonst ein Geisterbeleg.
        if not ordner.is_dir():
            continue
        daten = lese_json(ordner / "daten.json") or {}
        belege.append(
            {
                "nummer": ordner.name,
                "typ": daten.get("typ", "RECHNUNG"),
                "rechnungsdatum": daten.get("rechnungsdatum"),
                "empfaenger": (daten.get("empfaenger") or {}).get("name"),
                "pdf": f"/api/ablage/{ordner.name}/pdf",
                "xml": f"/api/ablage/{ordner.name}/xml",
                # Wurde der Beleg aufgehoben oder berichtigt? Das gehoert
                # in die Liste, nicht erst in die Einzelansicht — sonst
                # sieht eine stornierte Rechnung aus wie jede andere.
                **_aufhebung(ordner),
            }
        )
    return belege


def _aufhebung(ordner: Path) -> dict:
    """Der letzte Eintrag, der den Beleg aufhebt oder berichtigt."""
    for eintrag in reversed(protokoll_beleg.lies(ordner)):
        if eintrag.get("ereignis") in ("storniert", "berichtigt"):
            return {"aufgehoben": eintrag["ereignis"], "durch": eintrag.get("durch")}
    return {}


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


def _liesmich(anzahl: int, von: str | None, bis: str | None) -> str:
    """Was im Archiv steht — für jemanden, der es zum ersten Mal öffnet."""
    zeitraum = (f"Zeitraum: {von or 'Anfang'} bis {bis or 'heute'}"
                if (von or bis) else "Zeitraum: alle Belege")
    zeilen = [
        "Belegausgabe aus Rechnungsblatt",
        "==============================",
        "",
        zeitraum,
        f"Belege in diesem Archiv: {anzahl}",
        f"Erstellt am: {dt.datetime.now().astimezone():%d.%m.%Y %H:%M}",
        "",
        "Je Beleg ein Ordner, benannt nach der Rechnungsnummer:",
        "",
        "  rechnung.pdf     Der Beleg als PDF/A-3B. Das XML steckt",
        "                   zusätzlich darin (ZUGFeRD/Factur-X).",
        "  factur-x.xml     Dasselbe XML noch einmal einzeln, zum Einlesen.",
        "  daten.json       Die Eingaben, aus denen beides entstand.",
        "  protokoll.jsonl  Was mit dem Beleg geschah — eine Zeile je",
        "                   Ereignis, nur angehängt, nie geändert.",
        "",
        "uebersicht.csv     Alle Belege als Tabelle (Semikolon getrennt).",
        "siegel.jsonl       Die Siegelkette (siehe unten), vollständig.",
        "",
        "Zur Unveränderbarkeit",
        "---------------------",
        "PDF und XML entstehen aus denselben Daten im selben Vorgang; ein",
        "bestehendes PDF wird nie nachträglich angereichert. Eine vergebene",
        "Rechnungsnummer lässt sich nicht erneut verwenden, und es gibt",
        "keinen Weg, einen abgelegten Beleg zu löschen oder zu ändern.",
        "Wird eine Rechnung aufgehoben, entsteht eine Gutschrift mit Bezug;",
        "beide Protokolle halten das fest.",
        "",
        "Zusätzlich trägt jeder Beleg ein Siegel: den SHA-256 über PDF,",
        "XML und Eingabedaten, verknüpft mit dem Siegel des vorigen",
        "Belegs. Ändert sich ein Beleg nachträglich, passt sein Siegel",
        "nicht mehr, und weil die folgenden darauf aufbauen, fällt es an",
        "allen Nachfolgern auf. Nachrechnen lässt sich das mit den Daten",
        "in siegel.jsonl allein - ohne Zugang zum System.",
        "",
        "Kein Zeitstempel einer anerkannten Stelle: Wer Schreibzugriff auf",
        "die Ablage hat, könnte die Kette neu bilden. Sie zeigt, dass",
        "punktuell nichts geändert wurde.",
        "",
        "Diese Ausgabe ersetzt keine Verfahrensdokumentation. Einen Entwurf",
        "dafür gibt es im Konto unter \u201eFür die Betriebsprüfung\u201c.",
        "",
    ]
    return CRLF.join(zeilen)


@wege.get("/api/ablage/export.zip")
def ablage_export(
    von: str | None = None,
    bis: str | None = None,
    wurzel: Path = Depends(mandant),
) -> Response:
    """Alle Belege eines Zeitraums als ZIP — PDF, XML, Daten, Protokoll.

    **Der Weg zum Steuerpruefer.** Einzeln herunterzuladen ist bei
    zweihundert Rechnungen im Jahr keine Option, und wer seine Belege
    nicht am Stueck herausbekommt, hat sie faktisch nicht.

    Im Archiv liegt je Beleg ein Ordner mit dem, was auch auf der Platte
    liegt — dazu eine ``uebersicht.csv`` und eine ``LIESMICH.txt``, die
    erklaert, was der Pruefer vor sich hat. Ohne die steht er vor einem
    Haufen Dateien.

    Ohne Zeitraum: alles. Mit ``von``/``bis`` (JJJJ-MM-TT) nur, was
    dazwischen liegt — Betriebspruefungen betreffen meist ein Jahr.
    """
    basis = wurzel / "ablage"
    if not basis.exists():
        raise HTTPException(404, detail={"grund": "Noch keine Belege abgelegt."})

    def im_zeitraum(datum: str | None) -> bool:
        if not datum:
            # Ein Beleg ohne Datum fliegt nicht heraus — lieber zu viel im
            # Archiv als eine Luecke, die niemand bemerkt.
            return True
        if von and datum < von:
            return False
        if bis and datum > bis:
            return False
        return True

    puffer = io.BytesIO()
    zeilen = [("Nummer", "Typ", "Datum", "Empfaenger", "Netto", "Steuer",
               "Brutto", "Waehrung", "Bezug", "Aufgehoben durch")]
    anzahl = 0
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        for ordner in sorted(basis.iterdir()):
            if not ordner.is_dir():
                continue
            daten = lese_json(ordner / "daten.json") or {}
            if not im_zeitraum(daten.get("rechnungsdatum")):
                continue
            anzahl += 1
            for name in ("rechnung.pdf", "factur-x.xml", "daten.json",
                         protokoll_beleg.DATEI):
                quelle = ordner / name
                if quelle.exists():
                    archiv.writestr(f"{ordner.name}/{name}", lies_datei(quelle))
            summen = daten.get("summen") or {}
            hebung = _aufhebung(ordner)
            zeilen.append((
                ordner.name,
                daten.get("typ", "RECHNUNG"),
                daten.get("rechnungsdatum", ""),
                (daten.get("empfaenger") or {}).get("name", ""),
                str(summen.get("netto", "")),
                str(summen.get("steuer", "")),
                str(summen.get("brutto", "")),
                daten.get("waehrung", "EUR"),
                daten.get("bezugs_nummer", "") or "",
                hebung.get("durch", "") or "",
            ))

        if not anzahl:
            raise HTTPException(
                404, detail={"grund": "In diesem Zeitraum liegen keine Belege."})

        # Semikolon und BOM: So oeffnet Excel die Datei in Deutschland
        # ohne Nachfrage richtig — sonst steht alles in einer Spalte.
        auszug = io.StringIO()
        csv.writer(auszug, delimiter=";",
                   quoting=csv.QUOTE_MINIMAL).writerows(zeilen)
        archiv.writestr("uebersicht.csv", BOM + auszug.getvalue())
        # Die Siegelkette komplett, nicht nur die Glieder des Zeitraums:
        # Sie laesst sich nur im Ganzen nachrechnen, jedes Glied haengt am
        # vorigen. Ein Ausschnitt waere nicht pruefbar.
        kette = basis / siegel.DATEI
        if kette.exists():
            archiv.writestr(siegel.DATEI, kette.read_bytes())
        archiv.writestr("LIESMICH.txt", _liesmich(anzahl, von, bis))

    name = "rechnungen"
    if von or bis:
        name += f"-{von or 'anfang'}-bis-{bis or 'heute'}"
    return Response(
        puffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@wege.get("/api/pruefung/siegel")
def pruefung_siegel(wurzel: Path = Depends(mandant)) -> dict:
    """Rechnet die Siegelkette nach — wurde an den Belegen etwas geaendert?

    Die Belege liegen als Dateien, und die GoBD halten fest, dass das
    fuer sich genommen keine Unveraenderbarkeit gewaehrleistet (Rz. 110).
    Die Kette ist eine der Zusatzmassnahmen, die das aufwiegen: Jeder
    Beleg traegt einen Abdruck, der am vorigen haengt.

    Ein Beleg ohne Glied ist kein Fehler — er stammt aus der Zeit vor der
    Kette. Er wird gesondert ausgewiesen, nicht als Befund gezaehlt.
    """
    return siegel.pruefe(wurzel)


@wege.get("/api/pruefung/verfahrensdokumentation")
def pruefung_verfahrensdokumentation(wurzel: Path = Depends(mandant)) -> Response:
    """Ein Entwurf der Verfahrensdokumentation, mit den eigenen Daten gefuellt.

    Die Dokumentation schuldet der Steuerpflichtige, nicht der Hersteller
    (GoBD Rz. 21, 151) — nur kann er den technischen Teil nicht kennen.
    Rechnungsblatt schreibt deshalb, was es belegen kann, und laesst den
    Rest als benannte offene Frage stehen. Ein Entwurf, der so tut, als
    sei er fertig, waere in der Pruefung schaedlicher als keiner.
    """
    text = verfahrensdokumentation.erzeuge(wurzel)
    name = f"verfahrensdokumentation-{dt.date.today():%Y-%m-%d}.txt"
    return Response(
        # BOM, damit der Windows-Editor die Umlaute nicht zerlegt.
        (BOM + text).encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@wege.get("/api/ablage/{nummer}/protokoll")
def ablage_protokoll(nummer: str, wurzel: Path = Depends(mandant)) -> list[dict]:
    """Was mit diesem Beleg geschah — fuer die Betriebspruefung.

    Ein Beleg laesst sich hier nicht aendern und nicht loeschen; wird er
    aufgehoben, entsteht ein zweiter mit Bezug. Das Protokoll haelt beide
    Seiten dieser Spur fest.
    """
    return protokoll_beleg.lies(ablage_ordner(wurzel, nummer))


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


