"""Zahlungen über Stripe Checkout — Guthaben und Abo.

Bewusst schmal: Rechnungsblatt kennt genau zwei Vorgänge — jemand lädt
Guthaben auf, oder jemand bucht einen Abo-Tarif. Alles Weitere (Karten,
SEPA-Mandate, Rückbuchungen, Rechnungen an den Kunden) bleibt bei Stripe.

**Abo-Tarife sind Datensätze, kein Sonderfall im Code.** Jeder Tarif mit
einem Monatsbeitrag trägt seine eigene Stripe-Preis-ID; wer einen weiteren
Tarif anbietet, legt ihn im Adminbereich an und trägt die ID ein — hier ist
dafür nichts zu ändern.

**Keine Zahlungsdaten berühren diesen Server.** Der Kunde wird auf eine
von Stripe gehostete Seite geleitet; hierher kommt nur die Nachricht, dass
gezahlt wurde. Damit bleiben die PCI-Anforderungen dort, wo sie hingehören.

Der Zugang steht in der Datenbank (Adminbereich → Zahlungen), nicht in
Umgebungsvariablen: So lässt sich zwischen Test- und Live-Schlüssel
wechseln, ohne den Stack neu zu deployen.

**Das Overwrite bleibt.** Ein Konto, dem der Betreiber von Hand einen
Tarif oder Guthaben gibt, braucht Stripe nicht — die Zahlungswege hier
ergänzen den Adminbereich, sie ersetzen ihn nicht.
"""

from __future__ import annotations

import logging

import stripe

from . import konten

protokoll = logging.getLogger("rechnungsblatt.bezahlen")


class BezahlFehler(Exception):
    """Vorgang fehlgeschlagen — die Meldung ist für den Betreiber bestimmt."""


def _zugang() -> dict[str, str]:
    return konten.einstellungen(mit_geheimnissen=True)


def ist_eingerichtet() -> bool:
    return bool(_zugang().get("stripe_secret"))


def _schluessel() -> str:
    geheim = _zugang().get("stripe_secret", "").strip()
    if not geheim:
        raise BezahlFehler(
            "Kein Stripe-Schlüssel eingetragen (Adminbereich → Zahlungen)."
        )
    return geheim


def aufladungen() -> list[int]:
    """Wählbare Guthabenbeträge in Cent.

    Steht als Liste in der Verwaltung (``10,25,50``), damit sich die
    Staffelung ohne Neubau ändern lässt. Ohne Eintrag drei Vorgaben.
    """
    roh = _zugang().get("stripe_aufladungen", "").strip()
    if not roh:
        return [1000, 2500, 5000]
    betraege = []
    for teil in roh.replace(";", ",").split(","):
        teil = teil.strip().replace(",", ".")
        if not teil:
            continue
        try:
            euro = float(teil)
        except ValueError:
            continue
        if euro > 0:
            betraege.append(int(round(euro * 100)))
    return betraege or [1000, 2500, 5000]


def _kunde(person: konten.Nutzer) -> str:
    """Stripe-Kunde des Kontos; legt ihn beim ersten Mal an.

    Ein fester Kunde je Konto, damit Zahlungen zusammenlaufen und ein Abo
    später auffindbar bleibt. Die Nutzer-ID reist als Metadatum mit — sie
    ist der einzige verlässliche Weg vom Webhook zurück zum Konto.
    """
    vorhanden = konten.stripe_kunde_von(person.id)
    if vorhanden:
        return vorhanden
    stripe.api_key = _schluessel()
    neu = stripe.Customer.create(
        email=person.email,
        metadata={"nutzer_id": str(person.id)},
    )
    konten.merke_stripe_kunde(person.id, neu.id)
    return neu.id


