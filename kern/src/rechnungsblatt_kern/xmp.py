"""XMP-Metadaten für PDF/A-3B mit Factur-X-Extension-Schema.

Wortgleich aus dem validierten Prototyp (``prototyp/mk_zugferd.py``)
übernommen. Ohne das Extension-Schema mit den vier Eigenschaften
``DocumentFileName``, ``DocumentType``, ``Version``, ``ConformanceLevel``
ist die Datei kein gültiges ZUGFeRD.
"""

from __future__ import annotations

import datetime as _dt
from xml.sax.saxutils import escape

ERZEUGER = "Rechnungsblatt"


def erzeuge_xmp(titel: str, zeitpunkt: _dt.datetime, erzeuger: str = ERZEUGER) -> bytes:
    """Erzeugt das vollständige XMP-Paket für eine ZUGFeRD-Rechnung.

    ``zeitpunkt`` muss zeitzonenbewusst sein, damit CreateDate/ModifyDate
    ein gültiges Offset tragen.
    """
    if zeitpunkt.tzinfo is None:
        raise ValueError("zeitpunkt braucht eine Zeitzone (tzinfo).")
    zeit = zeitpunkt.isoformat(timespec="seconds")
    titel = escape(titel)
    erzeuger = escape(erzeuger)
    xmp = f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
   <pdfaid:part>3</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance></rdf:Description>
  <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{titel}</rdf:li></rdf:Alt></dc:title></rdf:Description>
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">
   <xmp:CreateDate>{zeit}</xmp:CreateDate><xmp:ModifyDate>{zeit}</xmp:ModifyDate>
   <xmp:CreatorTool>{erzeuger}</xmp:CreatorTool></rdf:Description>
  <rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
   <pdf:Producer>{erzeuger}</pdf:Producer></rdf:Description>
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
    return xmp.encode("utf-8")
