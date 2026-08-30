"""CII-XML-Erzeugung (UN/CEFACT Cross Industry Invoice, EN 16931).

Generalisiert aus dem validierten Prototyp (``prototyp/mk_zugferd.py``,
Profil ``urn:cen.eu:en16931:2017`` — status valid). Die Elementreihenfolge
folgt dem CII-D16B-Schema; sie ist nicht beliebig.

Kernregel: Diese Funktion erhält dieselben :class:`Summen` wie das
Blatt-Rendering. Es wird hier nicht gerechnet, nur serialisiert.
"""

from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from decimal import Decimal

from .modell import Belegtyp, Profil, Rechnung, Stammdaten, Steuerkategorie
from .summen import Summen

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}

for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _el(parent: ET.Element, prefix: str, tag: str, text: str | None = None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, _q(prefix, tag), attrs)
    if text is not None:
        element.text = text
    return element


def _betrag(wert: Decimal) -> str:
    return f"{wert:.2f}"


def _menge(wert: Decimal) -> str:
    text = format(wert.normalize(), "f")
    return text if text else "0"


def _datum102(datum: _dt.date) -> str:
    return datum.strftime("%Y%m%d")


def _datumselement(parent: ET.Element, prefix: str, tag: str, datum: _dt.date) -> None:
    umschlag = _el(parent, prefix, tag)
    _el(umschlag, "udt", "DateTimeString", _datum102(datum), format="102")


def erzeuge_cii_xml(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    summen: Summen,
    profil: Profil = Profil.EN16931,
) -> bytes:
    """Serialisiert den Beleg als CII-XML (EN 16931 bzw. XRechnung 3.0)."""
    wurzel = ET.Element(_q("rsm", "CrossIndustryInvoice"))

    kontext = _el(wurzel, "rsm", "ExchangedDocumentContext")
    if profil is Profil.XRECHNUNG:
        # BT-23 Business Process (PEPPOL-EN16931-R001)
        prozess = _el(kontext, "ram", "BusinessProcessSpecifiedDocumentContextParameter")
        _el(prozess, "ram", "ID", "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0")
    leitlinie = _el(kontext, "ram", "GuidelineSpecifiedDocumentContextParameter")
    _el(leitlinie, "ram", "ID", profil.value)

    dokument = _el(wurzel, "rsm", "ExchangedDocument")
    _el(dokument, "ram", "ID", rechnung.nummer)
    _el(dokument, "ram", "TypeCode", str(rechnung.typ.value))
    _datumselement(dokument, "ram", "IssueDateTime", rechnung.rechnungsdatum)
    for hinweis in _hinweise(rechnung):
        notiz = _el(dokument, "ram", "IncludedNote")
        _el(notiz, "ram", "Content", hinweis)

    transaktion = _el(wurzel, "rsm", "SupplyChainTradeTransaction")
    for nummer, position in enumerate(rechnung.positionen, start=1):
        _positionselement(transaktion, nummer, position)
    _vereinbarung(transaktion, rechnung, stammdaten, profil)
    _lieferung(transaktion, rechnung)
    _abrechnung(transaktion, rechnung, stammdaten, summen)

    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(wurzel, encoding="unicode").encode("utf-8")
    )


def _hinweise(rechnung: Rechnung) -> list[str]:
    hinweise: list[str] = []
    kategorien = {position.steuer for position in rechnung.positionen}
    for kategorie in sorted(kategorien, key=lambda k: k.name):
        if kategorie.hinweis:
            hinweise.append(kategorie.hinweis)
    if rechnung.freitext:
        hinweise.append(rechnung.freitext)
    return hinweise


def _positionselement(transaktion: ET.Element, nummer: int, position) -> None:
    zeile = _el(transaktion, "ram", "IncludedSupplyChainTradeLineItem")
    zeilendokument = _el(zeile, "ram", "AssociatedDocumentLineDocument")
    _el(zeilendokument, "ram", "LineID", str(nummer))

    produkt = _el(zeile, "ram", "SpecifiedTradeProduct")
    # Reihenfolge nach CII-Schema: SellerAssignedID vor Name vor Description.
    if position.artikelnummer:
        _el(produkt, "ram", "SellerAssignedID", position.artikelnummer)
    _el(produkt, "ram", "Name", position.bezeichnung)
    if position.beschreibung:
        _el(produkt, "ram", "Description", position.beschreibung)

    vereinbarung = _el(zeile, "ram", "SpecifiedLineTradeAgreement")
    preis = _el(vereinbarung, "ram", "NetPriceProductTradePrice")
    _el(preis, "ram", "ChargeAmount", _betrag(position.einzelpreis))

    lieferung = _el(zeile, "ram", "SpecifiedLineTradeDelivery")
    _el(lieferung, "ram", "BilledQuantity", _menge(position.menge), unitCode=position.einheit)

    abrechnung = _el(zeile, "ram", "SpecifiedLineTradeSettlement")
    steuer = _el(abrechnung, "ram", "ApplicableTradeTax")
    _el(steuer, "ram", "TypeCode", "VAT")
    _el(steuer, "ram", "CategoryCode", position.steuer.code)
    _el(steuer, "ram", "RateApplicablePercent", _betrag(position.steuer.satz))
    zeilensumme = _el(abrechnung, "ram", "SpecifiedTradeSettlementLineMonetarySummation")
    from .summen import zeilensumme as berechne_zeilensumme

    _el(zeilensumme, "ram", "LineTotalAmount", _betrag(berechne_zeilensumme(position)))


