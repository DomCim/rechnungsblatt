"""Passkeys mit PRF — Anmelden ohne Passwort, ohne die Ablage zu öffnen.

**Das Problem, das PRF löst.** Rechnungsblatt leitet den Datenschlüssel
aus dem Passwort ab; deshalb kann der Betreiber die Rechnungen nicht
lesen. Ein gewöhnlicher Passkey beweist nur, *wer* jemand ist — er
liefert nichts, woraus sich ein Schlüssel ableiten ließe. Eine reine
Passkey-Anmeldung hätte die verschlüsselte Ablage still ausgehebelt.

Die **PRF-Erweiterung** (WebAuthn Level 3, gebaut auf CTAP2
``hmac-secret``) gibt genau das her: Aus Passkey und einem festen Salz
entsteht bei jeder Anmeldung **dasselbe** 32-Byte-Geheimnis. Damit wird
der Datenschlüssel verpackt — dieselbe Mechanik wie beim Passwort und
beim Wiederherstellungscode, nur die dritte Hülle.

**Kein zweites Sicherheitsniveau.** Ein Passkey entsteht nur, wenn die
Hülle mitkommt — und die kann der Browser nur bilden, wenn PRF wirklich
Ausgabe geliefert hat. Wessen Authenticator es nicht kann (Bitwarden-
Erweiterung, der QR-Weg auf ein fremdes Gerät, ein Sicherheitsschlüssel
am iPhone), bekommt **keinen** Passkey und meldet sich weiter mit
Passwort an. Der Rückfall ist also kein schwacher Passkey, sondern der
Weg, den es ohnehin gibt.

**Was der Server sieht.** Beim Anmelden das PRF-Geheimnis, so wie er beim
Passwort-Anmelden das Passwort sieht — daran ändert sich nichts. Geschützt
ist damit ein gestohlener Datenbank-Abzug, nicht der laufende Server; das
war schon vorher so und steht so in ``tresor``.

**Die Prüfung selbst kommt aus einer Bibliothek.** Anders als bei TOTP
(dreißig Zeilen, gegen die RFC-Vektoren belegt) ist eine WebAuthn-Antwort
nichts, was man selbst prüft: CBOR, COSE, Attestierungsformate,
Signaturen über mehrere Kurven. Ein Fehler darin fällt nicht auf — er
lässt nur den Falschen herein.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import secrets

import webauthn
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

protokoll = logging.getLogger("rechnungsblatt.passkey")

#: Das Salz für die PRF-Ableitung. Fest und öffentlich — es ist kein
#: Geheimnis, sondern nur die Zusicherung, dass immer dieselbe Frage
#: gestellt wird. Wer es änderte, machte jede bestehende Hülle unlesbar.
SALZ = b"rechnungsblatt.datenschluessel.v1"

#: Wie lange eine Aufgabe gilt. Kurz: Sie liegt im Arbeitsspeicher, und
#: eine abgelaufene ist harmlos, eine ewige nicht.
AUFGABE_GILT = dt.timedelta(minutes=5)

# Offene Aufgaben, im Arbeitsspeicher wie SPAETER in `basis`. Ein Neustart
# verwirft sie -- dann faengt der Kunde den Vorgang neu an, mehr passiert
# nicht. Ein zweiter Arbeiter haette sie nicht; die App faehrt mit einem.
_AUFGABEN: dict[str, tuple[bytes, dt.datetime]] = {}


class PasskeyFehler(Exception):
    """Vorgang fehlgeschlagen — die Meldung ist für den Kunden bestimmt."""


def _aufraeumen() -> None:
    jetzt = dt.datetime.now(dt.timezone.utc)
    for kennung in [k for k, (_, bis) in _AUFGABEN.items() if bis < jetzt]:
        _AUFGABEN.pop(kennung, None)


def merke_aufgabe(kennung: str, aufgabe: bytes) -> None:
    _aufraeumen()
    _AUFGABEN[kennung] = (
        aufgabe, dt.datetime.now(dt.timezone.utc) + AUFGABE_GILT
    )


def hole_aufgabe(kennung: str) -> bytes:
    _aufraeumen()
    eintrag = _AUFGABEN.pop(kennung, None)
    if eintrag is None:
        raise PasskeyFehler(
            "Der Vorgang ist abgelaufen. Bitte noch einmal von vorn."
        )
    return eintrag[0]


def b64(rohdaten: bytes) -> str:
    return base64.urlsafe_b64encode(rohdaten).decode("ascii").rstrip("=")


def entb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def anlegen_beginnen(nutzer_id: int, email: str, rp_id: str,
                     vorhandene: list[str]) -> tuple[str, dict]:
    """Die Angaben, mit denen der Browser einen Passkey anlegt.

    ``residentKey`` verlangt einen auffindbaren Passkey: Nur so kann sich
    jemand anmelden, ohne vorher seine E-Mail-Adresse zu tippen.
    ``userVerification`` verlangt Gesicht, Fingerabdruck oder PIN — ohne
    das wäre ein gestohlenes Telefon der ganze Faktor.
    """
    aufgabe = secrets.token_bytes(32)
    optionen = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name="Rechnungsblatt",
        user_id=str(nutzer_id).encode("utf-8"),
        user_name=email,
        user_display_name=email,
        challenge=aufgabe,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=entb64(k)) for k in vorhandene
        ],
    )
    kennung = b64(secrets.token_bytes(16))
    merke_aufgabe(kennung, aufgabe)
    return kennung, options_to_json(optionen)


def anlegen_pruefen(antwort: dict, aufgabe: bytes, rp_id: str,
                    herkunft: str):
    """Prüft die Antwort des Browsers auf das Anlegen."""
    try:
        return webauthn.verify_registration_response(
            credential=antwort,
            expected_challenge=aufgabe,
            expected_rp_id=rp_id,
            expected_origin=herkunft,
            require_user_verification=True,
        )
    except Exception as fehler:                  # die Bibliothek wirft breit
        protokoll.info("Passkey nicht angenommen: %s", fehler)
        raise PasskeyFehler("Der Passkey ließ sich nicht prüfen.") from fehler


def anmelden_beginnen(rp_id: str) -> tuple[str, dict]:
    """Die Aufgabe fürs Anmelden — ohne Liste, der Passkey findet sich selbst."""
    aufgabe = secrets.token_bytes(32)
    optionen = webauthn.generate_authentication_options(
        rp_id=rp_id,
        challenge=aufgabe,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    kennung = b64(secrets.token_bytes(16))
    merke_aufgabe(kennung, aufgabe)
    return kennung, options_to_json(optionen)


def anmelden_pruefen(antwort: dict, aufgabe: bytes, rp_id: str, herkunft: str,
                     oeffentlicher_schluessel: bytes, zaehler: int):
    """Prüft eine Anmeldeantwort gegen den gespeicherten Schlüssel."""
    try:
        return webauthn.verify_authentication_response(
            credential=antwort,
            expected_challenge=aufgabe,
            expected_rp_id=rp_id,
            expected_origin=herkunft,
            credential_public_key=oeffentlicher_schluessel,
            credential_current_sign_count=zaehler,
            require_user_verification=True,
        )
    except Exception as fehler:
        protokoll.info("Anmeldung mit Passkey abgelehnt: %s", fehler)
        raise PasskeyFehler("Der Passkey ließ sich nicht prüfen.") from fehler


def rp_aus_adresse(adresse: str) -> str:
    """Die Domain ohne Schema und Port — WebAuthn will genau die.

    ``https://rechnungsblatt.de`` wird zu ``rechnungsblatt.de``,
    ``http://localhost:18099`` zu ``localhost``. Ein Port darin lehnt der
    Browser wortlos ab, und man sucht lange.
    """
    ohne_schema = adresse.split("://", 1)[-1]
    return ohne_schema.split("/", 1)[0].split(":", 1)[0]
