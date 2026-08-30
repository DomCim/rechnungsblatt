import dataclasses
from decimal import Decimal

import pytest

from rechnungsblatt_kern import (
    Belegtyp,
    Schreibzone,
    berechne_summen,
    erzeuge_epc_daten,
    rendere_blatt,
)


def test_epc_nutzlast_vollstaendig():
    daten = erzeuge_epc_daten(
        name="Muster & Partner GmbH",
        iban="DE14 7805 0000 0001 2345 67",
        betrag=Decimal("238.00"),
        bic="BYLADEM1HOF",
        verwendungszweck="RE-2026-0042",
    )
    zeilen = daten.split("\n")
    assert zeilen[0] == "BCD"
    assert zeilen[1] == "002"
    assert zeilen[2] == "1"  # UTF-8
    assert zeilen[3] == "SCT"
    assert zeilen[4] == "BYLADEM1HOF"
    assert zeilen[5] == "Muster & Partner GmbH"
    assert zeilen[6] == "DE14780500000001234567"  # ohne Leerzeichen
    assert zeilen[7] == "EUR238.00"
    assert zeilen[10] == "RE-2026-0042"


def test_epc_ohne_bic_und_grenzen():
    daten = erzeuge_epc_daten(
        name="X" * 100,  # wird auf 70 gekürzt
        iban="DE14780500000001234567",
        betrag=Decimal("0.00"),  # unter Minimum -> Betrag entfällt
        verwendungszweck="Y" * 200,  # wird auf 140 gekürzt
    )
    zeilen = daten.split("\n")
    assert zeilen[4] == ""  # BIC optional (Version 002)
    assert len(zeilen[5]) == 70
    assert zeilen[7] == ""  # kein Betrag
    assert len(zeilen[10]) == 140

    with pytest.raises(ValueError):
        erzeuge_epc_daten(name=" ", iban="DE14780500000001234567")


def _qr_flaechen_anzahl(blatt: bytes) -> int:
    """Zählt gefüllte Rechtecke im Inhaltsstrom (QR-Module sind 're ... f')."""
    import io
    import zlib

    import pikepdf

    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        inhalt = pdf.pages[0].Contents.read_bytes()
    return inhalt.count(b"re f")


def test_girocode_auf_dem_blatt(rechnung, stammdaten):
    summen = berechne_summen(rechnung)
    mit = rendere_blatt(rechnung, stammdaten, summen, Schreibzone(), girocode=True)
    ohne = rendere_blatt(rechnung, stammdaten, summen, Schreibzone(), girocode=False)
    # Der QR-Code besteht aus hunderten gefüllten Modulen
    assert _qr_flaechen_anzahl(mit) - _qr_flaechen_anzahl(ohne) > 300


def test_girocode_ist_scannbar(rechnung, stammdaten, tmp_path):
    """Ende-zu-Ende: Blatt → PNG → QR dekodieren → EPC-Nutzlast stimmt."""
    import shutil

    pyzbar = pytest.importorskip("pyzbar.pyzbar")
    PIL_Image = pytest.importorskip("PIL.Image")
    if shutil.which("gs") is None:
        pytest.skip("Ghostscript nicht installiert")

    from rechnungsblatt_kern import erzeuge_vorschau_png

    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone(), girocode=True)
    pdf_pfad = tmp_path / "blatt.pdf"
    pdf_pfad.write_bytes(blatt)
    png_pfad = erzeuge_vorschau_png(pdf_pfad, tmp_path / "blatt.png", dpi=200)

    gefunden = pyzbar.decode(PIL_Image.open(png_pfad))
    qr = [code for code in gefunden if code.type == "QRCODE"]
    assert qr, "Kein QR-Code im gerenderten Blatt gefunden"
    nutzlast = qr[0].data.decode("utf-8")
    erwartet = erzeuge_epc_daten(
        name=stammdaten.firmierung,
        iban=stammdaten.iban,
        betrag=summen.brutto,
        bic=stammdaten.bic,
        verwendungszweck=rechnung.verwendungszweck or rechnung.nummer,
    )
    assert nutzlast == erwartet
    assert "EUR238.00" in nutzlast
    assert "DE14780500000001234567" in nutzlast


def test_gutschrift_ohne_girocode(rechnung, stammdaten):
    gutschrift = dataclasses.replace(
        rechnung, typ=Belegtyp.GUTSCHRIFT, bezugs_nummer="RE-2026-0041"
    )
    summen = berechne_summen(gutschrift)
    mit_schalter = rendere_blatt(gutschrift, stammdaten, summen, Schreibzone(), girocode=True)
    ohne = rendere_blatt(gutschrift, stammdaten, summen, Schreibzone(), girocode=False)
    # Gutschrift: kein Zahlungsaufruf, also identisch viele Flächen
    assert _qr_flaechen_anzahl(mit_schalter) == _qr_flaechen_anzahl(ohne)
