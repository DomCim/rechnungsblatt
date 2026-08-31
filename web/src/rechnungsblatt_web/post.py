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
import socket
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import dkim, konten

protokoll = logging.getLogger("rechnungsblatt.post")


class PostFehler(Exception):
    """Versand fehlgeschlagen — die Meldung ist für den Betreiber bestimmt."""


def _zugang() -> dict[str, str]:
    return konten.einstellungen(mit_geheimnissen=True)


def ist_eingerichtet() -> bool:
    zugang = _zugang()
    return bool(zugang.get("smtp_host") and zugang.get("smtp_absender"))


def _absender_domain(absender: str) -> str:
    return dkim.domain_von(absender)


def _unterschreibe(nachricht, absender: str, zugang: dict) -> bytes:
    """Die versandfertige Nachricht — unterschrieben, wenn DKIM passt.

    Drei Gruende, warum hier nichts geschieht — alle unkritisch, alle im
    Log nachvollziehbar:

    * Es ist kein DKIM hinterlegt. Dann verschickt die App wie bisher.
    * Die Angaben sind unvollstaendig. Eine halbe Unterschrift schlaegt
      beim Empfaenger fehl und sieht dann nach einer Faelschung aus —
      schlimmer als gar keine.
    * Die signierende Domain passt nicht zum Absender. Die Unterschrift
      waere technisch gueltig, DMARC verlangt aber, dass beide
      zusammengehoeren; sie kostete nur Rechenzeit.
    """
    domain = (zugang.get("dkim_domain") or "").strip()
    selektor = (zugang.get("dkim_selektor") or "").strip()
    pem = (zugang.get("dkim_schluessel") or "").strip()
    if not (domain and selektor and pem):
        if domain or selektor or pem:
            protokoll.warning(
                "DKIM ist nur halb eingerichtet (Domain, Selektor und "
                "Schluessel gehoeren zusammen) — es wird nicht unterschrieben."
            )
        return nachricht.as_bytes()
    if not dkim.passt(domain, absender):
        protokoll.warning(
            "DKIM ist fuer %s hinterlegt, der Absender %s gehoert aber nicht "
            "dazu — diese Nachricht geht unsigniert raus.", domain, absender,
        )
        return nachricht.as_bytes()
    try:
        return dkim.unterschreibe(nachricht, domain, selektor, pem)
    except dkim.DkimFehler as fehler:
        # Nicht scheitern: Eine unsignierte Nachricht kommt vielleicht an,
        # eine nicht verschickte sicher nicht.
        protokoll.error("DKIM-Unterschrift nicht moeglich: %s", fehler)
        return nachricht.as_bytes()


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
    # Date und Message-ID gehoeren dazu, bevor unterschrieben wird: Sie
    # werden mitsigniert, und ein Mailserver, der sie nachtraegt, bricht
    # die Unterschrift. Ausserdem gilt eine Nachricht ohne beides bei
    # manchen Filtern schon fuer sich als verdaechtig.
    nachricht["Date"] = formatdate(localtime=True)
    nachricht["Message-ID"] = make_msgid(domain=_absender_domain(absender) or None)
    nachricht.set_content(text)

    # Fertige Bytes, damit die Signaturzeile unangetastet bleibt (siehe
    # dkim.unterschreibe). Ohne Unterschrift ist es einfach die Nachricht.
    roh = _unterschreibe(nachricht, absender, zugang)

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
                # sendmail statt send_message: Das baut die Nachricht neu
                # auf und wuerde die Signaturzeile wieder umkodieren.
                server.sendmail(absender, [an], roh)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=umgebung)
                if benutzer:
                    server.login(benutzer, passwort)
                server.sendmail(absender, [an], roh)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as fehler:
        protokoll.exception("Versand an %s fehlgeschlagen", an)
        raise PostFehler(
            f"E-Mail konnte nicht verschickt werden: {fehler}"
            + _hilfe_zum_fehler(fehler, host, port, implizit)
        ) from fehler


def _hilfe_zum_fehler(fehler: Exception, host: str, port: int,
                      implizit: bool) -> str:
    """Ergänzt die Meldung des Servers um die wahrscheinliche Ursache.

    „The read operation timed out" allein sagt niemandem, was zu tun ist.
    Dieselbe Meldung entsteht bei einem falschen Port wie bei einem toten
    Server — und der häufigste Fall ist, dass Port 465 unterwegs gesperrt
    ist: Viele Rechenzentren lassen ihn nicht heraus, 587 dagegen schon.
    """
    text = str(fehler).lower()
    if isinstance(fehler, smtplib.SMTPRecipientsRefused):
        # Der Zugang stimmt -- der Server hat die Nachricht angenommen und
        # erst den Empfaenger abgelehnt. Ohne diesen Hinweis sucht man den
        # Fehler weiter bei Server, Port und Passwort.
        return (" — der Zugang stimmt, aber diese Empfängeradresse gibt es "
                "nicht. Die Testnachricht geht an Ihre Kontoadresse, wenn "
                "kein anderes Ziel eingetragen ist.")
    if "no such mailbox" in text or "user unknown" in text:
        return (" — den Zugang hat der Server angenommen; nur die "
                "Empfängeradresse gibt es nicht.")
    if isinstance(fehler, smtplib.SMTPSenderRefused):
        return (" — der Server nimmt diese Absenderadresse nicht an. Sie "
                "muss zu dem Postfach gehören, mit dem sich die App anmeldet.")
    if isinstance(fehler, smtplib.SMTPAuthenticationError):
        return (" — Benutzername oder Passwort stimmen nicht. Bei manchen "
                "Anbietern ist das nicht das Postfachpasswort, sondern ein "
                "eigenes für den Programmzugriff.")
    if "timed out" in text or isinstance(fehler, (TimeoutError, socket.timeout)):
        if implizit or port == 465:
            return (f" — Port {port} antwortet nicht. Das ist meist keine "
                    "falsche Einstellung, sondern eine Sperre auf dem Weg: "
                    "Viele Rechenzentren lassen 465 nicht heraus. Port 587 "
                    "mit ausgeschaltetem Schalter probieren.")
        return (f" — {host}:{port} antwortet nicht. Stimmen Server und Port?")
    if "connection refused" in text:
        return f" — {host} nimmt auf Port {port} keine Verbindung an."
    if "name or service not known" in text or "nodename nor servname" in text:
        return f" — den Server „{host}“ gibt es nicht (Tippfehler?)."
    if "certificate" in text:
        return (" — das Zertifikat des Servers wurde abgelehnt. Passt der "
                "Servername zu dem, was der Anbieter nennt?")
    return ""
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
