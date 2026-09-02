"""Konten: Registrierung, Anmeldung, Passwort, eigener Verbrauch.

Der öffentliche Teil der Kontenschicht — alles, was jemand mit seinem
**eigenen** Konto tut. Die Tarifliste steht hier, weil sie zur
Anmeldeentscheidung gehört und ohne Konto abrufbar sein muss.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import konten, post
from .basis import (
    SITZUNG_KOPFZEILE,
    SITZUNG_COOKIE,
    SPAETER,
    angemeldet,
    oeffentliche_adresse,
    setze_sitzungscookie,
    sitzungsschluessel,
)
from .darstellung import nutzer_json, tarif_json
from .konten import KontoFehler, Nutzer

wege = APIRouter()


@wege.get("/api/gesundheit")
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


@wege.get("/api/tarife")
def oeffentliche_tarife() -> list[dict]:
    """Die öffentliche Seite rendert ihre Preistafel hieraus."""
    return [tarif_json(tarif) for tarif in konten.tarife(nur_sichtbare=True)]


@wege.post("/api/registrieren")
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
    SPAETER[person.id] = code
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


@wege.post("/api/email/bestaetigen")
def email_bestaetigen(daten: dict) -> JSONResponse:
    """Sechsstelligen Code einlösen und den Wiederherstellungscode zeigen."""
    person = konten.nutzer_zu_email(daten.get("email", ""))
    if person is None:
        raise HTTPException(422, detail={"grund": "Der Code stimmt nicht."})
    try:
        nutzer_id = konten.loese_nachweis_ein(
            str(daten.get("code", "")).strip(), konten.ZWECK_EMAIL,
            # An das Konto binden, dessen Adresse mitgeschickt wurde:
            # Sonst träfe ein geratener Code irgendein offenes Konto.
            nutzer_id=person.id,
        )
    except KontoFehler as fehler:
        konten.zaehle_fehlversuch(person.id, konten.ZWECK_EMAIL)
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    konten.bestaetige_email(nutzer_id)
    # Jetzt, und nur jetzt, bekommt der Kunde seinen Wiederherstellungscode
    # zu sehen. Er steht nirgends in der Datenbank — nur seine Hülle.
    return JSONResponse({
        "bestaetigt": True,
        "wiederherstellungscode": SPAETER.pop(nutzer_id, None),
    })


@wege.post("/api/email/code-neu")
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


@wege.post("/api/passwort/vergessen")
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


@wege.post("/api/passwort/neu")
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


@wege.post("/api/anmelden")
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
    nutzdaten = nutzer_json(person)
    if SITZUNG_KOPFZEILE:
        # Nur lokal: die Seite legt den Schlüssel ab und reicht ihn nach,
        # falls iOS das Cookie verworfen hat.
        nutzdaten["sitzung"] = schluessel
    antwort = JSONResponse(nutzdaten)
    setze_sitzungscookie(antwort, schluessel, anfrage)
    return antwort


@wege.post("/api/abmelden")
def abmelden(anfrage: Request) -> JSONResponse:
    konten.beende_sitzung(sitzungsschluessel(anfrage))
    antwort = JSONResponse({"abgemeldet": True})
    antwort.delete_cookie(SITZUNG_COOKIE, path="/")
    return antwort


@wege.get("/api/ich")
def ich(person: Nutzer = Depends(angemeldet)) -> dict:
    return nutzer_json(person)


@wege.get("/api/hinweis")
def hinweis(person: Nutzer = Depends(angemeldet)) -> dict:
    """Ein Hinweis des Betreibers im Kundenbereich.

    Nur für Angemeldete: Es ist ein Wort an die eigenen Kunden, nicht
    Werbung an Vorbeigehende. Ohne eingetragenen Text bleibt die Karte
    verborgen — dann ist hier nichts zu zeigen.
    """
    try:
        werte = konten.einstellungen()
    except Exception:          # Datenbank nicht erreichbar
        return {"an": False}

    an = (werte.get("werbung_an") or "").strip().lower() in (
        "1", "ja", "true", "an")
    titel = (werte.get("werbung_titel") or "").strip()
    text = (werte.get("werbung_text") or "").strip()
    ziel = (werte.get("werbung_ziel") or "").strip()

    # Ohne Titel und Ziel gäbe es eine leere Karte mit einem Knopf ins
    # Nichts — dann lieber gar keine.
    if not (an and titel and ziel):
        return {"an": False}

    return {
        "an": True,
        "titel": titel,
        "text": text,
        "knopf": (werte.get("werbung_knopf") or "").strip() or "Mehr erfahren",
        "ziel": ziel,
    }


@wege.post("/api/ich/passwort")
def passwort_wechseln(daten: dict, person: Nutzer = Depends(angemeldet)) -> dict:
    try:
        konten.wechsle_passwort(
            person.id, daten.get("alt", ""), daten.get("neu", "")
        )
    except KontoFehler as fehler:
        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler
    return {"gewechselt": True}


@wege.post("/api/ich/wiederherstellungscode")
def wiederherstellungscode_neu(
    daten: dict, anfrage: Request, person: Nutzer = Depends(angemeldet)
) -> dict:
    """Erzeugt einen neuen Wiederherstellungscode. Der alte verfällt.

    **Der einzige Weg zurück, wenn der Code verloren ging.** Ohne ihn und
    ohne Passwort sind die Daten endgültig zu — das ist der Zweck des
    Tresors, aber es macht diesen Endpunkt notwendig: Wer seinen Code
    verlegt hat, soll ihn ersetzen können, solange er sich noch anmelden
    kann.

    Das Passwort wird trotzdem verlangt. Es öffnet den Datenschlüssel, aus
    dem die neue Hülle entsteht — ohne ihn gäbe es nichts zu verpacken.
    Und es hält jemanden auf, der einen offenen Bildschirm vorfindet.
    """
    passwort = str(daten.get("passwort", ""))
    try:
        _, schluessel = konten.pruefe_anmeldung(person.email, passwort)
    except KontoFehler as fehler:
        raise HTTPException(
            403, detail={"grund": "Das Passwort stimmt nicht."}
        ) from fehler
    if schluessel is None:
        raise HTTPException(409, detail={
            "code": "kein_schluessel",
            "grund": "Für dieses Konto gibt es keinen Datenschlüssel — es "
                     "stammt aus der Zeit vor der Verschlüsselung.",
        })
    return {"wiederherstellungscode": konten.erneuere_code(person.id, schluessel)}


@wege.get("/api/ich/verbrauch")
def eigener_verbrauch(person: Nutzer = Depends(angemeldet)) -> list[dict]:
    return [
        {
            "nummer": zeile["nummer"],
            "kosten_cent": zeile["kosten_cent"],
            "zeitpunkt": zeile["zeitpunkt"].isoformat(timespec="seconds"),
        }
        for zeile in konten.verbrauch_liste(person.id)
    ]
