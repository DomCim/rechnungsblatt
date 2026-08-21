import dataclasses
import datetime as dt
import xml.etree.ElementTree as ET
from decimal import Decimal

from rechnungsblatt_kern import (
    Belegtyp,
    Position,
    Profil,
    Steuerkategorie,
    berechne_summen,
    erzeuge_cii_xml,
)
from rechnungsblatt_kern.cii import NS


def _xml(rechnung, stammdaten, profil=Profil.EN16931):
    summen = berechne_summen(rechnung)
    return ET.fromstring(erzeuge_cii_xml(rechnung, stammdaten, summen, profil))


def _text(wurzel, pfad: str) -> str | None:
    element = wurzel.find(pfad, NS)
    return element.text if element is not None else None


def test_wohlgeformt_und_leitlinie_en16931(rechnung, stammdaten):
    wurzel = _xml(rechnung, stammdaten)
    assert wurzel.tag == f"{{{NS['rsm']}}}CrossIndustryInvoice"
    leitlinie = _text(
        wurzel,
        "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
    )
    assert leitlinie == "urn:cen.eu:en16931:2017"


def test_xrechnung_leitlinie(rechnung, stammdaten):
    behoerde = dataclasses.replace(
        rechnung,
        empfaenger=dataclasses.replace(
            rechnung.empfaenger,
            leitweg_id="04011000-1234512345-06",
            email="rechnungseingang@behoerde.example.de",
        ),
    )
    wurzel = _xml(behoerde, stammdaten, Profil.XRECHNUNG)
    leitlinie = _text(
        wurzel,
        "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
    )
    assert leitlinie.endswith("xrechnung_3.0")
    prozess = _text(
        wurzel,
        "rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID",
    )
    assert prozess == "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
    kaeuferreferenz = _text(
        wurzel,
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/ram:BuyerReference",
    )
    assert kaeuferreferenz == "04011000-1234512345-06"
    vereinbarung = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement"
    assert (
        _text(wurzel, f"{vereinbarung}/ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID")
        == "info@muster-partner.de"
    )
    assert (
        _text(wurzel, f"{vereinbarung}/ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID")
        == "rechnungseingang@behoerde.example.de"
    )


def test_verkaeufer_id_als_ersatz_ohne_ustidnr(rechnung, stammdaten):
    """BR-CO-26: ohne USt-IdNr. wird die Steuernummer als BT-29 ausgegeben."""
    nur_stnr = dataclasses.replace(stammdaten, ust_idnr=None)
    wurzel = _xml(rechnung, nur_stnr)
    verkaeufer_id = _text(
        wurzel,
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
        "ram:SellerTradeParty/ram:ID",
    )
    assert verkaeufer_id == "223/456/78901"
    # mit USt-IdNr. keine Ersatz-Kennung nötig
    wurzel = _xml(rechnung, stammdaten)
    assert (
        wurzel.find(
            "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
            "ram:SellerTradeParty/ram:ID",
            NS,
        )
        is None
    )


def test_kopf_und_datum(rechnung, stammdaten):
    wurzel = _xml(rechnung, stammdaten)
    assert _text(wurzel, "rsm:ExchangedDocument/ram:ID") == "RE-2026-0042"
    assert _text(wurzel, "rsm:ExchangedDocument/ram:TypeCode") == "380"
    datum = wurzel.find(
        "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString", NS
    )
    assert datum.text == "20260821"
    assert datum.get("format") == "102"


def test_position_und_summen(rechnung, stammdaten):
    wurzel = _xml(rechnung, stammdaten)
    zeile = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem", NS
    )
    assert _text(zeile, "ram:SpecifiedTradeProduct/ram:Name") == "Montagearbeiten"
    menge = zeile.find("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", NS)
    assert menge.text == "8"
    assert menge.get("unitCode") == "HUR"
    assert (
        _text(
            zeile,
            "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
        )
        == "200.00"
    )

    gesamt = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
        NS,
    )
    assert _text(gesamt, "ram:LineTotalAmount") == "200.00"
    assert _text(gesamt, "ram:TaxBasisTotalAmount") == "200.00"
    steuersumme = gesamt.find("ram:TaxTotalAmount", NS)
    assert steuersumme.text == "38.00"
    assert steuersumme.get("currencyID") == "EUR"
    assert _text(gesamt, "ram:GrandTotalAmount") == "238.00"
    assert _text(gesamt, "ram:DuePayableAmount") == "238.00"


