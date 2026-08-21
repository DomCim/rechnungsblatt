"""Rechenwerk: Zeilensummen, Steuerkörbe, Rabattverteilung.

Kernregeln:
- alle Beträge ``Decimal``, Rundung ``ROUND_HALF_UP`` auf zwei Nachkommastellen,
- Summen werden je Steuerkategorie aufgeschlüsselt,
- ein Dokumentrabatt wird anteilig auf die Körbe verteilt; Rundungsdifferenzen
  gehen in den größten Korb, damit die Anteile exakt den Rabatt ergeben.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .modell import Position, Rechnung, Steuerkategorie

ZWEI_STELLEN = Decimal("0.01")


def runden(betrag: Decimal) -> Decimal:
    """Kaufmännisch auf zwei Nachkommastellen runden (ROUND_HALF_UP)."""
    return betrag.quantize(ZWEI_STELLEN, rounding=ROUND_HALF_UP)


def zeilensumme(position: Position) -> Decimal:
    return runden(position.menge * position.einzelpreis)


@dataclass(frozen=True)
class Steuerkorb:
    """Summen einer Steuerkategorie."""

    kategorie: Steuerkategorie
    zeilensumme: Decimal  # Summe der Positionsnettobeträge
    rabatt: Decimal  # anteiliger Dokumentrabatt
    basis: Decimal  # zeilensumme - rabatt
    steuer: Decimal  # runden(basis * satz)


@dataclass(frozen=True)
class Summen:
    zeilensumme: Decimal
    rabatt: Decimal
    steuerbasis: Decimal
    steuer: Decimal
    brutto: Decimal
    koerbe: tuple[Steuerkorb, ...]


def berechne_summen(rechnung: Rechnung) -> Summen:
    """Berechnet alle Beträge des Belegs aus den Positionen.

    PDF und XML entstehen beide aus dem Ergebnis dieser Funktion — nirgends
    sonst wird gerechnet.
    """
    if not rechnung.positionen:
        raise ValueError("Rechnung ohne Positionen hat keine Summen.")

    zeilen_je_kategorie: dict[Steuerkategorie, Decimal] = {}
    for position in rechnung.positionen:
        kategorie = position.steuer
        zeilen_je_kategorie[kategorie] = (
            zeilen_je_kategorie.get(kategorie, Decimal("0")) + zeilensumme(position)
        )

    gesamt_zeilen = sum(zeilen_je_kategorie.values(), Decimal("0"))
    rabatt = runden(rechnung.rabatt_betrag) if rechnung.rabatt_betrag else Decimal("0.00")
    if rabatt < 0:
        raise ValueError("Rabatt darf nicht negativ sein.")
    if rabatt > gesamt_zeilen:
        raise ValueError("Rabatt übersteigt die Zeilensumme.")

    rabatt_je_kategorie = _verteile_rabatt(zeilen_je_kategorie, rabatt, gesamt_zeilen)

    koerbe: list[Steuerkorb] = []
    for kategorie, zeilen in sorted(zeilen_je_kategorie.items(), key=lambda kv: kv[0].name):
        korb_rabatt = rabatt_je_kategorie[kategorie]
        basis = zeilen - korb_rabatt
        steuer = runden(basis * kategorie.satz / Decimal("100"))
        koerbe.append(
            Steuerkorb(
                kategorie=kategorie,
                zeilensumme=zeilen,
                rabatt=korb_rabatt,
                basis=basis,
                steuer=steuer,
            )
        )

    steuerbasis = sum((korb.basis for korb in koerbe), Decimal("0"))
    steuer_gesamt = sum((korb.steuer for korb in koerbe), Decimal("0"))
    return Summen(
        zeilensumme=gesamt_zeilen,
        rabatt=rabatt,
        steuerbasis=steuerbasis,
        steuer=steuer_gesamt,
        brutto=steuerbasis + steuer_gesamt,
        koerbe=tuple(koerbe),
    )


def _verteile_rabatt(
    zeilen_je_kategorie: dict[Steuerkategorie, Decimal],
    rabatt: Decimal,
    gesamt: Decimal,
) -> dict[Steuerkategorie, Decimal]:
    """Verteilt den Dokumentrabatt anteilig und rundungsfest auf die Körbe."""
    anteile: dict[Steuerkategorie, Decimal] = {
        kategorie: Decimal("0.00") for kategorie in zeilen_je_kategorie
    }
    if rabatt == 0 or gesamt == 0:
        return anteile

    verteilt = Decimal("0.00")
    kategorien = sorted(zeilen_je_kategorie, key=lambda k: k.name)
    for kategorie in kategorien:
        anteil = runden(rabatt * zeilen_je_kategorie[kategorie] / gesamt)
        anteile[kategorie] = anteil
        verteilt += anteil

    differenz = rabatt - verteilt
    if differenz != 0:
        groesster = max(kategorien, key=lambda k: (zeilen_je_kategorie[k], k.name))
        anteile[groesster] += differenz
    return anteile
