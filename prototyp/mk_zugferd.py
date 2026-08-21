"""Briefpapier als Unterlage -> Rechnungsinhalt darueber -> EN-16931-XML rein
   -> PDF/A-3B. Genau der Schritt, der ueber Bauen oder Lassen entscheidet."""
import sys, io, datetime, pikepdf
from pikepdf import Name, String, Dictionary, Array, Stream
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BRIEF, OUT = sys.argv[1], sys.argv[2]
W, H = A4
INV = dict(nr="RE-2026-0042", datum="2026-08-21", faellig="2026-09-04",
           netto="200.00", steuer="38.00", brutto="238.00")

# ---------- 1. Inhalt in die Schreibzone (unter Kopf, ueber Fuss) ----------
buf = io.BytesIO()
pdfmetrics.registerFont(TTFont("F",  "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("FB", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"))
c = canvas.Canvas(buf, pagesize=A4)
c.setFillColorRGB(0,0,0)
c.setFont("F", 8);  c.drawString(20*mm, H-62*mm, "Muster & Partner GmbH · Bahnhofstr. 12 · 95119 Naila")
c.setFont("F", 10)
for i, l in enumerate(["Beispielkunde GmbH","Frau Anna Schmidt","Industriestr. 5","95028 Hof"]):
    c.drawString(20*mm, H-70*mm - i*5*mm, l)
c.setFont("FB", 14); c.drawString(20*mm, H-105*mm, f"Rechnung {INV['nr']}")
c.setFont("F", 9)
c.drawString(130*mm, H-105*mm, f"Datum: {INV['datum']}")
c.drawString(130*mm, H-110*mm, f"Leistung: 08/2026")
y = H-125*mm
c.setFont("FB", 9)
for x, t in [(20,"Pos"),(32,"Leistung"),(120,"Menge"),(145,"Preis"),(170,"Summe")]:
    c.drawString(x*mm, y, t)
c.line(20*mm, y-2*mm, 190*mm, y-2*mm)
c.setFont("F", 9); y -= 9*mm
c.drawString(20*mm,y,"1"); c.drawString(32*mm,y,"Montagearbeiten")
c.drawRightString(138*mm,y,"8 Std"); c.drawRightString(163*mm,y,"25,00 €"); c.drawRightString(188*mm,y,"200,00 €")
y -= 14*mm
c.drawRightString(163*mm,y,"Nettobetrag"); c.drawRightString(188*mm,y,"200,00 €"); y-=5*mm
c.drawRightString(163*mm,y,"USt 19 %");    c.drawRightString(188*mm,y,"38,00 €");  y-=6*mm
c.setFont("FB",10); c.drawRightString(163*mm,y,"Gesamt"); c.drawRightString(188*mm,y,"238,00 €")
c.setFont("F",9); c.drawString(20*mm, y-18*mm, f"Zahlbar ohne Abzug bis {INV['faellig']}.")
c.showPage(); c.save()
buf.seek(0)