def sitzung_guthaben(person: konten.Nutzer, betrag_cent: int, basis: str) -> str:
    """Checkout für eine einmalige Guthabenaufladung. Liefert die Adresse."""
    if betrag_cent not in aufladungen():
        # Nur vorgegebene Beträge: Sonst könnte ein manipulierter Aufruf
        # ein Guthaben von einem Cent kaufen.
        raise BezahlFehler("Unbekannter Betrag.")
    stripe.api_key = _schluessel()
    sitzung = stripe.checkout.Session.create(
        mode="payment",
        customer=_kunde(person),
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": betrag_cent,
                "product_data": {"name": "Guthaben für Rechnungsblatt"},
            },
            "quantity": 1,
        }],
        success_url=f"{basis}/app/konto?bezahlt=1",
        cancel_url=f"{basis}/app/konto?abgebrochen=1",
        metadata={"nutzer_id": str(person.id), "art": "guthaben"},
    )
    return sitzung.url


def abo_tarife() -> list[konten.Tarif]:
    """Sichtbare Tarife, die als Abo buchbar sind.

    Buchbar heißt: eine Stripe-Preis-ID hinterlegt. Ein Tarif mit
    Monatsbeitrag, aber ohne ID, erscheint auf der Preistafel und ist
    trotzdem nicht buchbar — dann fehlt der Eintrag im Adminbereich.
    """
    return [
        t for t in konten.tarife(nur_sichtbare=True) if t.stripe_preis.strip()
    ]


def sitzung_abo(person: konten.Nutzer, schluessel: str, basis: str) -> str:
    """Checkout für einen Abo-Tarif. Der Preis steht am Tarif."""
    try:
        gewuenscht = konten.tarif(schluessel)
    except konten.KontoFehler as fehler:
        raise BezahlFehler(str(fehler)) from fehler
    if not gewuenscht.sichtbar:
        # Ein unsichtbarer Tarif ist zurückgezogen; ihn über einen
        # gebastelten Aufruf zu buchen, wäre ein Weg an der Entscheidung
        # des Betreibers vorbei.
        raise BezahlFehler("Dieser Tarif wird nicht angeboten.")
    preis = gewuenscht.stripe_preis.strip()
    if not preis:
        raise BezahlFehler(
            f"Für den Tarif „{gewuenscht.name}“ ist keine Stripe-Preis-ID "
            "eingetragen (Adminbereich → Tarife)."
        )
    stripe.api_key = _schluessel()
    sitzung = stripe.checkout.Session.create(
        mode="subscription",
        customer=_kunde(person),
        line_items=[{"price": preis, "quantity": 1}],
        success_url=f"{basis}/app/konto?bezahlt=1",
        cancel_url=f"{basis}/app/konto?abgebrochen=1",
        # Der Tarif reist mit: Der Webhook erfährt sonst nicht, welcher
        # der Abo-Tarife gebucht wurde.
        metadata={
            "nutzer_id": str(person.id),
            "art": "abo",
            "tarif": gewuenscht.schluessel,
        },
    )
    return sitzung.url


def verwaltungsseite(person: konten.Nutzer, basis: str) -> str:
    """Stripes eigene Seite zum Kündigen und Zahlungsmittel ändern.

    Kündigung selbst nachzubauen wäre Aufwand ohne Gewinn — und ein
    fehlender Kündigungsweg ist in Deutschland ein rechtliches Problem.
    """
    kunde = konten.stripe_kunde_von(person.id)
    if not kunde:
        raise BezahlFehler("Für dieses Konto gibt es noch keine Zahlung.")
    stripe.api_key = _schluessel()
    sitzung = stripe.billing_portal.Session.create(
        customer=kunde, return_url=f"{basis}/app/konto"
    )
    return sitzung.url


# ---------------------------------------------------------------- Webhook

def pruefe_und_lies(körper: bytes, signatur: str) -> dict:
    """Prüft die Signatur und liefert das Ereignis.

    **Ohne diese Prüfung könnte jeder Guthaben verschenken**: Der Endpunkt
    ist öffentlich erreichbar, und ein erfundener „Zahlung eingegangen"-
    Aufruf wäre sonst nicht von einem echten zu unterscheiden.
    """
    geheim = _zugang().get("stripe_webhook_secret", "").strip()
    if not geheim:
        raise BezahlFehler("Kein Webhook-Geheimnis eingetragen.")
    try:
        ereignis = stripe.Webhook.construct_event(körper, signatur, geheim)
    except (ValueError, stripe.SignatureVerificationError) as fehler:
        raise BezahlFehler(f"Signatur stimmt nicht: {fehler}") from fehler
    # Als dict weitergeben: Die Bibliothek liefert ein Event-Objekt, das
    # kein .get() kennt — und der Rest dieses Moduls soll von ihrem
    # Datentyp nichts wissen müssen.
    return ereignis.to_dict()


