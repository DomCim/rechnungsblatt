"""Kleine Helfer der Web-Tests.

Bewusst ein eigenes Modul und nicht `conftest`: Beim gemeinsamen Lauf von
`kern/tests` und `web/tests` liegen beide Testverzeichnisse im Suchpfad, und
`import conftest` träfe dann auf die falsche Datei.
"""

from __future__ import annotations


def melde_an(klient, email: str, passwort: str) -> None:
    antwort = klient.post("/api/anmelden", json={"email": email, "passwort": passwort})
    assert antwort.status_code == 200, antwort.text


def lege_kunden_an(konten, email: str, passwort: str, tarif: str = "unbegrenzt"):
    """Freigeschaltetes Konto mit bestätigter Adresse.

    Die E-Mail-Bestätigung wird hier übersprungen: Sie hat einen eigenen
    Test, und ohne sie käme kein anderer Test mehr an eine Sitzung.
    """
    person, _code = konten.registriere(email, passwort)
    konten.bestaetige_email(person.id)
    konten.setze_status(person.id, konten.STATUS_FREI)
    return konten.setze_tarif(person.id, tarif)
