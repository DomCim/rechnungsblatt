"""Länder, Umsatzsteuer-Identifikationsnummern und der Reverse-Charge-Begriff.

**Warum eine Tabelle und kein Sonderweg je Land.** Die Steuerregel ist für
Frankreich, Polen und Portugal dieselbe: eine sonstige Leistung an einen
Unternehmer im übrigen Gemeinschaftsgebiet wird nach § 3a Abs. 2 UStG dort
besteuert, wo der Empfänger sitzt, und der Empfänger schuldet die Steuer
(Art. 196 MwStSystRL). Verschieden sind nur **Daten**: wie die Nummer
aussieht, welches Präfix sie trägt, wie sie beim Kunden heißt und wie der
Pflichthinweis in seiner Sprache lautet.

**Drei Fallen, an denen selbstgebaute Prüfungen scheitern:**

- **Griechenland** führt umsatzsteuerlich ``EL``, obwohl sein Länderkennzeichen
  ``GR`` ist. Wer Präfix und Land gleichsetzt, lehnt jede griechische Nummer ab.
- **Österreich** ist das einzige Land mit einem Buchstaben direkt hinter dem
  Präfix (``ATU12345678``). Ein ``^[A-Z]{2}\\d+$`` wirft es weg — zusammen mit
  Irland, Spanien und den Niederlanden.
- **Nordirland** trägt seit dem Austritt ``XI`` für Warenlieferungen, liegt aber
  postalisch in ``GB``. Für **sonstige Leistungen** gehört es nicht mehr zum
  Gemeinschaftsgebiet; es steht deshalb NICHT in ``EU_LAENDER``, sein Präfix
  wird aber anerkannt.

**Was die Muster leisten und was nicht.** Sie erkennen Zahlendreher, ein
fehlendes Präfix und eine Nummer aus dem falschen Land. Sie beweisen **nicht**,
dass es die Nummer gibt und sie dem Kunden gehört — das kann allein die
qualifizierte Bestätigungsabfrage nach § 18e UStG (MIAS/VIES beim BZSt).
Deshalb ist ein verletztes Muster ein **Hinweis** und kein Fehler: Steht in
dieser Tabelle ein Muster zu eng, dürfte sonst ein Kunde mit gültiger Nummer
gar nicht mehr abrechnen. Das falsche **Präfix** ist dagegen ein Widerspruch,
den es nicht geben kann — der blockiert.

Prüfziffern bleiben bewusst außen vor: Jedes Land rechnet anders, mehrere
Verfahren sind nicht amtlich veröffentlicht, und eine faelschlich abgelehnte
gültige Nummer kostet mehr, als ein durchgelassener Zahlendreher einbringt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Land:
    """Ein Mitgliedstaat mit dem, was seine Nummer ausmacht."""

    name: str
    #: Präfix der USt-IdNr. Weicht nur bei Griechenland vom Länderkennzeichen ab.
    praefix: str
    #: Muster der vollständigen Nummer einschließlich Präfix.
    muster: str
    #: Wie die Nummer beim Kunden heißt — für die Beschriftung im Formular.
    nummer_heisst: str
    #: Der Reverse-Charge-Begriff in der Landessprache, für den Fußtext.
    umkehr_heisst: str


# Die 27 Mitgliedstaaten. Schlüssel ist das Länderkennzeichen nach
# ISO 3166-1 alpha-2, wie es in der Anschrift und als BT-55 im XML steht.
EU_LAENDER: dict[str, Land] = {
    "BE": Land("Belgien", "BE", r"BE\d{10}", "btw-nummer", "btw verlegd"),
    "BG": Land("Bulgarien", "BG", r"BG\d{9,10}", "ДДС номер", "обратно начисляване"),
    "CZ": Land("Tschechien", "CZ", r"CZ\d{8,10}", "DIČ", "daň odvede zákazník"),
    "DK": Land("Dänemark", "DK", r"DK\d{8}", "momsnummer", "omvendt betalingspligt"),
    "DE": Land("Deutschland", "DE", r"DE\d{9}", "USt-IdNr.", "Reverse Charge"),
    "EE": Land("Estland", "EE", r"EE\d{9}", "KMKR number", "pöördmaksustamine"),
    "IE": Land(
        "Irland", "IE",
        # Zwei amtliche Formen: die alte mit Buchstabe oder Sonderzeichen an
        # zweiter Stelle, die neue mit zwei Buchstaben am Ende.
        r"IE(\d{7}[A-W]|\d[A-Z0-9+*]\d{5}[A-W]|\d{7}[A-W][A-I])",
        "VAT number", "reverse charge",
    ),
    "GR": Land("Griechenland", "EL", r"EL\d{9}", "ΑΦΜ", "αντίστροφη επιβάρυνση"),
    "ES": Land("Spanien", "ES", r"ES[A-Z0-9]\d{7}[A-Z0-9]", "NIF-IVA",
               "inversión del sujeto pasivo"),
    "FR": Land("Frankreich", "FR", r"FR[A-Z0-9]{2}\d{9}",
               "TVA intracommunautaire", "autoliquidation"),
    "HR": Land("Kroatien", "HR", r"HR\d{11}", "OIB / PDV ID", "prijenos porezne obveze"),
    "IT": Land("Italien", "IT", r"IT\d{11}", "partita IVA", "inversione contabile"),
    "CY": Land("Zypern", "CY", r"CY\d{8}[A-Z]", "ΑΦΜ", "αντίστροφη επιβάρυνση"),
    "LV": Land("Lettland", "LV", r"LV\d{11}", "PVN numurs", "apgrieztā nodokļa maksāšana"),
    "LT": Land("Litauen", "LT", r"LT(\d{9}|\d{12})", "PVM kodas",
               "atvirkštinis apmokestinimas"),
    "LU": Land("Luxemburg", "LU", r"LU\d{8}", "numéro de TVA", "autoliquidation"),
    "HU": Land("Ungarn", "HU", r"HU\d{8}", "közösségi adószám", "fordított adózás"),
    "MT": Land("Malta", "MT", r"MT\d{8}", "VAT number", "reverse charge"),
    "NL": Land("Niederlande", "NL", r"NL\d{9}B\d{2}", "btw-identificatienummer",
               "btw verlegd"),
    "AT": Land("Österreich", "AT", r"ATU\d{8}", "UID-Nummer",
               "Übergang der Steuerschuld"),
    "PL": Land("Polen", "PL", r"PL\d{10}", "NIP", "odwrotne obciążenie"),
    "PT": Land("Portugal", "PT", r"PT\d{9}", "NIF", "autoliquidação"),
    "RO": Land("Rumänien", "RO", r"RO\d{2,10}", "cod de TVA", "taxare inversă"),
    "SI": Land("Slowenien", "SI", r"SI\d{8}", "ID za DDV", "obrnjena davčna obveznost"),
    "SK": Land("Slowakei", "SK", r"SK\d{10}", "IČ DPH", "prenesenie daňovej povinnosti"),
    "FI": Land("Finnland", "FI", r"FI\d{8}", "ALV-numero", "käännetty verovelvollisuus"),
    "SE": Land("Schweden", "SE", r"SE\d{12}", "momsregistreringsnummer",
               "omvänd betalningsskyldighet"),
}

# Präfixe, die es gibt, ohne dass das Land zum Gemeinschaftsgebiet zaehlt.
# Nordirland liegt postalisch in GB und trägt XI nur für Warenlieferungen.
SONDERPRAEFIXE: dict[str, tuple[str, ...]] = {"GB": ("XI", "GB")}

_LAENDERKENNZEICHEN = re.compile(r"^[A-Z]{2}$")


def ist_laenderkennzeichen(land: str) -> bool:
    """Zwei Großbuchstaben nach ISO 3166-1 alpha-2 — mehr prüft BT-55 auch nicht."""
    return bool(_LAENDERKENNZEICHEN.match((land or "").strip()))


def ist_eu(land: str) -> bool:
    """Gehört das Land zum Gemeinschaftsgebiet? Deutschland zaehlt mit."""
    return (land or "").strip().upper() in EU_LAENDER


def ist_eu_ausland(land: str) -> bool:
    """EU, aber nicht Deutschland — der Fall für Art. 196 MwStSystRL."""
    kennung = (land or "").strip().upper()
    return kennung in EU_LAENDER and kennung != "DE"


def land_zu(kennung: str) -> Land | None:
    return EU_LAENDER.get((kennung or "").strip().upper())


def erlaubte_praefixe(land: str) -> tuple[str, ...]:
    """Welche Präfixe eine Nummer aus diesem Land tragen darf."""
    kennung = (land or "").strip().upper()
    eintrag = EU_LAENDER.get(kennung)
    if eintrag is not None:
        return (eintrag.praefix,)
    return SONDERPRAEFIXE.get(kennung, ())


def normalisiere_nummer(nummer: str) -> str:
    """Leerzeichen, Punkte und Bindestriche weg, Großbuchstaben.

    Kunden schreiben ``FR 53 987 550 159`` oder ``ATU 1234 5678``. Das ist
    dieselbe Nummer; daran soll keine Prüfung scheitern.
    """
    return re.sub(r"[\s.\-/]", "", (nummer or "")).upper()


def praefix_passt(nummer: str, land: str) -> bool | None:
    """Passt das Präfix der Nummer zum Land?

    ``None``, wenn sich nichts sagen laesst — Nummer leer, Land unbekannt
    oder ausserhalb der Tabelle. Schweigen ist hier besser als raten.
    """
    sauber = normalisiere_nummer(nummer)
    erlaubt = erlaubte_praefixe(land)
    if not sauber or not erlaubt:
        return None
    return sauber[:2] in erlaubt


def muster_passt(nummer: str, land: str) -> bool | None:
    """Entspricht die Nummer dem Muster ihres Landes?

    ``None`` für alles ausserhalb der Tabelle. Ein ``False`` ist ein
    **Hinweis**, kein Fehler — siehe Modulkopf.
    """
    eintrag = land_zu(land)
    sauber = normalisiere_nummer(nummer)
    if eintrag is None or not sauber:
        return None
    return bool(re.fullmatch(eintrag.muster, sauber))


def befreiungsgrund(kategorie, land: str) -> str | None:
    """Der Pflichthinweis zum Steuerfall — beim Auslandskunden ergänzt.

    Auf dem Blatt und als ``ExemptionReason`` im XML steht sonst der Text
    der Kategorie. Bei **Reverse Charge in einen anderen Mitgliedstaat**
    lohnt sich mehr: Die Buchhaltung des Empfängers sucht den Begriff
    ihrer eigenen Sprache und die Rechtsgrundlage, auf die sie ihre
    Steuerschuld stützt.

    **Nur beim EU-Ausland.** Inländisches Reverse Charge nach § 13b UStG
    (Bauleistungen, Gebäudereinigung, Schrott) trägt denselben Code ``AE``
    — dort wäre „autoliquidation“ und Art. 196 MwStSystRL schlicht falsch.
    Ebenso im Drittland: Was ein Schweizer Empfänger schuldet, regelt
    Schweizer Recht.

    Die Pflichtangabe nach § 14a Abs. 5 UStG bleibt in jedem Fall der
    deutsche Satz — ergänzt wird, nicht ersetzt.
    """
    grund = getattr(kategorie, "hinweis", None)
    if not grund or getattr(kategorie, "code", "") != "AE":
        return grund
    eintrag = land_zu(land)
    if eintrag is None or (land or "").strip().upper() == "DE":
        return grund
    return (
        f"{grund.rstrip('.')} · {eintrag.umkehr_heisst} "
        f"(Art. 196 MwStSystRL)."
    )
