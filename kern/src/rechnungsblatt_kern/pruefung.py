"""§14-Prüfung: erzwingt die Pflichtangaben nach § 14 Abs. 4 UStG.

Das Formular erzwingt Vollständigkeit — das ist der eigentliche Wert gegenüber
der Word-Vorlage. Die Prüfung ist blockierend: eine Rechnung mit Befunden wird
nicht erzeugt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import laender
from .modell import Belegtyp, Empfaenger, Profil, Rechnung, Stammdaten, Steuerkategorie

_IBAN_MUSTER = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


@dataclass(frozen=True)
class Befund:
    code: str
    feld: str
    text: str
    #: Blockiert die Erzeugung. ``False`` heisst: auffaellig, aber moeglich.
    #
    # Gebraucht dort, wo die Pruefung sich irren KANN. Das Muster einer
    # auslaendischen USt-IdNr. etwa steht in einer Tabelle, die zu eng sein
    # koennte; ein Kunde mit gueltiger Nummer duerfte dann gar nicht mehr
    # abrechnen. Ein Widerspruch dagegen -- ein franzoesisches Praefix an
    # einer deutschen Anschrift -- kann es nicht geben und blockiert.
    blockierend: bool = True


class UngueltigeRechnung(Exception):
    """Wird geworfen, wenn eine Rechnung trotz Befunden erzeugt werden soll."""

    def __init__(self, befunde: list[Befund]):
        self.befunde = befunde
        super().__init__(
            "Rechnung verletzt Pflichtangaben: "
            + "; ".join(f"[{b.code}] {b.text}" for b in befunde)
        )


def pruefe_paragraph14(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    profil: Profil = Profil.EN16931,
) -> list[Befund]:
    """Liefert alle Befunde. Leere Liste = Rechnung darf erzeugt werden."""
    befunde: list[Befund] = []
    befunde += _pruefe_stammdaten(stammdaten, profil)
    befunde += _pruefe_empfaenger(rechnung.empfaenger, profil)
    befunde += _pruefe_beleg(rechnung)
    befunde += _pruefe_positionen(rechnung, stammdaten)
    return befunde


def erzwinge_paragraph14(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    profil: Profil = Profil.EN16931,
) -> None:
    befunde = [
        b for b in pruefe_paragraph14(rechnung, stammdaten, profil) if b.blockierend
    ]
    if befunde:
        raise UngueltigeRechnung(befunde)


def _pruefe_stammdaten(stammdaten: Stammdaten, profil: Profil) -> list[Befund]:
    befunde: list[Befund] = []
    if not stammdaten.firmierung.strip():
        befunde.append(Befund("S1", "stammdaten.firmierung", "Firmierung fehlt."))
    befunde += _pruefe_anschrift(stammdaten.anschrift, "stammdaten.anschrift", "S2")
    if not (stammdaten.steuernummer or stammdaten.ust_idnr):
        befunde.append(
            Befund(
                "S3",
                "stammdaten.steuernummer",
                "Steuernummer oder USt-IdNr. ist Pflicht (§ 14 Abs. 4 Nr. 2 UStG).",
            )
        )
    if stammdaten.ust_idnr and not re.match(r"^[A-Z]{2}[A-Za-z0-9]{2,12}$", stammdaten.ust_idnr):
        befunde.append(
            Befund("S4", "stammdaten.ust_idnr", "USt-IdNr. hat kein gültiges Format.")
        )
    iban = stammdaten.iban.replace(" ", "").upper()
    if not iban:
        befunde.append(Befund("S5", "stammdaten.iban", "IBAN fehlt."))
    elif not _IBAN_MUSTER.match(iban) or not _iban_pruefsumme_ok(iban):
        befunde.append(Befund("S6", "stammdaten.iban", "IBAN ist ungültig."))
    if profil is Profil.XRECHNUNG:
        if not (stammdaten.kontakt_email and stammdaten.kontakt_telefon and stammdaten.kontakt_name):
            befunde.append(
                Befund(
                    "X2",
                    "stammdaten.kontakt",
                    "XRechnung verlangt Kontaktname, Telefon und E-Mail des "
                    "Rechnungsstellers (BR-DE-2 bis BR-DE-7).",
                )
            )
    return befunde


def _pruefe_empfaenger(empfaenger: Empfaenger, profil: Profil) -> list[Befund]:
    befunde: list[Befund] = []
    if not empfaenger.name.strip():
        befunde.append(Befund("E1", "empfaenger.name", "Name des Empfängers fehlt."))
    befunde += _pruefe_anschrift(empfaenger.anschrift, "empfaenger.anschrift", "E2")
    land = (empfaenger.anschrift.land or "").strip()
    if land and not laender.ist_laenderkennzeichen(land):
        # Ein ausgeschriebenes "Frankreich" landet als CountryID (BT-55) im
        # XML und macht den Beleg ungueltig -- der Validator prueft gegen die
        # ISO-Codeliste. Das faellt sonst erst beim Empfaenger auf.
        befunde.append(
            Befund(
                "E3",
                "empfaenger.anschrift",
                f"„{land}“ ist kein Länderkennzeichen. Erwartet werden zwei "
                "Großbuchstaben nach ISO 3166-1, etwa DE, FR oder CH.",
            )
        )
    befunde += _pruefe_ustidnr_des_empfaengers(empfaenger)
    if profil is Profil.XRECHNUNG:
        if not (empfaenger.leitweg_id or "").strip():
            befunde.append(
                Befund(
                    "X1",
                    "empfaenger.leitweg_id",
                    "XRechnung verlangt eine Leitweg-ID als Käuferreferenz (BT-10, BR-DE-15).",
                )
            )
        if not (empfaenger.email or "").strip():
            befunde.append(
                Befund(
                    "X3",
                    "empfaenger.email",
                    "XRechnung verlangt die elektronische Adresse des Empfängers "
                    "(BT-49, PEPPOL-EN16931-R010).",
                )
            )
    return befunde


def _pruefe_ustidnr_des_empfaengers(empfaenger: Empfaenger) -> list[Befund]:
    """Praefix und Muster der USt-IdNr. des Empfaengers.

    Zwei Stufen mit Absicht: Das **Praefix** muss zum Land passen, sonst
    widersprechen sich zwei Angaben auf demselben Beleg. Das **Muster**
    stammt aus einer Tabelle, die zu eng sein koennte -- es meldet sich als
    Hinweis. Beweisen laesst sich mit beidem nichts: Ob es die Nummer gibt,
    sagt allein die Bestaetigungsabfrage nach § 18e UStG.
    """
    nummer = (empfaenger.ust_idnr or "").strip()
    if not nummer:
        return []
    land = empfaenger.anschrift.land
    befunde: list[Befund] = []

    passt = laender.praefix_passt(nummer, land)
    if passt is False:
        erlaubt = " oder ".join(laender.erlaubte_praefixe(land))
        befunde.append(
            Befund(
                "E4",
                "empfaenger.ust_idnr",
                f"Die USt-IdNr. beginnt mit „{laender.normalisiere_nummer(nummer)[:2]}“, "
                f"die Anschrift liegt in {land}. Erwartet wird „{erlaubt}“.",
            )
        )
        return befunde                      # ein Widerspruch genuegt

    if laender.muster_passt(nummer, land) is False:
        eintrag = laender.land_zu(land)
        name = eintrag.nummer_heisst if eintrag else "USt-IdNr."
        befunde.append(
            Befund(
                "E5",
                "empfaenger.ust_idnr",
                f"Die Nummer sieht für {land} ungewöhnlich aus — dort heißt sie "
                f"{name}. Bitte prüfen; die Rechnung lässt sich trotzdem erzeugen.",
                blockierend=False,
            )
        )
    return befunde


def _pruefe_anschrift(anschrift, feld: str, code: str) -> list[Befund]:
    fehlend = [
        name
        for name, wert in (
            ("Straße", anschrift.strasse),
            ("PLZ", anschrift.plz),
            ("Ort", anschrift.ort),
            ("Land", anschrift.land),
        )
        if not str(wert).strip()
    ]
    if fehlend:
        return [Befund(code, feld, f"Anschrift unvollständig: {', '.join(fehlend)} fehlt.")]
    return []


def _pruefe_beleg(rechnung: Rechnung) -> list[Befund]:
    befunde: list[Befund] = []
    if not rechnung.nummer.strip():
        befunde.append(
            Befund("R1", "rechnung.nummer", "Fortlaufende Rechnungsnummer fehlt.")
        )
    if rechnung.rechnungsdatum is None:
        befunde.append(Befund("R2", "rechnung.rechnungsdatum", "Rechnungsdatum fehlt."))
    if rechnung.leistungsdatum is None and rechnung.leistungszeitraum is None:
        befunde.append(
            Befund(
                "R3",
                "rechnung.leistungsdatum",
                "Leistungsdatum oder Leistungszeitraum ist Pflicht "
                "(§ 14 Abs. 4 Nr. 6 UStG).",
            )
        )
    if rechnung.leistungszeitraum and rechnung.leistungszeitraum.von > rechnung.leistungszeitraum.bis:
        befunde.append(
            Befund("R4", "rechnung.leistungszeitraum", "Leistungszeitraum: Beginn liegt nach Ende.")
        )
    if rechnung.typ in (Belegtyp.GUTSCHRIFT, Belegtyp.KORREKTUR):
        if not (rechnung.bezugs_nummer or "").strip():
            befunde.append(
                Befund(
                    "G1",
                    "rechnung.bezugs_nummer",
                    f"{rechnung.typ.titel} braucht die Nummer der Ursprungsrechnung.",
                )
            )
    return befunde


def _pruefe_positionen(rechnung: Rechnung, stammdaten: Stammdaten) -> list[Befund]:
    befunde: list[Befund] = []
    if not rechnung.positionen:
        befunde.append(
            Befund("P0", "rechnung.positionen", "Mindestens eine Position ist Pflicht.")
        )
        return befunde

    for index, position in enumerate(rechnung.positionen, start=1):
        feld = f"rechnung.positionen[{index}]"
        if not position.bezeichnung.strip():
            befunde.append(Befund("P1", feld, f"Position {index}: Bezeichnung fehlt."))
        if position.menge <= 0:
            befunde.append(Befund("P2", feld, f"Position {index}: Menge muss größer 0 sein."))
        if not position.einheit.strip():
            befunde.append(Befund("P3", feld, f"Position {index}: Einheit fehlt."))
        if position.einzelpreis < 0:
            befunde.append(
                Befund("P4", feld, f"Position {index}: Einzelpreis darf nicht negativ sein.")
            )
        if -position.einzelpreis.as_tuple().exponent > 2:
            # **Mehr als zwei Nachkommastellen ergeben ein widersprüchliches
            # XML.** Der Preis wird dort auf zwei Stellen ausgewiesen, der
            # Positionsbetrag aber aus dem ungerundeten Wert gerechnet: Bei
            # 0,333 € × 3 rechnet ein Prüfer 0,33 × 3 = 0,99 gegen einen
            # ausgewiesenen Betrag von 1,00 und beanstandet die Rechnung.
            #
            # Abweisen statt still runden: Gerundet stimmte zwar das XML,
            # die Summe wiche aber von der ab, die der Kunde erwartet — und
            # er merkte es nicht.
            befunde.append(
                Befund(
                    "P5",
                    feld,
                    f"Position {index}: Einzelpreis darf höchstens zwei "
                    "Nachkommastellen haben. Bei krummen Preisen je Einheit "
                    "besser die Menge anders wählen (etwa 3 Stück zu 1,00 € "
                    "statt 1 Stück zu 0,333 €).",
                )
            )

    kategorien = {position.steuer for position in rechnung.positionen}
    if stammdaten.kleinunternehmer and kategorien != {Steuerkategorie.KLEINUNTERNEHMER}:
        befunde.append(
            Befund(
                "K1",
                "rechnung.positionen",
                "Kleinunternehmer nach § 19 UStG dürfen keine Umsatzsteuer ausweisen — "
                "alle Positionen müssen die Kategorie KLEINUNTERNEHMER tragen.",
            )
        )
    if not stammdaten.kleinunternehmer and Steuerkategorie.KLEINUNTERNEHMER in kategorien:
        befunde.append(
            Befund(
                "K2",
                "rechnung.positionen",
                "Kategorie KLEINUNTERNEHMER ist nur zulässig, wenn die Stammdaten "
                "Kleinunternehmer nach § 19 UStG ausweisen.",
            )
        )
    if Steuerkategorie.REVERSE_CHARGE in kategorien:
        if not (rechnung.empfaenger.ust_idnr or "").strip():
            befunde.append(
                Befund(
                    "RC1",
                    "empfaenger.ust_idnr",
                    "Reverse Charge verlangt die USt-IdNr. des Leistungsempfängers.",
                )
            )
        if not (stammdaten.ust_idnr or "").strip():
            befunde.append(
                Befund(
                    "RC2",
                    "stammdaten.ust_idnr",
                    "Reverse Charge verlangt die USt-IdNr. des Rechnungsstellers.",
                )
            )
    if Steuerkategorie.IG_LIEFERUNG in kategorien:
        if not (rechnung.empfaenger.ust_idnr or "").strip() or not (
            stammdaten.ust_idnr or ""
        ).strip():
            befunde.append(
                Befund(
                    "IG1",
                    "empfaenger.ust_idnr",
                    "Innergemeinschaftliche Lieferung verlangt die USt-IdNr. "
                    "beider Parteien.",
                )
            )
    befunde += _pruefe_kategorie_gegen_land(rechnung, stammdaten, kategorien)
    return befunde


def _pruefe_kategorie_gegen_land(
    rechnung: Rechnung,
    stammdaten: Stammdaten,
    kategorien: set[Steuerkategorie],
) -> list[Befund]:
    """Passt die gewaehlte Steuerkategorie zum Sitz des Empfaengers?

    Zwei Regeln, beide blockierend, beide ohne Ermessen:

    **Reverse Charge gibt es nur im Gemeinschaftsgebiet.** Art. 196
    MwStSystRL bindet die Steuerschuld des Empfaengers an einen anderen
    Mitgliedstaat. Bei einem Schweizer Kunden waere die Aussage schlicht
    falsch -- dort gilt Schweizer Recht. Deutschland selbst bleibt erlaubt:
    § 13b UStG kennt inlaendisches Reverse Charge (Bauleistungen,
    Gebaeudereinigung, Schrott), und das traegt denselben Code AE.

    **Nicht steuerbar vertraegt sich mit nichts.** EN 16931 laesst neben
    einer O-Position keine andere Steuerkategorie im selben Beleg zu; der
    Validator lehnt eine gemischte Rechnung ab. Hier abzufangen ist
    freundlicher, als den Kunden mit einem Schematron-Fehler stehen zu
    lassen.

    Zu O und Inland sagt die Pruefung bewusst NICHTS: Eine Leistung an einen
    deutschen Kunden kann sehr wohl im Ausland steuerbar sein -- ein
    Grundstueck in Wien etwa, § 3a Abs. 3 Nr. 1 UStG. Wer das blockierte,
    laege falsch.
    """
    befunde: list[Befund] = []
    land = (rechnung.empfaenger.anschrift.land or "").strip().upper()

    # RC3 ist bewusst uebersprungen: In did0m-verwaltung traegt diese
    # Kennung seit dem 10.09.2026 ein falsches Nummernformat. RC1 und RC2
    # meinen in beiden Systemen dasselbe -- das soll so bleiben, und dann
    # darf RC3 hier nicht etwas anderes heissen.
    if Steuerkategorie.REVERSE_CHARGE in kategorien and land:
        if laender.ist_laenderkennzeichen(land) and not laender.ist_eu(land):
            befunde.append(
                Befund(
                    "RC4",
                    "rechnung.positionen",
                    f"Reverse Charge setzt einen Empfänger im Gemeinschaftsgebiet "
                    f"voraus (Art. 196 MwStSystRL); {land} gehört nicht dazu. "
                    "Für eine sonstige Leistung dorthin ist „Nicht steuerbar“ "
                    "die richtige Kategorie, für eine Warenlieferung „Ausfuhr“.",
                )
            )

        if laender.ist_eu_ausland(land):
            # Kein Fehler am Beleg, sondern eine Pflicht daneben: § 18a UStG
            # verlangt fuer innergemeinschaftliche sonstige Leistungen die
            # Zusammenfassende Meldung ans BZSt, vierteljaehrlich. Sie haengt
            # an der Leistung und nicht am eigenen Steuerstatus -- die
            # Kleinunternehmerregelung befreit davon NICHT. Das ist die
            # Pflicht, die am haeufigsten uebersehen wird.
            #
            # Nur beim EU-Ausland: Fuer die Schweiz gibt es keine ZM, und
            # § 13b im Inland ist ohnehin ein anderer Tatbestand.
            befunde.append(
                Befund(
                    "ZM1",
                    "rechnung.positionen",
                    "Denken Sie an die Zusammenfassende Meldung: "
                    "Innergemeinschaftliche sonstige Leistungen gehören "
                    "vierteljährlich ans BZSt (§ 18a UStG) — auch als "
                    "Kleinunternehmer.",
                    blockierend=False,
                )
            )

    if Steuerkategorie.NICHT_STEUERBAR in kategorien:
        # Folge aus BR-O-02: Bei "nicht steuerbar" darf die eigene USt-IdNr.
        # nicht im Beleg stehen (siehe cii.py). Der Verkaeufer weist sich
        # dann ueber seine Steuernummer aus -- hat er keine, laesst sich
        # BR-CO-26 nicht mehr erfuellen und es entstuende ein ungueltiger
        # Beleg. Lieber hier ein klarer Satz als dort ein Schematron-Fehler.
        if not (stammdaten.steuernummer or "").strip():
            befunde.append(
                Befund(
                    "O2",
                    "stammdaten.steuernummer",
                    "Für eine nicht steuerbare Leistung darf die USt-IdNr. nicht "
                    "auf der Rechnung stehen (EN 16931, BR-O-2). Tragen Sie "
                    "deshalb Ihre Steuernummer in den Stammdaten ein — ohne sie "
                    "fehlt dem Beleg jede Kennung des Rechnungsstellers.",
                )
            )

    if Steuerkategorie.NICHT_STEUERBAR in kategorien and len(kategorien) > 1:
        andere = ", ".join(
            sorted(
                k.name for k in kategorien if k is not Steuerkategorie.NICHT_STEUERBAR
            )
        )
        befunde.append(
            Befund(
                "O1",
                "rechnung.positionen",
                "„Nicht steuerbar“ lässt sich nicht mit einer anderen "
                f"Steuerkategorie auf demselben Beleg mischen (hier: {andere}). "
                "EN 16931 verbietet das; die Rechnung würde bei der Prüfung "
                "abgelehnt. Bitte zwei getrennte Rechnungen schreiben.",
            )
        )
    return befunde


def _iban_pruefsumme_ok(iban: str) -> bool:
    """MOD-97-Prüfung nach ISO 13616."""
    umgestellt = iban[4:] + iban[:4]
    ziffern = "".join(str(int(zeichen, 36)) for zeichen in umgestellt)
    return int(ziffern) % 97 == 1
