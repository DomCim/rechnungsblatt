"""Verschlüsselung der Mandantendaten — das Wallet-Muster.

Die Nutzdaten eines Kontos (Stammdaten, Kunden, Artikel, Vorlagen, die
erzeugten Belege und der Briefbogen) liegen als Dateien unter
``DATEN/nutzer/<id>/``. Verschlüsselt sind sie so, dass **auch der
Betreiber nicht hineinsehen kann**.

Der Aufbau ist der einer Krypto-Wallet:

    Datenschlüssel (32 Byte Zufall)   ← verschlüsselt die Dateien
            │
            ├── Hülle A: mit dem Anmeldepasswort verschlüsselt
            └── Hülle B: mit dem Wiederherstellungscode verschlüsselt

Der Datenschlüssel selbst wird **nie** gespeichert, nur seine beiden
Hüllen. Das Passwort ist nicht der Schlüssel — es öffnet nur die Hülle.
Daraus folgt dreierlei:

* **Der Betreiber kommt nicht heran.** In der Datenbank liegt vom Passwort
  nur ein scrypt-Hash; daraus lässt sich die Hülle nicht öffnen.
* **Passwortwechsel ist verlustfrei.** Es wird nur Hülle A neu
  verschlüsselt; der Datenschlüssel bleibt, keine Datei muss angefasst
  werden.
* **Vergessenes Passwort ist kein Totalverlust**, solange der bei der
  Einrichtung ausgedruckte Wiederherstellungscode existiert — er öffnet
  Hülle B.

Verliert jemand Passwort *und* Code, sind die Daten endgültig fort. Das
ist keine Panne, sondern der Zweck; die Oberfläche muss es deutlich sagen.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# scrypt-Parameter der Hüllen. Bewusst dieselben wie beim Passwort-Hash in
# `konten.py`: n=2^14 braucht rund 16 MB je Ableitung — genug Härte gegen
# Wörterbuchangriffe, ohne die Anmeldung spürbar zu bremsen.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

SCHLUESSEL_BYTES = 32          # AES-256
_SALZ_BYTES = 16
_NONCE_BYTES = 12              # von AES-GCM vorgegeben

# Kennzeichen am Anfang jeder verschlüsselten Datei. Damit lässt sich ein
# noch unverschlüsselter Bestand zweifelsfrei erkennen — nötig für die
# Übernahme alter Konten, die vor dieser Änderung angelegt wurden.
MARKE = b"RBV1"


class TresorFehler(Exception):
    """Entschlüsseln fehlgeschlagen (falsches Passwort oder Daten verfälscht)."""


# ---------------------------------------------------------------- Hüllen

def _aus_geheimnis(geheimnis: str, salz: bytes) -> bytes:
    """Leitet aus Passwort oder Code den Schlüssel für eine Hülle ab."""
    return hashlib.scrypt(
        geheimnis.encode("utf-8"),
        salt=salz,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=SCHLUESSEL_BYTES,
    )


def neuer_datenschluessel() -> bytes:
    """Der eigentliche Schlüssel. Existiert nur im Speicher und in Hüllen."""
    return secrets.token_bytes(SCHLUESSEL_BYTES)


def verpacke(datenschluessel: bytes, geheimnis: str) -> bytes:
    """Legt den Datenschlüssel in eine Hülle: salz || nonce || geheimtext."""
    salz = secrets.token_bytes(_SALZ_BYTES)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    kapsel = AESGCM(_aus_geheimnis(geheimnis, salz))
    return salz + nonce + kapsel.encrypt(nonce, datenschluessel, None)


def oeffne(huelle: bytes, geheimnis: str) -> bytes:
    """Holt den Datenschlüssel aus einer Hülle zurück."""
    if not huelle or len(huelle) < _SALZ_BYTES + _NONCE_BYTES:
        raise TresorFehler("Hülle fehlt oder ist unbrauchbar.")
    salz = huelle[:_SALZ_BYTES]
    nonce = huelle[_SALZ_BYTES:_SALZ_BYTES + _NONCE_BYTES]
    rest = huelle[_SALZ_BYTES + _NONCE_BYTES:]
    try:
        return AESGCM(_aus_geheimnis(geheimnis, salz)).decrypt(nonce, rest, None)
    except InvalidTag as fehler:
        raise TresorFehler("Falsches Passwort oder Hülle verfälscht.") from fehler


# ---------------------------------------------------------------- Dateien

def verschluessle(klartext: bytes, datenschluessel: bytes) -> bytes:
    """Verschlüsselt einen Dateiinhalt: MARKE || nonce || geheimtext.

    Je Datei ein eigenes Nonce — dasselbe zweimal zu verwenden hebt bei
    GCM den Schutz auf.
    """
    nonce = secrets.token_bytes(_NONCE_BYTES)
    kapsel = AESGCM(datenschluessel)
    return MARKE + nonce + kapsel.encrypt(nonce, klartext, None)


def entschluessle(inhalt: bytes, datenschluessel: bytes) -> bytes:
    """Gegenstück zu :func:`verschluessle`.

    Fehlt die Marke, stammt die Datei aus der Zeit vor der Verschlüsselung
    und wird unverändert zurückgegeben. So bleibt ein gewachsener Bestand
    lesbar, bis er beim nächsten Schreiben umgestellt ist.
    """
    if not ist_verschluesselt(inhalt):
        return inhalt
    nonce = inhalt[len(MARKE):len(MARKE) + _NONCE_BYTES]
    rest = inhalt[len(MARKE) + _NONCE_BYTES:]
    try:
        return AESGCM(datenschluessel).decrypt(nonce, rest, None)
    except InvalidTag as fehler:
        raise TresorFehler("Datei lässt sich nicht entschlüsseln.") from fehler


def ist_verschluesselt(inhalt: bytes) -> bool:
    return inhalt[:len(MARKE)] == MARKE


# ---------------------------------------------------------------- Sitzung

def fuer_sitzung(datenschluessel: bytes, sitzungsschluessel: str) -> bytes:
    """Verpackt den Datenschlüssel für die Ablage im Sitzungsdatensatz.

    Der Datenschlüssel muss während der Arbeit verfügbar sein. Läge er
    dafür im Klartext in der Datenbank, wäre der ganze Aufwand umsonst —
    wer die Datenbank liest, hätte ihn.

    Deshalb wird er mit dem **Sitzungsschlüssel** verschlüsselt, den nur
    der Browser des Kunden besitzt: In der Datenbank steht davon nur ein
    SHA-256-Abdruck. Damit gilt eine Ebene höher dieselbe Logik wie bei
    den Hüllen.

    Hier genügt HKDF statt scrypt: Der Sitzungsschlüssel ist bereits 32
    Byte Zufall aus ``secrets`` und nicht zu erraten — die Härtung gegen
    Wörterbuchangriffe, für die scrypt da ist, liefe hier ins Leere und
    würde jede Anfrage um Millisekunden verzögern.
    """
    abgeleitet = hashlib.blake2b(
        sitzungsschluessel.encode("utf-8"),
        digest_size=SCHLUESSEL_BYTES,
        person=b"rb-sitzung",
    ).digest()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    return nonce + AESGCM(abgeleitet).encrypt(nonce, datenschluessel, None)


def aus_sitzung(verpackt: bytes, sitzungsschluessel: str) -> bytes:
    """Gegenstück zu :func:`fuer_sitzung`."""
    if not verpackt or len(verpackt) < _NONCE_BYTES:
        raise TresorFehler("Kein Schlüssel in der Sitzung.")
    abgeleitet = hashlib.blake2b(
        sitzungsschluessel.encode("utf-8"),
        digest_size=SCHLUESSEL_BYTES,
        person=b"rb-sitzung",
    ).digest()
    nonce = verpackt[:_NONCE_BYTES]
    try:
        return AESGCM(abgeleitet).decrypt(nonce, verpackt[_NONCE_BYTES:], None)
    except InvalidTag as fehler:
        raise TresorFehler("Sitzungsschlüssel passt nicht.") from fehler


# ---------------------------------------------------------------- Code

# Ohne I, O, 0, 1 — die verwechselt man beim Abschreiben vom Papier.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def neuer_wiederherstellungscode() -> str:
    """Zweiter Weg zum Datenschlüssel, einmalig bei der Einrichtung gezeigt.

    Fünf Gruppen zu fünf Zeichen aus 32 Zeichen — rund 125 Bit, mehr als
    genug und noch abschreibbar.
    """
    gruppen = [
        "".join(secrets.choice(_ALPHABET) for _ in range(5)) for _ in range(5)
    ]
    return "-".join(gruppen)


def normalisiere_code(eingabe: str) -> str:
    """Macht die Eingabe vergleichbar: Großschreibung, keine Trennzeichen.

    Wer den Code abtippt, setzt Bindestriche und Leerzeichen anders — das
    darf nicht über Erfolg oder Misserfolg entscheiden.
    """
    return "".join(z for z in eingabe.upper() if z in _ALPHABET)


def gleich(a: str, b: str) -> bool:
    """Zeitkonstanter Vergleich, damit die Laufzeit nichts verrät."""
    return hmac.compare_digest(a, b)
