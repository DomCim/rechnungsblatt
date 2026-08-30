"""§14-Prüfung: erzwingt die Pflichtangaben nach § 14 Abs. 4 UStG.

Das Formular erzwingt Vollständigkeit — das ist der eigentliche Wert gegenüber
der Word-Vorlage. Die Prüfung ist blockierend: eine Rechnung mit Befunden wird
nicht erzeugt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .modell import Belegtyp, Empfaenger, Profil, Rechnung, Stammdaten, Steuerkategorie

_IBAN_MUSTER = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


@dataclass(frozen=True)
class Befund:
    code: str
    feld: str
    text: str


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
    befunde = pruefe_paragraph14(rechnung, stammdaten, profil)
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
    return befunde


def _iban_pruefsumme_ok(iban: str) -> bool:
    """MOD-97-Prüfung nach ISO 13616."""
    umgestellt = iban[4:] + iban[:4]
    ziffern = "".join(str(int(zeichen, 36)) for zeichen in umgestellt)
    return int(ziffern) % 97 == 1