def _vereinbarung(
    transaktion: ET.Element,
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    profil: Profil,
) -> None:
    vereinbarung = _el(transaktion, "ram", "ApplicableHeaderTradeAgreement")
    if profil is Profil.XRECHNUNG and rechnung.empfaenger.leitweg_id:
        _el(vereinbarung, "ram", "BuyerReference", rechnung.empfaenger.leitweg_id)

    verkaeufer = _el(vereinbarung, "ram", "SellerTradeParty")
    if not stammdaten.ust_idnr and stammdaten.steuernummer:
        # BR-CO-26: ohne USt-IdNr. (BT-31) braucht der Verkäufer eine
        # Kennung (BT-29) — die Steuernummer erfüllt das.
        _el(verkaeufer, "ram", "ID", stammdaten.steuernummer)
    _el(verkaeufer, "ram", "Name", stammdaten.firmierung)
    if stammdaten.kontakt_name or stammdaten.kontakt_telefon or stammdaten.kontakt_email:
        kontakt = _el(verkaeufer, "ram", "DefinedTradeContact")
        if stammdaten.kontakt_name:
            _el(kontakt, "ram", "PersonName", stammdaten.kontakt_name)
        if stammdaten.kontakt_telefon:
            telefon = _el(kontakt, "ram", "TelephoneUniversalCommunication")
            _el(telefon, "ram", "CompleteNumber", stammdaten.kontakt_telefon)
        if stammdaten.kontakt_email:
            email = _el(kontakt, "ram", "EmailURIUniversalCommunication")
            _el(email, "ram", "URIID", stammdaten.kontakt_email)
    _anschriftselement(verkaeufer, stammdaten.anschrift)
    if profil is Profil.XRECHNUNG and stammdaten.kontakt_email:
        # BT-34 elektronische Adresse (PEPPOL-EN16931-R020)
        uri = _el(verkaeufer, "ram", "URIUniversalCommunication")
        _el(uri, "ram", "URIID", stammdaten.kontakt_email, schemeID="EM")
    if stammdaten.steuernummer:
        registrierung = _el(verkaeufer, "ram", "SpecifiedTaxRegistration")
        _el(registrierung, "ram", "ID", stammdaten.steuernummer, schemeID="FC")
    if stammdaten.ust_idnr:
        registrierung = _el(verkaeufer, "ram", "SpecifiedTaxRegistration")
        _el(registrierung, "ram", "ID", stammdaten.ust_idnr, schemeID="VA")

    kaeufer = _el(vereinbarung, "ram", "BuyerTradeParty")
    _el(kaeufer, "ram", "Name", rechnung.empfaenger.name)
    _anschriftselement(kaeufer, rechnung.empfaenger.anschrift)
    if profil is Profil.XRECHNUNG and rechnung.empfaenger.email:
        # BT-49 elektronische Adresse (PEPPOL-EN16931-R010)
        uri = _el(kaeufer, "ram", "URIUniversalCommunication")
        _el(uri, "ram", "URIID", rechnung.empfaenger.email, schemeID="EM")
    if rechnung.empfaenger.ust_idnr:
        registrierung = _el(kaeufer, "ram", "SpecifiedTaxRegistration")
        _el(registrierung, "ram", "ID", rechnung.empfaenger.ust_idnr, schemeID="VA")


def _anschriftselement(partei: ET.Element, anschrift) -> None:
    adresse = _el(partei, "ram", "PostalTradeAddress")
    _el(adresse, "ram", "PostcodeCode", anschrift.plz)
    _el(adresse, "ram", "LineOne", anschrift.strasse)
    _el(adresse, "ram", "CityName", anschrift.ort)
    _el(adresse, "ram", "CountryID", anschrift.land)


def _lieferung(transaktion: ET.Element, rechnung: Rechnung) -> None:
    lieferung = _el(transaktion, "ram", "ApplicableHeaderTradeDelivery")
    if rechnung.leistungsdatum is not None:
        ereignis = _el(lieferung, "ram", "ActualDeliverySupplyChainEvent")
        _datumselement(ereignis, "ram", "OccurrenceDateTime", rechnung.leistungsdatum)


