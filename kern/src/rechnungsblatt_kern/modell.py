"""Datenmodell des Rechnungskerns.

Beträge sind durchgängig ``Decimal``; Rundung geschieht ausschließlich in
:mod:`rechnungsblatt_kern.summen` mit ``ROUND_HALF_UP`` auf zwei
Nachkommastellen. Floats haben in diesem Modell nichts verloren.
"""

from __future__ import annotations

import datetime as _dt
import enum
from dataclasses import dataclass, field
from decimal import Decimal


class Steuerkategorie(enum.Enum):
    """Die im MVP unterstützten Steuersätze bzw. Befreiungstatbestände.

    ``code`` ist der EN-16931-Kategoriecode (UNCL 5305), ``satz`` der
    Prozentsatz. Befreiungen tragen den Pflichthinweis, der sowohl auf dem
    Blatt als auch als ExemptionReason im XML erscheint.
    """

    UST_19 = ("S", Decimal("19"), None)
    UST_7 = ("S", Decimal("7"), None)
    UST_0 = ("Z", Decimal("0"), None)
    KLEINUNTERNEHMER = (
        "E",
        Decimal("0"),
        "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG.",
    )
    REVERSE_CHARGE = (
        "AE",
        Decimal("0"),
        "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge).",
    )
    IG_LIEFERUNG = (
        "K",
        Decimal("0"),
        "Steuerfreie innergemeinschaftliche Lieferung.",
    )
    AUSFUHR = ("G", Decimal("0"), "Steuerfreie Ausfuhrlieferung.")

    def __init__(self, code: str, satz: Decimal, hinweis: str | None):
        self.code = code
        self.satz = satz
        self.hinweis = hinweis

    @property
    def befreit(self) -> bool:
        return self.hinweis is not None


class Belegtyp(enum.Enum):
    """UNCL-1001-Typcodes der unterstützten Belege."""

    RECHNUNG = 380
    GUTSCHRIFT = 381
    KORREKTUR = 384

    @property
    def titel(self) -> str:
        return {
            Belegtyp.RECHNUNG: "Rechnung",
            Belegtyp.GUTSCHRIFT: "Gutschrift",
            Belegtyp.KORREKTUR: "Rechnungskorrektur",
        }[self]


class Profil(enum.Enum):
    """Zielprofil des CII-XML."""

    EN16931 = "urn:cen.eu:en16931:2017"
    XRECHNUNG = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"


@dataclass(frozen=True)
class Anschrift:
    strasse: str
    plz: str
    ort: str
    land: str = "DE"  # ISO 3166-1 alpha-2


@dataclass(frozen=True)
class Stammdaten:
    """Einmalig erfasste Daten des Rechnungsstellers."""

    firmierung: str
    anschrift: Anschrift
    steuernummer: str | None = None
    ust_idnr: str | None = None
    iban: str = ""
    bic: str | None = None
    zahlungsziel_tage: int = 14
    kontakt_name: str | None = None
    kontakt_email: str | None = None
    kontakt_telefon: str | None = None
    kleinunternehmer: bool = False
    artikelnummern: bool = False  # steuert nur die Anzeige in der Vorschau


@dataclass(frozen=True)
class Empfaenger:
    name: str
    anschrift: Anschrift
    ust_idnr: str | None = None
    leitweg_id: str | None = None  # BT-10, Pflicht für XRechnung an Behörden
    email: str | None = None  # BT-49 elektronische Adresse, Pflicht für XRechnung


@dataclass(frozen=True)
class Position:
    bezeichnung: str
    menge: Decimal
    einheit: str  # UN/ECE-Rec-20-Code, z. B. "C62" (Stück), "HUR" (Stunde)
    einzelpreis: Decimal  # Netto je Einheit
    steuer: Steuerkategorie
    beschreibung: str | None = None
    artikelnummer: str | None = None  # BT-155, Artikelnummer des Verkäufers


@dataclass(frozen=True)
class Zeitraum:
    von: _dt.date
    bis: _dt.date


