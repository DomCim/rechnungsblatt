"""Gemeinsame Testvorbereitung der Web-Schicht.

Die Web-Tests brauchen eine echte PostgreSQL-Datenbank — die Kontenschicht
ist ohne sie nicht sinnvoll prüfbar. Fehlt die Datenbank, werden die Tests
übersprungen statt zu scheitern, damit ein reiner Kern-Lauf möglich bleibt.

Lokal genügt:

    docker compose -f deploy/docker-compose.local.yml up -d datenbank

oder eine eigene Instanz über TEST_DATENBANK_URL.
"""

from __future__ import annotations

import os

import pytest

STANDARD_URL = "postgresql://rechnungsblatt:rechnungsblatt@127.0.0.1:5432/rechnungsblatt"
TEST_URL = os.environ.get("TEST_DATENBANK_URL", STANDARD_URL)


@pytest.fixture(scope="session")
def datenbank():
    from rechnungsblatt_web import konten

    konten.schliesse_pool()
    konten.DATENBANK_URL = TEST_URL
    try:
        konten.richte_schema_ein()
    except Exception as fehler:  # psycopg wirft je nach Ursache Verschiedenes
        konten.schliesse_pool()
        pytest.skip(f"Keine Testdatenbank unter {TEST_URL}: {fehler}")
    yield konten
    konten.schliesse_pool()


@pytest.fixture
def mit_serverschluessel(datenbank):
    """Setzt RECHNUNGSBLATT_SCHLUESSEL für die Dauer eines Tests.

    Ohne ihn legt die Anwendung Geheimnisse im Klartext ab — bewusst, damit
    Entwicklung und CI ohne Schlüssel laufen; der Produktivstack erzwingt
    ihn. Wer die Verschlüsselung selbst prüfen will, braucht ihn also.
    """
    vorher = datenbank.SERVERSCHLUESSEL
    datenbank.SERVERSCHLUESSEL = "test-serverschluessel-nur-hier"
    yield datenbank
    datenbank.SERVERSCHLUESSEL = vorher


@pytest.fixture
def leere_konten(datenbank):
    """Setzt Konten, Sitzungen und Verbrauch vor jedem Test zurück.

    Die Tarife bleiben stehen — sie sind Stammdaten, kein Testzustand.
    """
    with datenbank.verbindung() as verbindung:
        verbindung.execute(
            "TRUNCATE verbrauch, sitzungen, nutzer RESTART IDENTITY CASCADE"
        )
    return datenbank
