"""Integrationstests: Testbogen -> Normalisierung (Ghostscript) -> PDF/A-3B.

Die inhaltliche PDF/A-Prüfung übernimmt der Mustang-Validator in der CI
(siehe .github/workflows/ci.yml); hier wird die Struktur geprüft, die der
Prototyp als notwendig bewiesen hat.
"""

import io
import shutil

import pikepdf
import pytest

from rechnungsblatt_kern import (
    NormalisierungAbgelehnt,
    Schreibzone,
    erzeuge_rechnung,
    normalisiere_briefpapier,
    pruefe_upload,
)
from rechnungsblatt_kern.testbogen import erzeuge_testbogen

import datetime as dt

ZEITPUNKT = dt.datetime(2026, 8, 21, 12, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))

benoetigt_gs = pytest.mark.skipif(
    shutil.which("gs") is None, reason="Ghostscript nicht installiert"
)


@pytest.fixture(params=["gut", "boese"])
def briefpapier_norm(request, tmp_path):
    upload = tmp_path / "upload.pdf"
    upload.write_bytes(erzeuge_testbogen(request.param))
    ausgabe = tmp_path / "briefpapier_norm.pdf"
    ergebnis = normalisiere_briefpapier(upload, ausgabe)
    return ergebnis


@benoetigt_gs
def test_normalisierung_meldet_schriftersetzung(tmp_path):
    upload = tmp_path / "boese.pdf"
    upload.write_bytes(erzeuge_testbogen("boese"))
    ergebnis = normalisiere_briefpapier(upload, tmp_path / "norm.pdf")
    assert ergebnis.schriften_ersetzt  # Vorschau-Warnung „bitte prüfen"

    upload_gut = tmp_path / "gut.pdf"
    upload_gut.write_bytes(erzeuge_testbogen("gut"))
    ergebnis_gut = normalisiere_briefpapier(upload_gut, tmp_path / "norm_gut.pdf")
    assert not ergebnis_gut.schriften_ersetzt


@benoetigt_gs
def test_normalisierung_vereinheitlicht_farbraum(briefpapier_norm):
    """Nach der Normalisierung darf kein DeviceCMYK mehr im Bogen stecken."""
    roh = briefpapier_norm.pfad.read_bytes()
    assert b"DeviceCMYK" not in roh


def test_mehrseitiger_bogen_wird_abgelehnt(tmp_path):
    import pikepdf as pp

    quelle = pp.open(io.BytesIO(erzeuge_testbogen("gut")))
    doppelt = pp.new()
    doppelt.pages.extend([quelle.pages[0], quelle.pages[0]])
    pfad = tmp_path / "doppelt.pdf"
    doppelt.save(str(pfad))
    with pytest.raises(NormalisierungAbgelehnt):
        pruefe_upload(pfad)


def test_kaputte_datei_wird_abgelehnt(tmp_path):
    pfad = tmp_path / "kaputt.pdf"
    pfad.write_bytes(b"kein pdf")
    with pytest.raises(NormalisierungAbgelehnt):
        pruefe_upload(pfad)


@benoetigt_gs
def test_zusammenbau_traegt_alle_pdfa3_merkmale(briefpapier_norm, rechnung, stammdaten):
    ergebnis = erzeuge_rechnung(
        rechnung,
        stammdaten,
        briefpapier_norm.pfad,
        Schreibzone(kopf_ende_mm=52, fuss_beginn_mm=25),
        zeitpunkt=ZEITPUNKT,
    )

    with pikepdf.open(io.BytesIO(ergebnis.pdf)) as pdf:
        # genau eine Ausgabebedingung, sRGB, ICC eingebettet
        absichten = pdf.Root.OutputIntents
        assert len(absichten) == 1
        absicht = absichten[0]
        assert absicht.S == pikepdf.Name.GTS_PDFA1
        assert str(absicht.OutputConditionIdentifier) == "sRGB IEC61966-2.1"
        assert len(bytes(absicht.DestOutputProfile.read_bytes())) > 0

        # Anhang factur-x.xml mit AFRelationship /Alternative und MIME text/xml
        spec = pdf.Root.AF[0]
        assert str(spec.F) == "factur-x.xml"
        assert spec.AFRelationship == pikepdf.Name.Alternative
        eingebettet = spec.EF.F
        assert eingebettet.Subtype == pikepdf.Name("/text/xml")
        assert bytes(eingebettet.read_bytes()) == ergebnis.xml

        # Namensbaum, MarkInfo, Sprache
        namen = pdf.Root.Names.EmbeddedFiles.Names
        assert str(namen[0]) == "factur-x.xml"
        assert bool(pdf.Root.MarkInfo.Marked) is True
        assert str(pdf.Root.Lang) == "de-DE"

        # XMP: PDF/A-3B plus Factur-X-Extension-Schema
        xmp = bytes(pdf.Root.Metadata.read_bytes())
        assert b"<pdfaid:part>3</pdfaid:part>" in xmp
        assert b"<pdfaid:conformance>B</pdfaid:conformance>" in xmp
        assert b"urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#" in xmp
        assert b"DocumentFileName" in xmp
        assert b"ConformanceLevel" in xmp
        assert "Rechnung RE-2026-0042".encode() in xmp


@benoetigt_gs
def test_pdf_und_xml_aus_demselben_vorgang(briefpapier_norm, rechnung, stammdaten):
    """Kernregel: das eingebettete XML ist bitidentisch mit dem gelieferten."""
    ergebnis = erzeuge_rechnung(
        rechnung,
        stammdaten,
        briefpapier_norm.pfad,
        Schreibzone(kopf_ende_mm=52, fuss_beginn_mm=25),
        zeitpunkt=ZEITPUNKT,
    )
    assert b"urn:cen.eu:en16931:2017" in ergebnis.xml
    with pikepdf.open(io.BytesIO(ergebnis.pdf)) as pdf:
        assert bytes(pdf.Root.AF[0].EF.F.read_bytes()) == ergebnis.xml