@dataclass(frozen=True)
class Rechnung:
    """Ein einzelner Beleg. Entsteht je Vorgang aus den Formulardaten."""

    nummer: str
    rechnungsdatum: _dt.date
    empfaenger: Empfaenger
    positionen: tuple[Position, ...] = field(default_factory=tuple)
    leistungsdatum: _dt.date | None = None
    leistungszeitraum: Zeitraum | None = None
    rabatt_betrag: Decimal | None = None  # Nettominderung auf die Summe
    rabatt_prozent: Decimal | None = None  # BT-138, nur zur Angabe; maßgeblich
    # bleibt rabatt_betrag — siehe summen.rabatt_aus_prozent().
    rabatt_grund: str = "Rabatt"
    freitext: str | None = None
    waehrung: str = "EUR"
    typ: Belegtyp = Belegtyp.RECHNUNG
    bezugs_nummer: str | None = None  # Pflicht bei GUTSCHRIFT/KORREKTUR
    bezugs_datum: _dt.date | None = None
    faelligkeit: _dt.date | None = None
    verwendungszweck: str | None = None  # BT-83, erscheint auf Blatt und im XML


class Layoutvariante(enum.Enum):
    """Vorgefertigte, getestete Blattlayouts — bewusst keine freie
    Positionierung (Übergabe §7: wenige verständliche Entscheidungen
    statt eines Editors)."""

    KLASSISCH = "klassisch"  # Belegdaten als Block rechts, klare Linien
    KOMPAKT = "kompakt"  # Belegdaten als Zeile, enge Abstände — viele Positionen
    MODERN = "modern"  # großer Titel, graue Linien, mehr Weißraum
    ZEBRA = "zebra"  # getönte Wechselzeilen statt Trennlinien
    LUFTIG = "luftig"  # ohne Linien, Gliederung nur über Abstände
    DOPPELT = "doppelt"  # sehr eng, Belegdaten zweispaltig


class Schriftgrad(enum.Enum):
    """Grundschriftgröße des Blatts in Punkt."""

    KOMPAKT = 9.0
    NORMAL = 10.0
    GROSS = 11.0


@dataclass(frozen=True)
class Blattgestaltung:
    """Gestaltung des Blatts: Schrift, Grad, Layoutvariante, Schalter.

    ``schrift`` ist ein Schlüssel aus dem kuratierten Katalog
    (:data:`rechnungsblatt_kern.blatt.SCHRIFTEN_KATALOG`) — nur mitgelieferte,
    einbettbare Schriften, damit die PDF/A-Garantie erhalten bleibt.
    """

    schrift: str = "liberation-sans"
    schriftgrad: Schriftgrad = Schriftgrad.NORMAL
    layout: Layoutvariante = Layoutvariante.KLASSISCH
    belegdaten_als_zeile: bool = False  # KOMPAKT erzwingt die Zeile ohnehin
    # Akzentfarbe quer zu allen Layouts: aus = schwarze bzw. graue Linien wie
    # bisher, an = Titel und Linien tragen die Farbe. ZEBRA tönt damit auch
    # seine Wechselzeilen.
    akzent_an: bool = False
    akzentfarbe: str = "#136f83"


@dataclass(frozen=True)
class Schreibzone:
    """Bewusst nur zwei Werte: wo endet der Kopf, wo beginnt der Fuß.

    Beide Werte in Millimetern, gemessen vom oberen bzw. unteren Blattrand
    eines A4-Bogens. Der Rechnungsinhalt wird ausschließlich dazwischen
    gerendert.
    """

    kopf_ende_mm: float = 45.0
    fuss_beginn_mm: float = 25.0

    A4_HOEHE_MM = 297.0
    A4_BREITE_MM = 210.0
    MINDESTHOEHE_MM = 100.0

    def __post_init__(self) -> None:
        nutzbar = self.A4_HOEHE_MM - self.kopf_ende_mm - self.fuss_beginn_mm
        if self.kopf_ende_mm < 0 or self.fuss_beginn_mm < 0:
            raise ValueError("Schreibzonen-Werte dürfen nicht negativ sein.")
        if nutzbar < self.MINDESTHOEHE_MM:
            raise ValueError(
                f"Schreibzone zu klein: {nutzbar:.0f} mm nutzbar, "
                f"mindestens {self.MINDESTHOEHE_MM:.0f} mm nötig."
            )

    @property
    def nutzhoehe_mm(self) -> float:
        return self.A4_HOEHE_MM - self.kopf_ende_mm - self.fuss_beginn_mm
