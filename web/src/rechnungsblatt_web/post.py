"""E-Mail-Versand — Bestätigungscode und Rücksetz-Link.

Bewusst schmal: Rechnungsblatt verschickt genau zwei Arten von Nachrichten,
beide an die Adresse des Kontoinhabers, beide ohne Anhang. Ein
Newsletter-Werkzeug wäre hier fehl am Platz.

Der Zugang steht in der Datenbank (Adminbereich → Betrieb), nicht in
Umgebungsvariablen: So lässt sich der Postausgang ändern, ohne den Stack
neu zu deployen.

**Ist kein SMTP eingerichtet, wird die Nachricht ins Log geschrieben statt
verschickt.** Das hält die lokale Entwicklung am Laufen und macht in einem
frisch aufgesetzten Stack sichtbar, was fehlt — statt Registrierungen
stillschweigend scheitern zu lassen.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import konten

protokoll = logging.getLogger("rechnungsblatt.post")


class PostFehler(Exception):
    """Versand fehlgeschlagen — die Meldung ist für den Betreiber bestimmt."""


def _zugang() -> dict[str, str]:
    return konten.einstellungen(mit_geheimnissen=True)


def ist_eingerichtet() -> bool:
    zugang = _zugang()
    return bool(zugang.get("smtp_host") and zugang.get("smtp_absender"))


def sende(an: str, betreff: str, text: str) -> bool:
    """Verschickt eine Nachricht. Liefert False, wenn nur geloggt wurde.

    Reiner Text, kein HTML: Ein Bestätigungscode braucht kein Layout, und
    Textnachrichten landen seltener im Spam.
    """
    zugang = _zugang()
    absender = zugang.get("smtp_absender", "").strip()
    host = zugang.get("smtp_host", "").strip()

    if not host or not absender:
        # Kein Postausgang eingerichtet. Nicht scheitern — sonst käme
        # niemand mehr durch die Registrierung, und lokal gäbe es gar
        # keinen Weg, den Code zu erfahren.
        protokoll.warning(
            "Kein SMTP eingerichtet. Nachricht an %s NICHT verschickt:\n"
            "Betreff: %s\n%s", an, betreff, text,
        )
        return False

    nachricht = EmailMessage()
    nachricht["From"] = absender
    nachricht["To"] = an
    nachricht["Subject"] = betreff
    nachricht.set_content(text)

    port = int(zugang.get("smtp_port") or 587)
    benutzer = zugang.get("smtp_benutzer", "").strip()
    passwort = zugang.get("smtp_passwort", "")
    # "1" = implizites TLS auf Port 465, sonst STARTTLS auf 587.
    implizit = zugang.get("smtp_tls", "") == "1" or port == 465

    try:
        umgebung = ssl.create_default_context()
        if implizit:
            with smtplib.SMTP_SSL(host, port, context=umgebung, timeout=20) as server:
                if benutzer:
                    server.login(benutzer, passwort)
                server.send_message(nachricht)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=umgebung)
                if benutzer:
                    server.login(benutzer, passwort)
                server.send_message(nachricht)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as fehler:
        protokoll.exception("Versand an %s fehlgeschlagen", an)
        raise PostFehler(f"E-Mail konnte nicht verschickt werden: {fehler}") from fehler
    return True


# ---------------------------------------------------------------- Vorlagen

def sende_bestaetigungscode(an: str, code: str) -> bool:
    return sende(
        an,
        "Ihr Bestätigungscode für Rechnungsblatt",
        f"""Guten Tag,

zum Bestätigen Ihrer E-Mail-Adresse geben Sie bitte diesen Code ein:

    {code}

Der Code gilt 30 Minuten. Haben Sie sich nicht bei Rechnungsblatt
registriert, können Sie diese Nachricht ignorieren — ohne den Code
passiert nichts.

Rechnungsblatt
""",
    )


def sende_ruecksetzlink(an: str, verweis: str) -> bool:
    return sende(
        an,
        "Passwort zurücksetzen — Rechnungsblatt",
        f"""Guten Tag,

Sie haben angefordert, Ihr Passwort zurückzusetzen. Über diesen Link
kommen Sie zur Bestätigung und können danach ein neues Passwort setzen:

{verweis}

Der Link gilt 60 Minuten und lässt sich nur einmal verwenden.

Wichtig: Ihre Rechnungsdaten sind mit Ihrem Passwort verschlüsselt. Ein
neues Passwort allein öffnet sie NICHT — dafür brauchen Sie den
Wiederherstellungscode, den Sie bei der Einrichtung notiert haben. Ohne
ihn bekommen Sie zwar wieder Zugang zum Konto, die vorhandenen Belege
bleiben aber unlesbar.

Haben Sie das nicht angefordert, ignorieren Sie diese Nachricht — Ihr
Passwort bleibt dann unverändert.

Rechnungsblatt
""",
    )
