"""Meldungen aus dem Arbeitsbereich: Formular, Bilder, Adminliste.

Getrennt von ``wege_konto``, obwohl beides am Konto haengt: Hier geht
etwas nach draussen. Jede Zeile in dieser Datei entscheidet mit darueber,
was ein Kunde ungewollt veroeffentlicht — das soll man an einer Stelle
nachlesen koennen und nicht zwischen Passwortwechsel und Abmeldung
suchen muessen.

Der Bildweg ist der einzige Endpunkt neben dem Stripe-Webhook, der ohne
Anmeldung antwortet: GitHub holt die Bilder ueber das offene Netz. Er
liefert ausschliesslich Dateien aus ``DATEN/meldungen`` und ausschliesslich
solche, deren Name genau der vergebenen Form entspricht (siehe
``meldungen.bild_pfad``).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from . import konten, meldungen
from .basis import freigegeben, oeffentliche_adresse, protokoll, verwalter
from .konten import Nutzer

wege = APIRouter()

# Welcher Stand laeuft? Der Stack setzt RECHNUNGSBLATT_VERSION, um auf einem
# Image festzunageln; steht dort nichts, laeuft "latest". Fuer eine Meldung
# ist gerade das die wichtigste Angabe -- ohne sie sucht man den Fehler im
# falschen Stand.
STAND = os.environ.get("RECHNUNGSBLATT_VERSION", "").strip()

_MEDIENARTEN = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


@wege.get("/api/meldung")
def meldung_angebot(_: Nutzer = Depends(freigegeben)) -> dict:
    """Was gemeldet werden kann — und ob es auch ankommt."""
    return {
        "arten": [{"schluessel": s, "name": n} for s, n in meldungen.ARTEN.items()],
        "eingerichtet": meldungen.ist_eingerichtet(),
        "max_bilder": meldungen.MAX_BILDER,
        "max_bild_bytes": meldungen.MAX_BILD_BYTES,
        "stand": STAND or "unbekannt",
    }


@wege.post("/api/meldung")
async def meldung_abschicken(
    anfrage: Request,
    art: str = Form(...),
    titel: str = Form(...),
    text: str = Form(...),
    seite: str = Form(""),
    bilder: list[UploadFile] = File(default=[]),
    person: Nutzer = Depends(freigegeben),
) -> dict:
    """Nimmt eine Meldung an, legt sie ab und veroeffentlicht sie.

    **Erst speichern, dann veroeffentlichen.** Wenn GitHub klemmt, ist die
    Meldung trotzdem da; der Grund steht am Datensatz. Andersherum waere
    die Schilderung weg, und der Kunde muesste sie ein zweites Mal
    tippen — genau in dem Moment, in dem er ohnehin schon aergerlich ist.
    """
    art = art.strip()
    if art not in meldungen.ARTEN:
        raise HTTPException(422, detail={"grund": "Unbekannte Art der Meldung."})
    titel, text = titel.strip(), text.strip()
    if not titel or not text:
        raise HTTPException(
            422,
            detail={"grund": "Bitte eine Überschrift und eine Beschreibung angeben."},
        )

    if konten.meldungen_seit(person.id) >= meldungen.MELDUNGEN_JE_STUNDE:
        raise HTTPException(
            429,
            detail={
                "code": "zu_viele",
                "grund": "Sie haben gerade viele Meldungen abgeschickt — "
                "bitte in einer Stunde erneut.",
            },
        )

    namen: list[str] = []
    for datei in bilder[: meldungen.MAX_BILDER]:
        inhalt = await datei.read()
        if not inhalt:
            continue
        try:
            namen.append(meldungen.speichere_bild(inhalt))
        except meldungen.MeldungFehler as fehler:
            # Was schon liegt, wieder wegräumen: Eine abgebrochene Meldung
            # soll keine verwaisten Dateien hinterlassen.
            meldungen.loesche_bilder(namen)
            raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    browser = anfrage.headers.get("user-agent", "")
    meldung_id = konten.lege_meldung_an(
        person.id, art, titel, text, seite, browser, STAND, namen
    )

    basis = oeffentliche_adresse(anfrage)
    koerper = meldungen.baue_koerper(
        art, text, person.id, seite, browser, STAND,
        [f"{basis}/meldungen/bilder/{name}" for name in namen],
    )
    try:
        nummer, adresse = meldungen.lege_issue_an(
            f"[{meldungen.ARTEN[art]}] {titel}", koerper, art
        )
    except meldungen.MeldungFehler as fehler:
        protokoll.warning("Meldung %s nicht veröffentlicht: %s", meldung_id, fehler)
        konten.vermerke_issue(meldung_id, None, "", str(fehler))
        # Kein Fehler für den Kunden: Seine Meldung ist angekommen. Dass sie
        # noch nicht bei GitHub liegt, ist Sache des Betreibers.
        return {"meldung": meldung_id, "issue": None, "veroeffentlicht": False}

    konten.vermerke_issue(meldung_id, nummer, adresse, "")
    return {
        "meldung": meldung_id,
        "issue": {"nummer": nummer, "adresse": adresse},
        "veroeffentlicht": True,
    }


@wege.get("/meldungen/bilder/{name}")
def meldungsbild(name: str) -> FileResponse:
    """Ein Bildschirmfoto zu einer Meldung — ohne Anmeldung.

    Muss oeffentlich sein: Der Bildproxy von GitHub holt die Datei ueber
    das offene Netz, auch bei einem privaten Repository. Geschuetzt ist sie
    allein durch ihren Zufallsnamen.
    """
    pfad = meldungen.bild_pfad(name)
    if pfad is None:
        raise HTTPException(404, detail={"grund": "Kein solches Bild."})
    return FileResponse(
        pfad,
        media_type=_MEDIENARTEN.get(pfad.suffix, "application/octet-stream"),
        # Ein Bild aendert sich nie -- es traegt einen Zufallsnamen und wird
        # nie ueberschrieben. Der Proxy darf es also behalten.
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@wege.get("/api/verwaltung/meldungen")
def verwaltung_meldungen(_: Nutzer = Depends(verwalter)) -> list[dict]:
    """Alle Meldungen, neueste zuerst — mit Adresse des Kontos.

    Hier steht die E-Mail-Adresse, im Issue steht sie nicht: Wer antworten
    will, findet sie an einer Stelle, die eine Anmeldung verlangt.
    """
    ergebnis = []
    for zeile in konten.meldungen():
        ergebnis.append({
            "id": zeile["id"],
            "art": zeile["art"],
            "art_name": meldungen.ARTEN.get(zeile["art"], zeile["art"]),
            "titel": zeile["titel"],
            "text": zeile["text"],
            "seite": zeile["seite"],
            "browser": zeile["browser"],
            "stand": zeile["stand"],
            "bilder": [n for n in (zeile["bilder"] or "").split("\n") if n],
            "issue_nummer": zeile["issue_nummer"],
            "issue_url": zeile["issue_url"],
            "issue_fehler": zeile["issue_fehler"],
            "angelegt": zeile["angelegt"].isoformat(timespec="seconds"),
            "konto": zeile["nutzer"],
            "email": zeile["email"],
        })
    return ergebnis