def _abrechnung(
    transaktion: ET.Element,
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    summen: Summen,
) -> None:
    abrechnung = _el(transaktion, "ram", "ApplicableHeaderTradeSettlement")
    if rechnung.verwendungszweck:
        # BT-83: Verwendungszweck für die Überweisung (vor InvoiceCurrencyCode)
        _el(abrechnung, "ram", "PaymentReference", rechnung.verwendungszweck)
    _el(abrechnung, "ram", "InvoiceCurrencyCode", rechnung.waehrung)

    zahlweg = _el(abrechnung, "ram", "SpecifiedTradeSettlementPaymentMeans")
    _el(zahlweg, "ram", "TypeCode", "58")  # SEPA-Überweisung
    konto = _el(zahlweg, "ram", "PayeePartyCreditorFinancialAccount")
    _el(konto, "ram", "IBANID", stammdaten.iban.replace(" ", ""))
    if stammdaten.bic:
        institut = _el(zahlweg, "ram", "PayeeSpecifiedCreditorFinancialInstitution")
        _el(institut, "ram", "BICID", stammdaten.bic)

    for korb in summen.koerbe:
        steuer = _el(abrechnung, "ram", "ApplicableTradeTax")
        _el(steuer, "ram", "CalculatedAmount", _betrag(korb.steuer))
        _el(steuer, "ram", "TypeCode", "VAT")
        if korb.kategorie.hinweis:
            _el(steuer, "ram", "ExemptionReason", korb.kategorie.hinweis)
        _el(steuer, "ram", "BasisAmount", _betrag(korb.basis))
        _el(steuer, "ram", "CategoryCode", korb.kategorie.code)
        _el(steuer, "ram", "RateApplicablePercent", _betrag(korb.kategorie.satz))

    if rechnung.leistungszeitraum is not None:
        zeitraum = _el(abrechnung, "ram", "BillingSpecifiedPeriod")
        _datumselement(zeitraum, "ram", "StartDateTime", rechnung.leistungszeitraum.von)
        _datumselement(zeitraum, "ram", "EndDateTime", rechnung.leistungszeitraum.bis)

    if summen.rabatt > 0:
        for korb in summen.koerbe:
            if korb.rabatt <= 0:
                continue
            nachlass = _el(abrechnung, "ram", "SpecifiedTradeAllowanceCharge")
            kennzeichen = _el(nachlass, "ram", "ChargeIndicator")
            _el(kennzeichen, "udt", "Indicator", "false")
            if rechnung.rabatt_prozent is not None:
                # BT-138 vor BT-92 (ActualAmount) — Schemareihenfolge.
                _el(
                    nachlass,
                    "ram",
                    "CalculationPercent",
                    _betrag(rechnung.rabatt_prozent),
                )
            _el(nachlass, "ram", "ActualAmount", _betrag(korb.rabatt))
            _el(nachlass, "ram", "Reason", rechnung.rabatt_grund)
            korbsteuer = _el(nachlass, "ram", "CategoryTradeTax")
            _el(korbsteuer, "ram", "TypeCode", "VAT")
            _el(korbsteuer, "ram", "CategoryCode", korb.kategorie.code)
            _el(korbsteuer, "ram", "RateApplicablePercent", _betrag(korb.kategorie.satz))

    zahlungsziel = _el(abrechnung, "ram", "SpecifiedTradePaymentTerms")
    if rechnung.faelligkeit is not None:
        _el(
            zahlungsziel,
            "ram",
            "Description",
            f"Zahlbar ohne Abzug bis {rechnung.faelligkeit.strftime('%d.%m.%Y')}.",
        )
        faellig = _el(zahlungsziel, "ram", "DueDateDateTime")
        _el(faellig, "udt", "DateTimeString", _datum102(rechnung.faelligkeit), format="102")
    else:
        _el(
            zahlungsziel,
            "ram",
            "Description",
            f"Zahlbar innerhalb von {stammdaten.zahlungsziel_tage} Tagen ohne Abzug.",
        )

    gesamt = _el(abrechnung, "ram", "SpecifiedTradeSettlementHeaderMonetarySummation")
    _el(gesamt, "ram", "LineTotalAmount", _betrag(summen.zeilensumme))
    if summen.rabatt > 0:
        _el(gesamt, "ram", "AllowanceTotalAmount", _betrag(summen.rabatt))
    _el(gesamt, "ram", "TaxBasisTotalAmount", _betrag(summen.steuerbasis))
    _el(gesamt, "ram", "TaxTotalAmount", _betrag(summen.steuer), currencyID=rechnung.waehrung)
    _el(gesamt, "ram", "GrandTotalAmount", _betrag(summen.brutto))
    _el(gesamt, "ram", "DuePayableAmount", _betrag(summen.brutto))

    if rechnung.typ in (Belegtyp.GUTSCHRIFT, Belegtyp.KORREKTUR) and rechnung.bezugs_nummer:
        bezug = _el(abrechnung, "ram", "InvoiceReferencedDocument")
        _el(bezug, "ram", "IssuerAssignedID", rechnung.bezugs_nummer)
        if rechnung.bezugs_datum is not None:
            formatiert = _el(bezug, "ram", "FormattedIssueDateTime")
            _el(formatiert, "qdt", "DateTimeString", _datum102(rechnung.bezugs_datum), format="102")
