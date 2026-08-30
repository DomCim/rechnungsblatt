import io

import pikepdf
import pytest

from rechnungsblatt_kern import (
    Blattgestaltung,
    Layoutvariante,
    Schreibzone,
    SchriftNichtGefunden,
    Schriftgrad,
    berechne_summen,
    erzeuge_gestaltungsvorschau,
    registriere_schriftart,
    rendere_blatt,
    verfuegbare_schriften,
)
from rechnungsblatt_kern.normalisierung import _benutzte_schriften


def test_katalog_schriften_verfuegbar():
    schluessel = {schrift.schluessel for schrift in verfuegbare_schriften()}
    # Die kuratierten Pakete (Dockerfile/CI) müssen alle fünf liefern
    assert {"liberation-sans", "liberation-serif", "carlito", "caladea", "dejavu-sans"} <= schluessel


def test_unbekannte_schrift_wird_abgelehnt():
    with pytest.raises(SchriftNichtGefunden):
        registriere_schriftart("comic-sans")


@pytest.mark.parametrize("layout", list(Layoutvariante))
@pytest.mark.parametrize("grad", list(Schriftgrad))
def test_jede_variante_rendert(rechnung, stammdaten, layout, grad):
    gestaltung = Blattgestaltung(schrift="carlito", schriftgrad=grad, layout=layout)
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone(), gestaltung=gestaltung)
    assert blatt.startswith(b"%PDF-")


@pytest.mark.parametrize(
    "schluessel", ["liberation-sans", "liberation-serif", "carlito", "caladea", "dejavu-sans"]
)
def test_jede_katalogschrift_wird_eingebettet(rechnung, stammdaten, schluessel):
    gestaltung = Blattgestaltung(schrift=schluessel)
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone(), gestaltung=gestaltung)
    with pikepdf.open(io.BytesIO(blatt)) as pdf:
        benutzte = list(_benutzte_schriften(pdf.pages[0]))
        assert len(benutzte) >= 2
        for schrift, name in benutzte:
            deskriptor = schrift.get("/FontDescriptor", None)
            assert deskriptor is not None, f"{name}: ohne FontDescriptor"
            assert any(
                key in deskriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
            ), f"{name}: nicht eingebettet"


def test_belegdaten_als_zeile_rendert(rechnung, stammdaten):
    gestaltung = Blattgestaltung(belegdaten_als_zeile=True)
    summen = berechne_summen(rechnung)
    blatt = rendere_blatt(rechnung, stammdaten, summen, Schreibzone(), gestaltung=gestaltung)
    assert blatt.startswith(b"%PDF-")


def test_gestaltungsvorschau_ohne_briefpapier():
    vorschau = erzeuge_gestaltungsvorschau(
        Schreibzone(), Blattgestaltung(layout=Layoutvariante.MODERN)
    )
    assert vorschau.startswith(b"%PDF-")
    with pikepdf.open(io.BytesIO(vorschau)) as pdf:
        assert len(pdf.pages) == 1


def test_gestaltungsvorschau_mit_briefpapier(tmp_path):
    import shutil

    from rechnungsblatt_kern import normalisiere_briefpapier
    from rechnungsblatt_kern.testbogen import erzeuge_testbogen

    if shutil.which("gs") is None:
        pytest.skip("Ghostscript nicht installiert")
    upload = tmp_path / "upload.pdf"
    upload.write_bytes(erzeuge_testbogen("gut"))
    norm = normalisiere_briefpapier(upload, tmp_path / "norm.pdf")
    vorschau = erzeuge_gestaltungsvorschau(
        Schreibzone(kopf_ende_mm=52, fuss_beginn_mm=25),
        Blattgestaltung(schrift="caladea", layout=Layoutvariante.KOMPAKT),
        briefpapier_norm=norm.pfad,
    )
    assert vorschau.startswith(b"%PDF-")
