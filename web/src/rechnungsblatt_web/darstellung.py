"""Modelle der Kontenschicht als JSON.

Eigenes Modul, damit nicht jeder Weg die Innereien von ``Tarif`` und
``Kontingent`` kennen muss — und damit dieselbe Form überall herauskommt.
Vorher baute jeder Endpunkt sein eigenes Nutzer-Dict; drei Stellen, drei
leicht abweichende Formen.
"""

from __future__ import annotations

from . import konten
from .konten import Nutzer


def nutzer_json(person: Nutzer) -> dict:

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
        # Zweiter Faktor: nur OB er an ist und wie viele Ersatzcodes
        # uebrig sind. Das Geheimnis selbst verlaesst den Server nie
        # wieder, nachdem es einmal als QR-Bild herausging.
        "mfa_aktiv": person.mfa_aktiv is not None,
        "mfa_ersatzcodes_offen": (
            konten.offene_ersatzcodes(person.id)
            if person.mfa_aktiv is not None else 0
        ),

        # Gesetzt, wenn ein Abo gekündigt ist und ausläuft. Stripe lässt
        # es bis zum Periodenende laufen — bis dahin steht hier ein
        # Datum, damit das Konto es zeigen kann.
        "abo_endet": (person.abo_endet.isoformat()
                      if person.abo_endet else None),
    }





def tarif_json(tarif: konten.Tarif, intern: bool = False) -> dict:

    """Ein Tarif als JSON.



    ``intern`` gibt zusätzlich die Stripe-Preis-ID heraus. Sie ist kein

    Geheimnis im Sinne eines Schlüssels, gehört aber nicht auf die

    öffentliche Preistafel — dort zählt allein, *dass* der Tarif als Abo

    buchbar ist.

    """

    daten = {

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

    if intern:

        daten["stripe_preis"] = tarif.stripe_preis

    return daten
