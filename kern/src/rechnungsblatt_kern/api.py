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
from .modell import Profil, Rechnung, Schreibzone, Stammdaten
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
) -> ErzeugteRechnung:
    """Erzeugt die ZUGFeRD-Rechnung (PDF/A-3B) auf dem normalisierten Briefpapier.

    Wirft :class:`~rechnungsblatt_kern.pruefung.UngueltigeRechnung`, wenn
    Pflichtangaben fehlen — die Prüfung ist blockierend.
    """
    erzwinge_paragraph14(rechnung, stammdaten, Profil.EN16931)
    summen = berechne_summen(rechnung)
    xml = erzeuge_cii_xml(rechnung, stammdaten, summen, Profil.EN16931)
    blatt = rendere_blatt(rechnung, stammdaten, summen, zone, schriften)
    pdf = baue_pdfa3(
        briefpapier_norm,
        blatt,
        xml,
        titel=f"{rechnung.typ.titel} {rechnung.nummer}",
        zeitpunkt=zeitpunkt,
        icc=icc,
    )
    return ErzeugteRechnung(pdf=pdf, xml=xml, summen=summen)


def erzeuge_xrechnung(rechnung: Rechnung, stammdaten: Stammdaten) -> bytes:
    """Erzeugt das XRechnung-CII-XML (für Behördenkunden, reiner XML-Download).

    Prüft zusätzlich die XRechnung-Pflichten (Leitweg-ID, Kontaktdaten).
    """
    erzwinge_paragraph14(rechnung, stammdaten, Profil.XRECHNUNG)
    summen = berechne_summen(rechnung)
    return erzeuge_cii_xml(rechnung, stammdaten, summen, Profil.XRECHNUNG)
