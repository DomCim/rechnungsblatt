"""Schmale Schnittstelle des Kerns für die Web-Schicht.

Kernregel (Übergabe, §3): PDF und XML entstehen aus denselben Daten im selben
Vorgang — :func:`erzeuge_rechnung` rechnet die Summen genau einmal und speist
daraus sowohl das Blatt als auch das CII-XML. Ein bestehendes PDF wird nie
nachträglich angereichert.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from .blatt import Schriften, rendere_blatt
from .cii import erzeuge_cii_xml
from .modell import (
    Anschrift,
    Belegtyp,
    Blattgestaltung,
    Empfaenger,
    Position,
    Profil,
    Rechnung,
    Schreibzone,
    Stammdaten,
    Steuerkategorie,
)
from .pruefung import erzwinge_paragraph14
from .summen import Summen, berechne_summen
from .zusammenbau import baue_pdfa3


@dataclass(frozen=True)
class ErzeugteRechnung:
    pdf: bytes  # PDF/A-3B mit eingebettetem factur-x.xml (ZUGFeRD)
    xml: bytes  # dasselbe CII-XML, einzeln (z. B. für Sichtprüfung)
    summen: Summen


def erzeuge_rechnung(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    briefpapier_norm: bytes | str | Path,
    zone: Schreibzone,
    zeitpunkt: _dt.datetime,
    schriften: Schriften | None = None,
    icc: bytes | None = None,
    gestaltung: Blattgestaltung | None = None,
    girocode: bool = True,
) -> ErzeugteRechnung:
    """Erzeugt die ZUGFeRD-Rechnung (PDF/A-3B) auf dem normalisierten Briefpapier.

    Wirft :class:`~rechnungsblatt_kern.pruefung.UngueltigeRechnung`, wenn
    Pflichtangaben fehlen — die Prüfung ist blockierend.
    """
    erzwinge_paragraph14(rechnung, stammdaten, Profil.EN16931)
    summen = berechne_summen(rechnung)
    xml = erzeuge_cii_xml(rechnung, stammdaten, summen, Profil.EN16931)
    blatt = rendere_blatt(
        rechnung, stammdaten, summen, zone, schriften, gestaltung, girocode=girocode
    )
    pdf = baue_pdfa3(
        briefpapier_norm,
        blatt,
        xml,
        titel=f"{rechnung.typ.titel} {rechnung.nummer}",
        zeitpunkt=zeitpunkt,
        icc=icc,
    )
    return ErzeugteRechnung(pdf=pdf, xml=xml, summen=summen)


def erzeuge_gestaltungsvorschau(
    zone: Schreibzone,
    gestaltung: Blattgestaltung,
    stammdaten: Stammdaten | None = None,
    briefpapier_norm: bytes | str | Path | None = None,
    girocode: bool = True,
) -> bytes:
    """Rendert eine Musterrechnung mit der gewählten Gestaltung als PDF.

    Nur für die Vorschau im Gestaltungs-Schritt — keine PDF/A-Merkmale, kein
    XML. Liegt ein normalisiertes Briefpapier vor, wird es unterlegt, damit
    die Vorschau das echte Zusammenspiel zeigt.
    """
    import datetime as dt
    from decimal import Decimal

    stammdaten = stammdaten or Stammdaten(
        firmierung="Muster & Partner GmbH",
        anschrift=Anschrift(strasse="Bahnhofstr. 12", plz="95119", ort="Naila"),
        steuernummer="223/456/78901",
        ust_idnr="DE123456789",
        iban="DE14 7805 0000 0001 2345 67",
        bic="BYLADEM1HOF",
    )
    kategorie = (
        Steuerkategorie.KLEINUNTERNEHMER
        if stammdaten.kleinunternehmer
        else Steuerkategorie.UST_19
    )
    heute = dt.date.today()
    muster = Rechnung(
        verwendungszweck="RE-2026-0042",
        nummer="RE-2026-0042",
        rechnungsdatum=heute,
        leistungsdatum=heute,
        faelligkeit=heute + dt.timedelta(days=stammdaten.zahlungsziel_tage),
        empfaenger=Empfaenger(
            name="Beispielkunde GmbH",
            anschrift=Anschrift(strasse="Industriestr. 5", plz="95028", ort="Hof"),
        ),
        freitext="Vielen Dank für Ihren Auftrag.",
        positionen=(
            Position(
                bezeichnung="Montagearbeiten",
                menge=Decimal("8"),
                einheit="HUR",
                einzelpreis=Decimal("25.00"),
                steuer=kategorie,
            ),
            Position(
                bezeichnung="Anfahrtspauschale",
                menge=Decimal("1"),
                einheit="C62",
                einzelpreis=Decimal("35.00"),
                steuer=kategorie,
            ),
        ),
    )
    summen = berechne_summen(muster)
    blatt = rendere_blatt(
        muster, stammdaten, summen, zone, gestaltung=gestaltung, girocode=girocode
    )
    if briefpapier_norm is None:
        return blatt

    import io

    import pikepdf

    quelle = (
        io.BytesIO(briefpapier_norm)
        if isinstance(briefpapier_norm, bytes)
        else str(briefpapier_norm)
    )
    with pikepdf.open(quelle) as pdf, pikepdf.open(io.BytesIO(blatt)) as overlay:
        pdf.pages[0].add_overlay(overlay.pages[0])
        ausgabe = io.BytesIO()
        pdf.save(ausgabe)
        return ausgabe.getvalue()


def erzeuge_xrechnung(rechnung: Rechnung, stammdaten: Stammdaten) -> bytes:
    """Erzeugt das XRechnung-CII-XML (für Behördenkunden, reiner XML-Download).

    Prüft zusätzlich die XRechnung-Pflichten (Leitweg-ID, Kontaktdaten).
    """
    erzwinge_paragraph14(rechnung, stammdaten, Profil.XRECHNUNG)
    summen = berechne_summen(rechnung)
    return erzeuge_cii_xml(rechnung, stammdaten, summen, Profil.XRECHNUNG)
