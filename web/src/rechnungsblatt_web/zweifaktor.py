"""Zweiter Faktor: zeitbasierte Einmalkennwörter (TOTP, RFC 6238).

**Warum selbst gebaut.** Es sind dreißig Zeilen Standardbibliothek —
HMAC-SHA1 über den Zeitschritt, vier Bytes daraus, modulo eine Million.
Eine Abhängigkeit dafür aufzunehmen hieße, den Zulieferweg für etwas zu
öffnen, das sich gegen die Prüfwerte der Norm beweisen lässt (siehe
``test_zweifaktor.py``). Dieselbe Abwägung wie bei DKIM.

**Warum TOTP und nicht mehr.** Der zweite Faktor sitzt **vor** der
Anmeldung und rührt den Datenschlüssel nicht an. Der wird weiterhin
allein aus dem Passwort abgeleitet (siehe ``tresor``); MFA ändert daran
nichts und kann die verschlüsselte Ablage deshalb auch nicht aushebeln.

**Was das für den Betreiber heißt.** Er kann den zweiten Faktor eines
ausgesperrten Kunden zurücksetzen — und kommt damit trotzdem nicht an
dessen Rechnungen. Ohne das Passwort bleibt der Datenschlüssel verpackt.
Ein Rücksetzweg ist hier also keine Hintertür, sondern nur Kundendienst.

**Uhren gehen falsch.** Geprüft wird der aktuelle Zeitschritt und je
einer davor und danach — das deckt anderthalb Minuten Abweichung ab.
Mehr Fenster hieße, das Zeitfenster eines abgefangenen Codes zu
verlängern.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

#: Länge eines Codes. Sechs Stellen sind der Standard aller gängigen Apps.
STELLEN = 6
#: Dauer eines Zeitschritts in Sekunden.
SCHRITT = 30
#: Wie viele Schritte vor und nach dem aktuellen noch gelten.
FENSTER = 1
#: So viele Ersatzcodes bekommt ein Konto beim Einschalten.
ERSATZCODES = 8


def neues_geheimnis() -> str:
    """160 Bit Zufall als Base32 — das Format, das jede App erwartet."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_fuer(geheimnis: str, zaehler: int, stellen: int = STELLEN) -> str:
    """Ein HOTP-Wert nach RFC 4226 — TOTP ist HOTP über dem Zeitschritt."""
    auffuellen = "=" * (-len(geheimnis) % 8)
    schluessel = base64.b32decode(geheimnis.upper() + auffuellen)
    abdruck = hmac.new(schluessel, struct.pack(">Q", zaehler), hashlib.sha1).digest()
    # Dynamic Truncation: die letzten vier Bit sagen, wo die vier Bytes
    # beginnen, die den Code tragen.
    versatz = abdruck[-1] & 0x0F
    ausschnitt = struct.unpack(">I", abdruck[versatz:versatz + 4])[0] & 0x7FFFFFFF
    return str(ausschnitt % (10 ** stellen)).zfill(stellen)


def code_jetzt(geheimnis: str, zeitpunkt: float | None = None) -> str:
    """Der Code, der in diesem Augenblick gilt — für Tests und die Vorschau."""
    jetzt = time.time() if zeitpunkt is None else zeitpunkt
    return _code_fuer(geheimnis, int(jetzt // SCHRITT))


def stimmt(geheimnis: str, eingabe: str, zeitpunkt: float | None = None) -> bool:
    """Prüft einen eingegebenen Code gegen das Geheimnis.

    Verglichen wird mit ``compare_digest``: Ein Vergleich, der beim ersten
    abweichenden Zeichen abbricht, verrät über die Laufzeit, wie viele
    Stellen stimmten.
    """
    eingabe = (eingabe or "").strip().replace(" ", "")
    if not eingabe.isdigit() or len(eingabe) != STELLEN or not geheimnis:
        return False
    jetzt = time.time() if zeitpunkt is None else zeitpunkt
    schritt = int(jetzt // SCHRITT)
    for versatz in range(-FENSTER, FENSTER + 1):
        if hmac.compare_digest(_code_fuer(geheimnis, schritt + versatz), eingabe):
            return True
    return False


def otpauth_adresse(email: str, geheimnis: str, herausgeber: str = "Rechnungsblatt") -> str:
    """Die Adresse, die als QR-Bild in der App landet."""
    kennung = quote(f"{herausgeber}:{email}", safe="")
    return (
        f"otpauth://totp/{kennung}?secret={geheimnis}"
        f"&issuer={quote(herausgeber, safe='')}"
        f"&algorithm=SHA1&digits={STELLEN}&period={SCHRITT}"
    )


def qr_svg(adresse: str, kantenlaenge: int = 220) -> str:
    """Der QR-Code als eingebettetes SVG.

    Kein PNG und keine zweite Ablage: Das Bild entsteht bei jedem Aufruf
    neu und darf nirgends liegen bleiben — es trägt das Geheimnis.
    """
    import qrcode                       # ueber den Kern ohnehin vorhanden

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(adresse)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    module = len(matrix)

    kaestchen = []
    for zeile_nr, zeile in enumerate(matrix):
        for spalte_nr, gesetzt in enumerate(zeile):
            if gesetzt:
                kaestchen.append(f'<rect x="{spalte_nr}" y="{zeile_nr}" width="1" height="1"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {module} {module}" '
        f'width="{kantenlaenge}" height="{kantenlaenge}" role="img" '
        f'aria-label="QR-Code zum Einrichten">'
        f'<rect width="{module}" height="{module}" fill="#fff"/>'
        f'<g fill="#000">{"".join(kaestchen)}</g></svg>'
    )


def neue_ersatzcodes(anzahl: int = ERSATZCODES) -> list[str]:
    """Einmalcodes für den Fall, dass das Telefon weg ist.

    Ohne sie wäre ein verlorenes Telefon gleichbedeutend mit einem
    verlorenen Konto — und der Betreiber müsste jedes Mal von Hand
    zurücksetzen.
    """
    return [
        f"{secrets.randbelow(10**5):05d}-{secrets.randbelow(10**5):05d}"
        for _ in range(anzahl)
    ]
