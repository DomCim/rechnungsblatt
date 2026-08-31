"""Zahlungen über Stripe: Guthaben aufladen, Abo buchen, Webhook.

Getrennt vom Adminbereich, obwohl beides mit Geld zu tun hat: Hier zahlt
der **Kunde**, dort vergibt der Betreiber Tarife von Hand. Der Webhook ist
zudem der einzige Endpunkt der Anwendung ohne Anmeldung — seine Echtheit
hängt allein an der Signatur.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import bezahlen, konten
from .basis import freigegeben, oeffentliche_adresse, protokoll
from .konten import Nutzer

wege = APIRouter()


# ---------------------------------------------------------------- Zahlungen



@wege.get("/api/bezahlen/angebot")

def bezahl_angebot(person: Nutzer = Depends(freigegeben)) -> dict:

    """Was der Kunde kaufen kann — und ob überhaupt etwas eingerichtet ist."""

    return {

        "eingerichtet": bezahlen.ist_eingerichtet(),

        "aufladungen": bezahlen.aufladungen(),

        # Jeder buchbare Abo-Tarif einzeln: Es gibt mehr als einen, und

        # der Kunde soll sehen, was er bekommt — nicht nur „Abo".

        "abos": [

            {

                "schluessel": t.schluessel,

                "name": t.name,

                "monatsbeitrag_cent": t.monatsbeitrag_cent,

                "inklusiv_rechnungen": t.inklusiv_rechnungen,

                "laufend": t.schluessel == person.tarif,

            }

            for t in bezahlen.abo_tarife()

        ],

        "tarif": person.tarif,

        "hat_kunde": bool(konten.stripe_kunde_von(person.id)),

        "zahlungen": konten.zahlungen_von(person.id),

    }


@wege.post("/api/bezahlen/guthaben")

def bezahl_guthaben(

    daten: dict, anfrage: Request, person: Nutzer = Depends(freigegeben)

) -> dict:

    """Legt eine Checkout-Sitzung an und liefert die Adresse dorthin."""

    try:

        betrag = int(daten.get("betrag_cent", 0))

    except (TypeError, ValueError) as fehler:

        raise HTTPException(422, detail={"grund": "Ungültiger Betrag."}) from fehler

    try:

        ziel = bezahlen.sitzung_guthaben(

            person, betrag, oeffentliche_adresse(anfrage)

        )

    except bezahlen.BezahlFehler as fehler:

        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    return {"weiter": ziel}


@wege.post("/api/bezahlen/abo")

def bezahl_abo(

    daten: dict, anfrage: Request, person: Nutzer = Depends(freigegeben)

) -> dict:

    """Checkout für einen bestimmten Abo-Tarif."""

    schluessel = str(daten.get("tarif", "")).strip()

    if not schluessel:

        raise HTTPException(422, detail={"grund": "Kein Tarif angegeben."})

    try:

        ziel = bezahlen.sitzung_abo(

            person, schluessel, oeffentliche_adresse(anfrage)

        )

    except bezahlen.BezahlFehler as fehler:

        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    return {"weiter": ziel}


@wege.post("/api/bezahlen/verwalten")

def bezahl_verwalten(anfrage: Request, person: Nutzer = Depends(freigegeben)) -> dict:

    """Zu Stripes Portal: Zahlungsmittel ändern, Abo kündigen."""

    try:

        ziel = bezahlen.verwaltungsseite(person, oeffentliche_adresse(anfrage))

    except bezahlen.BezahlFehler as fehler:

        raise HTTPException(422, detail={"grund": str(fehler)}) from fehler

    return {"weiter": ziel}


@wege.post("/api/bezahlen/webhook")

async def bezahl_webhook(anfrage: Request) -> JSONResponse:

    """Nimmt Zahlungsmeldungen von Stripe entgegen.



    Öffentlich erreichbar — die Echtheit hängt allein an der Signatur.

    Der Rohkörper wird gebraucht, weil die Signatur über die unveränderten

    Bytes gebildet wird; ein bereits geparstes JSON passte nicht mehr.

    """

    körper = await anfrage.body()

    signatur = anfrage.headers.get("stripe-signature", "")

    try:

        ereignis = bezahlen.pruefe_und_lies(körper, signatur)

    except bezahlen.BezahlFehler as fehler:

        protokoll.warning("Webhook abgewiesen: %s", fehler)

        # 400, damit Stripe es als Fehlschlag anzeigt — bei 200 bliebe eine

        # falsche Einrichtung unbemerkt.

        raise HTTPException(400, detail={"grund": str(fehler)}) from fehler



    try:

        meldung = bezahlen.verarbeite(ereignis)

    except Exception:

        # Nicht durchreichen: Ein 500 lässt Stripe endlos wiederholen.

        # Der Fehler gehört ins Log, die Quittung geht trotzdem raus.

        protokoll.exception("Webhook konnte nicht verarbeitet werden")

        return JSONResponse({"empfangen": True, "verarbeitet": False})

    protokoll.info("Stripe: %s", meldung)

    return JSONResponse({"empfangen": True})