def test_steuerkoerbe_mit_befreiungsgrund(rechnung, stammdaten):
    klein_stamm = dataclasses.replace(stammdaten, kleinunternehmer=True)
    klein = dataclasses.replace(
        rechnung,
        positionen=(
            dataclasses.replace(
                rechnung.positionen[0], steuer=Steuerkategorie.KLEINUNTERNEHMER
            ),
        ),
    )
    wurzel = _xml(klein, klein_stamm)
    steuer = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax",
        NS,
    )
    assert _text(steuer, "ram:CategoryCode") == "E"
    assert "§ 19 UStG" in _text(steuer, "ram:ExemptionReason")
    assert _text(steuer, "ram:CalculatedAmount") == "0.00"
    # Pflichthinweis auch als Dokumentnotiz
    notizen = [
        notiz.text
        for notiz in wurzel.findall("rsm:ExchangedDocument/ram:IncludedNote/ram:Content", NS)
    ]
    assert any("§ 19 UStG" in text for text in notizen)


def test_rabatt_als_nachlass_mit_korbsteuer(rechnung, stammdaten):
    rabattiert = dataclasses.replace(rechnung, rabatt_betrag=Decimal("20.00"))
    wurzel = _xml(rabattiert, stammdaten)
    nachlass = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:SpecifiedTradeAllowanceCharge",
        NS,
    )
    assert nachlass is not None
    kennzeichen = nachlass.find("ram:ChargeIndicator/udt:Indicator", NS)
    assert kennzeichen.text == "false"
    assert _text(nachlass, "ram:ActualAmount") == "20.00"
    assert _text(nachlass, "ram:CategoryTradeTax/ram:CategoryCode") == "S"

    gesamt = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:SpecifiedTradeSettlementHeaderMonetarySummation",
        NS,
    )
    assert _text(gesamt, "ram:AllowanceTotalAmount") == "20.00"
    assert _text(gesamt, "ram:TaxBasisTotalAmount") == "180.00"
    assert _text(gesamt, "ram:GrandTotalAmount") == "214.20"


def test_verkaeufer_steuerregistrierungen(rechnung, stammdaten):
    wurzel = _xml(rechnung, stammdaten)
    registrierungen = wurzel.findall(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/"
        "ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID",
        NS,
    )
    schemata = {element.get("schemeID"): element.text for element in registrierungen}
    assert schemata["FC"] == "223/456/78901"
    assert schemata["VA"] == "DE123456789"


def test_zahlweg_sepa_mit_iban_ohne_leerzeichen(rechnung, stammdaten):
    wurzel = _xml(rechnung, stammdaten)
    zahlweg = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:SpecifiedTradeSettlementPaymentMeans",
        NS,
    )
    assert _text(zahlweg, "ram:TypeCode") == "58"
    assert _text(zahlweg, "ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == (
        "DE14780500000001234567"
    )
    assert _text(
        zahlweg, "ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID"
    ) == "BYLADEM1HOF"


def test_gutschrift_mit_bezug(rechnung, stammdaten):
    gutschrift = dataclasses.replace(
        rechnung,
        typ=Belegtyp.GUTSCHRIFT,
        bezugs_nummer="RE-2026-0041",
        bezugs_datum=dt.date(2026, 8, 1),
    )
    wurzel = _xml(gutschrift, stammdaten)
    assert _text(wurzel, "rsm:ExchangedDocument/ram:TypeCode") == "381"
    bezug = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:InvoiceReferencedDocument",
        NS,
    )
    assert _text(bezug, "ram:IssuerAssignedID") == "RE-2026-0041"
    datum = bezug.find("ram:FormattedIssueDateTime/qdt:DateTimeString", NS)
    assert datum.text == "20260801"


def test_leistungszeitraum_statt_datum(rechnung, stammdaten):
    from rechnungsblatt_kern import Zeitraum

    zeitraum = dataclasses.replace(
        rechnung,
        leistungsdatum=None,
        leistungszeitraum=Zeitraum(von=dt.date(2026, 8, 1), bis=dt.date(2026, 8, 31)),
    )
    wurzel = _xml(zeitraum, stammdaten)
    periode = wurzel.find(
        "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement/"
        "ram:BillingSpecifiedPeriod",
        NS,
    )
    assert periode.find("ram:StartDateTime/udt:DateTimeString", NS).text == "20260801"
    assert periode.find("ram:EndDateTime/udt:DateTimeString", NS).text == "20260831"
    # kein Lieferdatum-Ereignis, wenn nur ein Zeitraum angegeben ist
    assert (
        wurzel.find(
            "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeDelivery/"
            "ram:ActualDeliverySupplyChainEvent",
            NS,
        )
        is None
    )
