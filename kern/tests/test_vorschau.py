import shutil

import pytest

from rechnungsblatt_kern import erzeuge_vorschau_png, normalisiere_briefpapier
from rechnungsblatt_kern.testbogen import erzeuge_testbogen

benoetigt_gs = pytest.mark.skipif(
    shutil.which("gs") is None, reason="Ghostscript nicht installiert"
)


@benoetigt_gs
def test_vorschau_png_aus_normalisiertem_bogen(tmp_path):
    upload = tmp_path / "upload.pdf"
    upload.write_bytes(erzeuge_testbogen("gut"))
    norm = normalisiere_briefpapier(upload, tmp_path / "norm.pdf")

    png = erzeuge_vorschau_png(norm.pfad, tmp_path / "vorschau.png", dpi=96)
    daten = png.read_bytes()
    assert daten[:8] == b"\x89PNG\r\n\x1a\n"
    # A4 bei 96 dpi: 210 mm ≈ 794 px Breite (IHDR: Breite in Bytes 16–20)
    breite = int.from_bytes(daten[16:20], "big")
    assert 790 <= breite <= 800
