"""GiroCode (EPC-QR-Code nach EPC069-12) für SEPA-Überweisungen.

Der Kunde scannt den Code mit seiner Banking-App — Empfänger, IBAN, Betrag
und Verwendungszweck sind vorausgefüllt. Gezeichnet wird der Code als
Vektorgrafik (schwarze Rechtecke) direkt auf das Blatt: kein Rasterbild,
kein neuer Farbraum, die PDF/A-Garantie bleibt unberührt.
"""

from __future__ import annotations

from decimal import Decimal

import qrcode
from reportlab.lib.units import mm

_BETRAG_MIN = Decimal("0.01")
_BETRAG_MAX = Decimal("999999999.99")


def erzeuge_epc_daten(
    name: str,
    iban: str,
    betrag: Decimal | None = None,
    bic: str | None = None,
    verwendungszweck: str | None = None,
) -> str:
    """Baut die EPC069-12-Nutzlast (Version 002, UTF-8, SCT).

    Feldgrenzen laut Spezifikation: Name max. 70 Zeichen, unstrukturierter
    Verwendungszweck max. 140, Betrag 0,01–999 999 999,99 EUR (außerhalb
    wird er weggelassen — die App fragt dann nach).
    """
    if not name.strip():
        raise ValueError("GiroCode braucht den Namen des Zahlungsempfängers.")
    iban_kompakt = iban.replace(" ", "").upper()
    if not iban_kompakt:
        raise ValueError("GiroCode braucht eine IBAN.")

    betrag_zeile = ""
    if betrag is not None and _BETRAG_MIN <= betrag <= _BETRAG_MAX:
        betrag_zeile = f"EUR{betrag:.2f}"

    zeilen = [
        "BCD",  # Service Tag
        "002",  # Version (BIC optional)
        "1",  # Zeichensatz UTF-8
        "SCT",  # SEPA Credit Transfer
        (bic or "").strip(),
        name.strip()[:70],
        iban_kompakt,
        betrag_zeile,
        "",  # Purpose-Code (ungenutzt)
        "",  # strukturierte Referenz (ungenutzt — wir nutzen Freitext)
        (verwendungszweck or "").strip()[:140],
    ]
    # Leere Zeilen am Ende dürfen entfallen
    while zeilen and not zeilen[-1]:
        zeilen.pop()
    return "\n".join(zeilen)


def zeichne_girocode(canvas, daten: str, x: float, y: float, groesse_mm: float) -> None:
    """Zeichnet den QR-Code als schwarze Vektor-Rechtecke.

    ``x``/``y`` ist die linke untere Ecke, ``groesse_mm`` die Kantenlänge.
    Fehlerkorrektur M ist für den GiroCode vorgeschrieben.
    """
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(daten)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    module = len(matrix)
    kante = groesse_mm * mm / module

    canvas.saveState()
    canvas.setFillColorRGB(0, 0, 0)
    # Ruhezone: weißer Grund, ein Modul Rand rundum
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(x - kante, y - kante, (module + 2) * kante, (module + 2) * kante, stroke=0, fill=1)
    canvas.setFillColorRGB(0, 0, 0)
    for zeile_nr, zeile in enumerate(matrix):
        for spalte_nr, dunkel in enumerate(zeile):
            if dunkel:
                canvas.rect(
                    x + spalte_nr * kante,
                    y + (module - 1 - zeile_nr) * kante,
                    kante,
                    kante,
                    stroke=0,
                    fill=1,
                )
    canvas.restoreState()
