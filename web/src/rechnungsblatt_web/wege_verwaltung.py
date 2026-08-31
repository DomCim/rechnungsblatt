"""Der Adminbereich: Konten, Tarife, Betriebseinstellungen, Zahlungen.

Alles hier hängt an ``Depends(verwalter)`` — ohne Adminrolle kommt niemand
hinein. Die Endpunkte selbst prüfen das nicht noch einmal.
"""

from __future__ import annotations

import re
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import bezahlen, dkim, konten, post, statistik
from .basis import (
    datenverzeichnis,
    freigegeben,
    oeffentliche_adresse,
    protokoll,
    verwalter,
    wurzel_von,
)
from .darstellung import tarif_json
from .konten import KontoFehler, Nutzer

wege = APIRouter()


@wege.get("/api/verwaltung/nutzer")

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


@wege.post("/api/verwaltung/nutzer/{nutzer_id}/status")

def verwaltung_status(

    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)

) -> dict:

    return _verwaltung_aendern(

        lambda: konten.setze_status(nutzer_id, daten.get("status", ""))

    )


@wege.post("/api/verwaltung/nutzer/{nutzer_id}/rolle")

def verwaltung_rolle(

    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)

) -> dict:

    return _verwaltung_aendern(

        lambda: konten.setze_rolle(nutzer_id, daten.get("rolle", ""))

    )


@wege.post("/api/verwaltung/nutzer/{nutzer_id}/tarif")

def verwaltung_tarif(

    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)

) -> dict:

    return _verwaltung_aendern(

        lambda: konten.setze_tarif(nutzer_id, daten.get("tarif", ""))

    )


@wege.post("/api/verwaltung/nutzer/{nutzer_id}/guthaben")

def verwaltung_guthaben(

    nutzer_id: int, daten: dict, _: Nutzer = Depends(verwalter)

) -> dict:

    try:

        cent = int(daten.get("cent", 0))

    except (TypeError, ValueError) as fehler:

        raise HTTPException(422, detail={"grund": "Betrag muss ganzzahlig sein."}) from fehler

    return _verwaltung_aendern(lambda: konten.buche_guthaben(nutzer_id, cent))


@wege.delete("/api/verwaltung/nutzer/{nutzer_id}")

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

    daten = datenverzeichnis()
    verzeichnis = daten / "nutzer" / str(nutzer_id)

    # Pfad absichern: nutzer_id kommt aus der URL. FastAPI erzwingt zwar

    # int, aber der Check kostet nichts und hält auch künftige Umbauten

    # davon ab, hier versehentlich außerhalb von DATEN zu löschen.

    erwartet = (daten / "nutzer").resolve()

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


@wege.get("/api/verwaltung/dubletten")

def verwaltung_dubletten(_: Nutzer = Depends(verwalter)) -> list[dict]:

    """Konten, die sich ein Steuermerkmal teilen.


    Nur eine Meldung — wer hier auftaucht, ist nicht zwingend ein

    Missbrauchsfall: Betriebsübergaben und Steuernummernwechsel sehen

    genauso aus.

    """

    return konten.konten_mit_gleichem_steuermerkmal()


@wege.get("/api/verwaltung/zahlen")

def verwaltung_zahlen(_: Nutzer = Depends(verwalter)) -> dict:

    """Konten und Belege in Zahlen. Plausible zählt daneben die Aufrufe."""

    return konten.betriebszahlen()


@wege.get("/api/verwaltung/einstellungen")

def verwaltung_einstellungen(_: Nutzer = Depends(verwalter)) -> dict:

    """Betriebseinstellungen. Das SMTP-Passwort kommt NUR als Punkte zurück."""

    werte = konten.einstellungen()

    werte["eingerichtet"] = post.ist_eingerichtet()

    return werte


@wege.put("/api/verwaltung/einstellungen")

def verwaltung_einstellungen_setzen(

    daten: dict, _: Nutzer = Depends(verwalter)

) -> dict:

    konten.setze_einstellungen({k: str(v) for k, v in daten.items()})

    werte = konten.einstellungen()

    werte["eingerichtet"] = post.ist_eingerichtet()

    return werte


@wege.post("/api/verwaltung/testmail")

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

        # Sagen, WAS fehlt, und zwar aus dem Stand, den der Versand

        # gerade gelesen hat. „Kein SMTP eingerichtet" vor einem

        # ausgefüllten Formular ist nicht nur unhilfreich, sondern

        # irreführend — dann steht in der Datenbank etwas anderes als

        # auf dem Bildschirm, und genau das gehört gezeigt.

        werte = konten.einstellungen()

        stand = {name: (werte.get(schluessel) or "").strip()

                 for schluessel, name in (("smtp_host", "Server"),

                                          ("smtp_absender", "Absender"))}

        fehlt = [name for name, wert in stand.items() if not wert]

        raise HTTPException(422, detail={"grund":

            f"Es fehlt noch: {' und '.join(fehlt)}. Gespeichert ist gerade: "

            + ", ".join(f"{n}={w or '(leer)'}" for n, w in stand.items())

            + ". Zuerst „Speichern“ drücken — der Versand liest den "

              "gespeicherten Stand, nicht das Formular."

            if fehlt else

            "Kein SMTP eingerichtet — nichts verschickt."})

    return {"verschickt": True, "an": ziel}


@wege.get("/api/verwaltung/dkim")