def _nutzer_aus_ereignis(objekt: dict) -> konten.Nutzer | None:
    """Findet das Konto — erst über die Metadaten, dann über den Kunden."""
    kennung = (objekt.get("metadata") or {}).get("nutzer_id")
    if kennung:
        try:
            person = konten.nutzer(int(kennung))
        except (TypeError, ValueError):
            person = None
        if person:
            return person
    kunde = objekt.get("customer")
    return konten.nutzer_zu_stripe_kunde(kunde) if kunde else None


def _gebuchter_tarif(objekt: dict) -> str:
    """Welcher Abo-Tarif wurde gebucht?

    Steht in den Metadaten der Checkout-Sitzung. Fehlt er — etwa bei einem
    Abo, das jemand direkt in Stripe angelegt hat —, sucht die Funktion den
    Tarif über die Preis-ID. Erst wenn auch das nichts findet, bleibt der
    Standardtarif: lieber zu wenig gewährt als das falsche Kontingent.
    """
    aus_metadaten = (objekt.get("metadata") or {}).get("tarif")
    if aus_metadaten:
        return str(aus_metadaten)
    posten = ((objekt.get("items") or {}).get("data") or [])
    for eintrag in posten:
        preis = (eintrag.get("price") or {}).get("id")
        if not preis:
            continue
        for kandidat in konten.tarife():
            if kandidat.stripe_preis.strip() == preis:
                return kandidat.schluessel
    return konten.STANDARD_TARIF


def verarbeite(ereignis: dict) -> str:
    """Verbucht ein geprüftes Ereignis. Liefert eine Zeile fürs Protokoll.

    Behandelt werden nur die vier Fälle, die den Kontostand ändern. Alles
    andere quittiert die App mit 200, ohne etwas zu tun — sonst wiederholt
    Stripe die Zustellung endlos.
    """
    art = ereignis.get("type", "")
    objekt = (ereignis.get("data") or {}).get("object") or {}

    if art == "checkout.session.completed":
        person = _nutzer_aus_ereignis(objekt)
        if person is None:
            return f"{art}: kein Konto zuzuordnen"
        if objekt.get("mode") == "subscription":
            gebucht = _gebuchter_tarif(objekt)
            konten.setze_abo(person.id, objekt.get("subscription"), gebucht)
            return f"{art}: Tarif {gebucht} für {person.email}"
        betrag = int(objekt.get("amount_total") or 0)
        neu = konten.verbuche_zahlung(
            objekt.get("id", ""), person.id, "guthaben", betrag
        )
        return (f"{art}: {betrag} ct für {person.email}"
                if neu else f"{art}: schon gebucht")

    if art == "invoice.paid":
        # Folgemonate eines Abos. Ohne diesen Fall liefe das Abo nach dem
        # ersten Monat weiter, ohne dass eine Zahlung ankommt.
        person = _nutzer_aus_ereignis(objekt)
        if person is None:
            return f"{art}: kein Konto zuzuordnen"
        konten.verbuche_zahlung(
            objekt.get("id", ""), person.id, "abo",
            int(objekt.get("amount_paid") or 0),
        )
        return f"{art}: Abo verlängert für {person.email}"

    if art in ("customer.subscription.deleted", "invoice.payment_failed"):
        person = _nutzer_aus_ereignis(objekt)
        if person is None:
            return f"{art}: kein Konto zuzuordnen"
        # Abo endet: zurück auf den Standardtarif. Das Guthaben bleibt —
        # es ist bezahlt und hat mit dem Abo nichts zu tun.
        konten.setze_abo(person.id, None, konten.STANDARD_TARIF)
        return f"{art}: Abo beendet für {person.email}"

    return f"{art}: nicht behandelt"
