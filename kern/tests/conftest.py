import datetime as dt
from decimal import Decimal

import pytest

from rechnungsblatt_kern import (
    Anschrift,
    Empfaenger,
    Position,
    Rechnung,
    Stammdaten,
    Steuerkategorie,
)


@pytest.fixture
def stammdaten() -> Stammdaten:
    return Stammdaten(
        firmierung="Muster & Partner GmbH",
        anschrift=Anschrift(strasse="Bahnhofstr. 12", plz="95119", ort="Naila"),
        steuernummer="223/456/78901",
        ust_idnr="DE123456789",
        iban="DE14 7805 0000 0001 2345 67",
        bic="BYLADEM1HOF",
        zahlungsziel_tage=14,
        kontakt_name="Max Muster",
        kontakt_email="info@muster-partner.de",
        kontakt_telefon="09282 12345",
    )


@pytest.fixture
def empfaenger() -> Empfaenger:
    return Empfaenger(
        name="Beispielkunde GmbH",
        anschrift=Anschrift(strasse="Industriestr. 5", plz="95028", ort="Hof"),
    )


@pytest.fixture
def rechnung(empfaenger) -> Rechnung:
    return Rechnung(
        nummer="RE-2026-0042",
        rechnungsdatum=dt.date(2026, 8, 21),
        empfaenger=empfaenger,
        leistungsdatum=dt.date(2026, 8, 20),
        faelligkeit=dt.date(2026, 9, 4),
        positionen=(
            Position(
                bezeichnung="Montagearbeiten",
                menge=Decimal("8"),
                einheit="HUR",
                einzelpreis=Decimal("25.00"),
                steuer=Steuerkategorie.UST_19,
            ),
        ),
    )