def verwaltung_dkim(_: Nutzer = Depends(verwalter)) -> dict:

    """Zustand der Unterschrift und der DNS-Eintrag, der dazu gehört.


    Ohne den veröffentlichten Eintrag nützt die Unterschrift nichts — der

    Empfänger holt den öffentlichen Schlüssel dort ab.

    """

    werte = konten.einstellungen(mit_geheimnissen=True)

    domain = (werte.get("dkim_domain") or "").strip()

    selektor = (werte.get("dkim_selektor") or "").strip()

    pem = (werte.get("dkim_schluessel") or "").strip()

    absender = (werte.get("smtp_absender") or "").strip()


    antwort: dict = {

        "eingerichtet": bool(domain and selektor and pem),

        "unvollstaendig": bool((domain or selektor or pem)

                               and not (domain and selektor and pem)),

        "absender": absender,

        # Ein Absender ohne @ ist keine Adresse. Der Mailserver lehnt ihn

        # ab, lange bevor DKIM eine Rolle spielt — das gehört gemeldet,

        # nicht stillschweigend hingenommen.

        "absender_gueltig": bool(absender and dkim.domain_von(absender)),

        "passt": bool(domain and absender and dkim.passt(domain, absender)),

    }

    if antwort["eingerichtet"]:

        try:

            antwort["dns"] = dkim.dns_eintrag(pem, selektor, domain)

        except dkim.DkimFehler as fehler:

            antwort["fehler"] = str(fehler)

    return antwort


@wege.post("/api/verwaltung/dkim/schluessel")

def verwaltung_dkim_schluessel(_: Nutzer = Depends(verwalter)) -> dict:

    """Erzeugt ein Schlüsselpaar und legt den privaten Teil ab.


    Bequemer und sicherer, als den Betreiber mit openssl auf der

    Kommandozeile zu lassen — und der private Schlüssel verlässt den

    Server dabei nie.

    """

    werte = konten.einstellungen()

    domain = (werte.get("dkim_domain") or "").strip()

    selektor = (werte.get("dkim_selektor") or "").strip()

    if not (domain and selektor):

        raise HTTPException(422, detail={

            "grund": "Erst Domain und Selektor eintragen und speichern."

        })

    pem = dkim.erzeuge_schluesselpaar()

    konten.setze_einstellungen({"dkim_schluessel": pem})

    return {"dns": dkim.dns_eintrag(pem, selektor, domain)}


@wege.get("/api/verwaltung/besucher")

def verwaltung_besucher(

    zeitraum: str = "30t", _: Nutzer = Depends(verwalter)

) -> dict:

    """Besucherzahlen aus Plausible.


    Getrennt von den Betriebszahlen: Die kommen aus der eigenen Datenbank

    und sind immer da; diese hier hängen an einem fremden Dienst und

    fallen aus, ohne dass deshalb die Übersicht leer bleiben darf.

    """

    if zeitraum not in statistik.ZEITRAEUME:

        # Nicht `in` auf ein dict mit Vorgabewert: Ein erfundener Zeitraum

        # soll abgewiesen werden, nicht stillschweigend zu 30 Tagen werden.

        raise HTTPException(422, detail={"grund": "Unbekannter Zeitraum."})

    if statistik.zugang() is None:

        # Kein Fehler, sondern ein Zustand: Gezählt wird trotzdem, es fehlt

        # nur der Schlüssel zum Lesen.

        return {"eingerichtet": False}

    try:

        daten = statistik.auswertung(zeitraum)

    except statistik.StatistikFehler as fehler:

        protokoll.warning("Besucherzahlen nicht lesbar: %s", fehler)

        return {"eingerichtet": True, "fehler": str(fehler)}

    return {"eingerichtet": True, **daten}


@wege.get("/api/verwaltung/tarife")

def verwaltung_tarife(_: Nutzer = Depends(verwalter)) -> list[dict]:

    return [tarif_json(tarif, intern=True) for tarif in konten.tarife()]


@wege.put("/api/verwaltung/tarife/{schluessel}")

def verwaltung_tarif_speichern(

    schluessel: str, daten: dict, _: Nutzer = Depends(verwalter)

) -> dict:

    # Der Schlüssel steht in der Adresse und haftet an jedem Konto — ein

    # Leerzeichen oder Umlaut darin fiele erst später auf.

    if not re.fullmatch(r"[a-z0-9_-]{2,32}", schluessel):

        raise HTTPException(422, detail={"grund":

            "Der Schlüssel darf nur Kleinbuchstaben, Ziffern, Bindestrich "

            "und Unterstrich enthalten (2 bis 32 Zeichen)."})

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

            stripe_preis=str(daten.get("stripe_preis", "")).strip(),

        )

    except (TypeError, ValueError) as fehler:

        raise HTTPException(422, detail={"grund": f"Ungültiger Tarif: {fehler}"}) from fehler

    return tarif_json(konten.speichere_tarif(neu), intern=True)


@wege.delete("/api/verwaltung/tarife/{schluessel}")

def verwaltung_tarif_loeschen(

    schluessel: str, _: Nutzer = Depends(verwalter)

) -> dict:

    """Entfernt einen Tarif, auf dem niemand mehr sitzt."""

    try:

        konten.loesche_tarif(schluessel)

    except KontoFehler as fehler:

        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    return {"geloescht": schluessel}