# ---------- 2. EN-16931-XML (CII) ----------
xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
 <rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>
 <rsm:ExchangedDocument><ram:ID>{INV['nr']}</ram:ID><ram:TypeCode>380</ram:TypeCode><ram:IssueDateTime><udt:DateTimeString format="102">{INV['datum'].replace('-','')}</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:IncludedSupplyChainTradeLineItem>
   <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
   <ram:SpecifiedTradeProduct><ram:Name>Montagearbeiten</ram:Name></ram:SpecifiedTradeProduct>
   <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>25.00</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
   <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="HUR">8</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
   <ram:SpecifiedLineTradeSettlement>
    <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
    <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>200.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
   </ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
  <ram:ApplicableHeaderTradeAgreement>
   <ram:SellerTradeParty><ram:Name>Muster &amp; Partner GmbH</ram:Name>
    <ram:PostalTradeAddress><ram:PostcodeCode>95119</ram:PostcodeCode><ram:LineOne>Bahnhofstr. 12</ram:LineOne><ram:CityName>Naila</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
    <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE123456789</ram:ID></ram:SpecifiedTaxRegistration></ram:SellerTradeParty>
   <ram:BuyerTradeParty><ram:Name>Beispielkunde GmbH</ram:Name>
    <ram:PostalTradeAddress><ram:PostcodeCode>95028</ram:PostcodeCode><ram:LineOne>Industriestr. 5</ram:LineOne><ram:CityName>Hof</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress></ram:BuyerTradeParty>
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeDelivery><ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime><udt:DateTimeString format="102">{INV['datum'].replace('-','')}</udt:DateTimeString></ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent></ram:ApplicableHeaderTradeDelivery>
  <ram:ApplicableHeaderTradeSettlement>
   <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
   <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount><ram:IBANID>DE02780500000001234567</ram:IBANID></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>
   <ram:ApplicableTradeTax><ram:CalculatedAmount>38.00</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>200.00</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
   <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">{INV['faellig'].replace('-','')}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation><ram:LineTotalAmount>200.00</ram:LineTotalAmount><ram:TaxBasisTotalAmount>200.00</ram:TaxBasisTotalAmount><ram:TaxTotalAmount currencyID="EUR">38.00</ram:TaxTotalAmount><ram:GrandTotalAmount>238.00</ram:GrandTotalAmount><ram:DuePayableAmount>238.00</ram:DuePayableAmount></ram:SpecifiedTradeSettlementHeaderMonetarySummation>
  </ram:ApplicableHeaderTradeSettlement>
 </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>""".encode()
open("factur-x.xml","wb").write(xml)

# ---------- 3. Ueberlagern ----------
pdf = pikepdf.open(BRIEF)
ov  = pikepdf.open(buf)
pdf.pages[0].add_overlay(ov.pages[0])

# ---------- 4. PDF/A-3B: OutputIntent + XMP + Anhang ----------
icc = open("/usr/share/texlive/texmf-dist/tex/generic/colorprofiles/sRGB.icc","rb").read()
icc_st = Stream(pdf, icc); icc_st.N = 3; icc_st.Alternate = Name.DeviceRGB
pdf.Root.OutputIntents = Array([Dictionary(
    Type=Name.OutputIntent, S=Name.GTS_PDFA1,
    OutputConditionIdentifier=String("sRGB IEC61966-2.1"),
    Info=String("sRGB IEC61966-2.1"), DestOutputProfile=icc_st)])

fs = Stream(pdf, xml)
fs.Type=Name.EmbeddedFile; fs.Subtype=Name("/text/xml")
fs.Params = Dictionary(ModDate=String("D:20260821120000+02'00'"), Size=len(xml))
spec = Dictionary(Type=Name.Filespec, F=String("factur-x.xml"), UF=String("factur-x.xml"),
                  Desc=String("Factur-X/ZUGFeRD Invoice"),
                  AFRelationship=Name.Alternative, EF=Dictionary(F=fs, UF=fs))
spec_o = pdf.make_indirect(spec)
pdf.Root.AF = Array([spec_o])
pdf.Root.Names = Dictionary(EmbeddedFiles=Dictionary(Names=Array([String("factur-x.xml"), spec_o])))
pdf.Root.MarkInfo = Dictionary(Marked=True)
if Name.Lang not in pdf.Root: pdf.Root.Lang = String("de-DE")

now = "2026-08-21T12:00:00+02:00"
xmp = f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
   <pdfaid:part>3</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance></rdf:Description>
  <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Rechnung {INV['nr']}</rdf:li></rdf:Alt></dc:title></rdf:Description>
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">
   <xmp:CreateDate>{now}</xmp:CreateDate><xmp:ModifyDate>{now}</xmp:ModifyDate>
   <xmp:CreatorTool>Prototyp Briefpapier-ZUGFeRD</xmp:CreatorTool></rdf:Description>
  <rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
   <pdf:Producer>Prototyp Briefpapier-ZUGFeRD</pdf:Producer></rdf:Description>
  <rdf:Description rdf:about="" xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/" xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#" xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
   <pdfaExtension:schemas><rdf:Bag><rdf:li rdf:parseType="Resource">
    <pdfaSchema:schema>Factur-X PDFA Extension Schema</pdfaSchema:schema>
    <pdfaSchema:namespaceURI>urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#</pdfaSchema:namespaceURI>
    <pdfaSchema:prefix>fx</pdfaSchema:prefix>
    <pdfaSchema:property><rdf:Seq>
     <rdf:li rdf:parseType="Resource"><pdfaProperty:name>DocumentFileName</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>Name of the embedded XML document</pdfaProperty:description></rdf:li>
     <rdf:li rdf:parseType="Resource"><pdfaProperty:name>DocumentType</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>INVOICE</pdfaProperty:description></rdf:li>
     <rdf:li rdf:parseType="Resource"><pdfaProperty:name>Version</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>Version of the Factur-X data</pdfaProperty:description></rdf:li>
     <rdf:li rdf:parseType="Resource"><pdfaProperty:name>ConformanceLevel</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>Conformance level</pdfaProperty:description></rdf:li>
    </rdf:Seq></pdfaSchema:property></rdf:li></rdf:Bag></pdfaExtension:schemas></rdf:Description>
  <rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
   <fx:DocumentType>INVOICE</fx:DocumentType><fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>
   <fx:Version>1.0</fx:Version><fx:ConformanceLevel>EN 16931</fx:ConformanceLevel></rdf:Description>
 </rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"""
mst = Stream(pdf, xmp.encode("utf-8")); mst.Type=Name.Metadata; mst.Subtype=Name.XML
pdf.Root.Metadata = pdf.make_indirect(mst)
pdf.save(OUT)
print("erzeugt:", OUT)
