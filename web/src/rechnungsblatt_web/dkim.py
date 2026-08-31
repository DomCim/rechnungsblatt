"""DKIM — ausgehende Nachrichten unterschreiben.

**Ohne Unterschrift landet Post von einer eigenen Domain regelmäßig im
Spam.** Der empfangende Server sieht eine Nachricht, die vorgibt, von
rechnungsblatt.de zu kommen, und hat nichts, womit er das prüfen könnte.
Ein Bestätigungscode, der im Spam liegt, ist genauso gut wie keiner — die
Registrierung bricht dort ab.

Signiert wird hier selbst, weil ein gewöhnlicher SMTP-Zugang das nicht tut.
Anbieter für Transaktionspost (Postmark, Mailgun) nehmen einem das ab; die
kosten aber ab dem ersten Tag und binden an einen Dienst, während hier ein
Postfach genügt, das ohnehin da ist.

**Zusammengehören müssen zwei Domains:** die im Absender und die, für die
signiert wird. DMARC nennt das „Alignment". Eine Nachricht von
``no-reply@rechnungsblatt.de``, unterschrieben mit dem Schlüssel von
``example.org``, besteht die DKIM-Prüfung zwar — sie gilt trotzdem als
nicht ausgewiesen und hilft nicht.

Umgesetzt mit ``cryptography``, das ohnehin für die Mandantendaten
gebraucht wird. Eine eigene DKIM-Bibliothek wäre eine weitere
Abhängigkeit für gut hundert Zeilen.

**DKIM allein genügt nicht.** SPF und DMARC sind DNS-Einträge und stehen
nicht in dieser Anwendung; ``dns_eintrag()`` liefert den Text, der für DKIM
veröffentlicht werden muss.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

protokoll = logging.getLogger("rechnungsblatt.dkim")


class DkimFehler(Exception):
    """Schlüssel unbrauchbar — die Meldung ist für den Betreiber bestimmt."""


# Diese Kopfzeilen werden unterschrieben. Weniger wäre angreifbar (wer den
# Betreff ändern kann, ändert die Nachricht), mehr wäre zerbrechlich:
# Zwischenstationen ergänzen Kopfzeilen, und eine Unterschrift über eine
# Zeile, die unterwegs entsteht, schlägt beim Empfänger fehl.
_ZU_SIGNIEREN = ("from", "to", "subject", "date", "message-id")


def domain_von(adresse: str) -> str:
    """Die Domain einer Adresse, klein geschrieben. Leer, wenn keine drin ist.

    **Ohne ``@`` ist es keine Adresse.** ``rpartition`` allein lieferte
    sonst den ganzen Text als „Domain": Aus dem Absender
    ``Rechnungsblatt.de`` — ohne Postfach davor — wurde die Domain
    ``rechnungsblatt.de``, die Alignment-Prüfung ging durch, und die App
    hätte gegenüber dem Mailserver einen Absender ohne ``@`` behauptet.
    """
    treffer = re.search(r"<([^>]+)>", adresse or "")
    reine = (treffer.group(1) if treffer else (adresse or "")).strip()
    postfach, trenner, domain = reine.rpartition("@")
    if not trenner or not postfach.strip():
        return ""
    return domain.strip().lower()


def passt(signier_domain: str, absender: str) -> bool:
    """Gehören signierende Domain und Absender zusammen? (DMARC-Alignment)

    Eine Unterdomain zählt als zugehörig, umgekehrt nicht: Wer
    ``rechnungsblatt.de`` signiert, deckt ``post.rechnungsblatt.de`` mit ab,
    aber nicht andersherum.
    """
    a = domain_von(absender)
    s = (signier_domain or "").strip().lower()
    if not a or not s:
        return False
    return a == s or a.endswith("." + s)


def _schluessel_laden(pem: str) -> rsa.RSAPrivateKey:
    try:
        schluessel = serialization.load_pem_private_key(
            pem.strip().encode("utf-8"), password=None
        )
    except (ValueError, TypeError) as fehler:
        raise DkimFehler(
            "Der DKIM-Schlüssel ist nicht lesbar. Erwartet wird ein "
            "privater RSA-Schlüssel im PEM-Format (beginnt mit -----BEGIN)."
        ) from fehler
    if not isinstance(schluessel, rsa.RSAPrivateKey):
        raise DkimFehler("Der DKIM-Schlüssel ist kein RSA-Schlüssel.")
    return schluessel


def _falte(wert: str) -> str:
    """Whitespace einer Kopfzeile vereinheitlichen (relaxed canonicalization).

    Der Empfänger rechnet über denselben Text nach. Zwischenstationen dürfen
    Zeilen umbrechen und Leerzeichen ändern — „relaxed" macht die
    Unterschrift dagegen unempfindlich. Bei „simple" hätte ein einziges
    zusätzliches Leerzeichen sie zerstört.
    """
    return re.sub(r"[ \t]+", " ", wert.replace("\r\n", " ").replace("\n", " ")).strip()


def _koerper_hash(koerper: bytes) -> str:
    """SHA-256 über den Nachrichtentext, relaxed kanonisiert."""
    text = koerper.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    zeilen = [re.sub(rb"[ \t]+", b" ", z).rstrip() for z in text.split(b"\n")]
    # Leerzeilen am Ende fallen weg, dafür endet der Text immer mit CRLF.
    while zeilen and not zeilen[-1]:
        zeilen.pop()
    fertig = b"\r\n".join(zeilen) + b"\r\n" if zeilen else b"\r\n"
    return base64.b64encode(hashlib.sha256(fertig).digest()).decode("ascii")


def unterschreibe(nachricht, domain: str, selektor: str, pem: str) -> bytes:
    """Die fertige Nachricht als Bytes, mit vorangestellter Unterschrift.

    **Die Signaturzeile wird der serialisierten Nachricht vorangestellt und
    nicht über ``nachricht[…]`` gesetzt.** Python hält die lange
    base64-Zeile sonst für umbruchbedürftigen Text und kodiert sie als
    ``=?utf-8?q?…`` — damit ist die Unterschrift unlesbar und jede Prüfung
    schlägt fehl. Keine der Policy-Einstellungen verhindert das
    zuverlässig; vorangestellt fasst Python sie gar nicht erst an.

    Wirft DkimFehler, wenn der Schlüssel unbrauchbar ist — der Aufrufer
    entscheidet, ob er dann unsigniert verschickt oder abbricht.
    """
    schluessel = _schluessel_laden(pem)
    fertig = nachricht.as_bytes()
    kopfzeilen, koerper = _zerlege(fertig)

    # **Über die serialisierten Kopfzeilen signieren, nicht über
    # ``nachricht.get(…)``.** Bei „Ihr Bestätigungscode" liefert get() den
    # Klartext, in den Bytes steht aber „=?utf-8?q?…" — signiert wäre dann
    # etwas anderes, als beim Empfänger ankommt, und jede Prüfung schlüge
    # fehl. Genau dieser Betreff steht auf jeder Registrierungsmail.
    vorhanden = [k for k in _ZU_SIGNIEREN if k in kopfzeilen]
    kopf_text = "".join(f"{k}:{_falte(kopfzeilen[k])}\r\n" for k in vorhanden)

    felder = (
        "v=1; a=rsa-sha256; c=relaxed/relaxed; "
        f"d={domain}; s={selektor}; t={int(time.time())}; "
        f"h={':'.join(vorhanden)}; bh={_koerper_hash(koerper)}; b="
    )
    # Die Signaturzeile unterschreibt sich selbst mit — ohne abschließendes
    # CRLF und mit noch leerem b=, so schreibt es die Norm vor.
    zu_signieren = (kopf_text + f"dkim-signature:{_falte(felder)}").encode("utf-8")

    unterschrift = base64.b64encode(
        schluessel.sign(zu_signieren, padding.PKCS1v15(), hashes.SHA256())
    ).decode("ascii")

    # Der eigene Umbruch mit CRLF + Leerzeichen ist das, was die Norm
    # vorsieht; „relaxed" macht ihn für die Prüfung unschädlich.
    zeile = "DKIM-Signature: " + _umbrich(felder + unterschrift)
    return zeile.encode("ascii") + b"\r\n" + fertig


def _zerlege(fertig: bytes) -> tuple[dict[str, str], bytes]:
    """Trennt die serialisierte Nachricht in Kopfzeilen und Text.

    Von Hand statt über ``email``: Gebraucht wird der Wortlaut, wie er auf
    der Leitung steht — mit ``=?utf-8?…`` und aufgelösten Zeilenumbrüchen.
    Der Parser gäbe stattdessen den entschlüsselten Klartext zurück.
    """
    text = fertig.replace(b"\r\n", b"\n")
    kopf_roh, _, koerper = text.partition(b"\n\n")
    kopfzeilen: dict[str, str] = {}
    letzter = ""
    for zeile in kopf_roh.split(b"\n"):
        entziffert = zeile.decode("utf-8", "replace")
        if entziffert[:1] in (" ", "\t") and letzter:
            # Fortsetzungszeile: gehört zur vorigen Kopfzeile.
            kopfzeilen[letzter] += " " + entziffert.strip()
            continue
        name, trenner, wert = entziffert.partition(":")
        if not trenner:
            continue
        letzter = name.strip().lower()
        kopfzeilen[letzter] = wert.strip()
    return kopfzeilen, koerper


_FALTUNG = "\r\n "


def _umbrich(zeile: str, breite: int = 72) -> str:
    """Bricht die Signaturzeile um, wie es die Norm erlaubt."""
    stuecke, rest = [], zeile
    while len(rest) > breite:
        schnitt = rest.rfind(" ", 0, breite)
        if schnitt <= 0:
            schnitt = breite
        stuecke.append(rest[:schnitt].rstrip())
        rest = rest[schnitt:].lstrip()
    stuecke.append(rest)
    return _FALTUNG.join(stuecke)


def dns_eintrag(pem: str, selektor: str, domain: str) -> dict[str, str]:
    """Der TXT-Eintrag, der zum privaten Schlüssel veröffentlicht werden muss.

    Ohne ihn nützt die Unterschrift nichts: Der Empfänger holt den
    öffentlichen Schlüssel unter ``<selektor>._domainkey.<domain>``.
    """
    schluessel = _schluessel_laden(pem)
    roh = schluessel.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {
        "name": f"{selektor}._domainkey.{domain}",
        "typ": "TXT",
        "wert": "v=DKIM1; k=rsa; p=" + base64.b64encode(roh).decode("ascii"),
    }


def erzeuge_schluesselpaar(bits: int = 2048) -> str:
    """Ein frischer privater Schlüssel als PEM.

    2048 Bit: 1024 gilt als zu schwach, und 4096 sprengt bei manchen
    DNS-Anbietern die Länge eines TXT-Eintrags.
    """
    schluessel = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    return schluessel.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
