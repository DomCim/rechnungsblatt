"""Meldungen aus dem Arbeitsbereich — als GitHub-Issue.

**Warum überhaupt.** Ein Fehler, den ein Kunde per Mail schildert, landet
in einem Postfach und wird dort zur Handarbeit: abtippen, einordnen,
nachfragen, was er eigentlich angeklickt hat. Ein Formular im
Arbeitsbereich nimmt dieselbe Schilderung entgegen und hängt an, was der
Kunde nicht wissen kann — welche Seite, welcher Browser, welcher Stand.
Als Issue steht sie dort, wo ohnehin entschieden wird, was als Nächstes
gebaut wird.

**Der Text wird veröffentlicht.** Wer das Ziel-Repository lesen darf,
liest die Meldung. Das Formular sagt das ausdrücklich, und die
Datenschutzerklärung nennt GitHub als Empfänger. Die **Adresse** des
Kontos steht bewusst NICHT im Issue, nur seine Nummer: Wer dahintersteckt,
schlägt der Betreiber im Adminbereich nach. Damit bleibt aus dem Issue
heraus niemand identifizierbar, dessen Meldung einmal falsch adressiert
ist.

**Ohne Zugang geht nichts verloren.** Repo und Token stehen in den
Einstellungen (Adminbereich → Meldungen), nicht in Umgebungsvariablen — so
lässt sich das Ziel wechseln, ohne den Stack neu zu deployen. Fehlt eines
von beiden oder antwortet GitHub nicht, wird die Meldung trotzdem
gespeichert und der Grund am Datensatz vermerkt. Der Betreiber sieht sie
im Adminbereich und kann sie von dort nachreichen.

**Die Bilder liegen unverschlüsselt und öffentlich.** Das ist der Preis
dafür, dass GitHub sie einbetten kann: Der Bildproxy holt sie über das
offene Netz, auch für ein privates Repository. Sie liegen deshalb
getrennt von den Mandantendaten unter ``DATEN/meldungen/`` und tragen
Zufallsnamen — erraten lässt sich keiner, verlinkt ist jeder. Wer ein
Konto löscht, löscht sie mit (siehe ``wege_verwaltung``); sonst überlebte
ein Bildschirmfoto das Konto, dem es gehörte.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

import httpx

from . import konten
from .basis import datenverzeichnis

protokoll = logging.getLogger("rechnungsblatt.meldungen")


class MeldungFehler(Exception):
    """Vorgang fehlgeschlagen — die Meldung ist für den Betreiber bestimmt."""


# Die Arten, in denen gemeldet werden kann. Der Schlüssel wird zum
# GitHub-Label, der Text steht im Formular.
#
# "beleg" ist die Art, die es beim Vorbild (FWG-Portal) nicht gibt und die
# hier am schwersten wiegt: Wenn die §14-Prüfung etwas durchlässt oder zu
# Unrecht ablehnt, oder ein Prüfportal das XML zurückweist, ist das kein
# Schönheitsfehler, sondern der Kern des Produkts. Solche Meldungen sollen
# sich nicht in "Sonstiges" verstecken.
ARTEN: dict[str, str] = {
    "fehler": "Fehler / Bug",
    "gestaltung": "Design-Problem",
    "idee": "Idee / Verbesserung",
    "beleg": "Rechnung stimmt nicht",
    "sonstiges": "Sonstiges",
}

# Was an einem Bild angenommen wird. Bewusst über die Kennung am
# Dateianfang und nicht über die Endung: Die Endung sagt, wie die Datei
# heißt, die Kennung, was sie ist.
_BILDARTEN: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"RIFF", ".webp"),          # genauer geprüft wird unten
)

MAX_BILD_BYTES = 5 * 1024 * 1024
MAX_BILDER = 4

# Drossel: So viele Meldungen darf ein Konto je Stunde abschicken. Nicht
# gegen Angriffe gedacht — gegen den doppelt geklickten Knopf und gegen
# den Abend, an dem jemand seinen Frust in zwanzig Issues schreibt.
MELDUNGEN_JE_STUNDE = 10

def bildverzeichnis() -> Path:
    """Wo die Bildschirmfotos liegen.

    Als Funktion und nicht als Konstante: Die Tests haengen das
    Datenverzeichnis zur Laufzeit um (siehe ``basis.datenverzeichnis``).
    Eine beim Import gebundene Konstante schriebe an ihnen vorbei -- in das
    echte Verzeichnis.
    """
    return datenverzeichnis() / "meldungen"


def _zugang() -> tuple[str, str]:
    werte = konten.einstellungen(mit_geheimnissen=True)
    return werte.get("github_repo", "").strip(), werte.get("github_token", "").strip()


def ist_eingerichtet() -> bool:
    repo, token = _zugang()
    return bool(repo and token)


# ---------------------------------------------------------------- Bilder

def _endung(inhalt: bytes) -> str | None:
    """Welche Bildart? ``None``, wenn es keine erkannte ist."""
    for kennung, endung in _BILDARTEN:
        if not inhalt.startswith(kennung):
            continue
        if endung == ".webp" and inhalt[8:12] != b"WEBP":
            # RIFF allein ist auch eine WAV-Datei.
            return None
        return endung
    return None


def speichere_bild(inhalt: bytes) -> str:
    """Legt ein Bild ab und liefert seinen Dateinamen.

    Der Name ist reiner Zufall: Er wird verlinkt, nicht erraten, und darf
    nichts über Konto oder Meldung verraten.
    """
    if len(inhalt) > MAX_BILD_BYTES:
        raise MeldungFehler("Ein Bild ist größer als 5 MB.")
    endung = _endung(inhalt)
    if endung is None:
        raise MeldungFehler("Nur PNG, JPEG und WebP werden angenommen.")
    ziel = bildverzeichnis()
    ziel.mkdir(parents=True, exist_ok=True)
    name = secrets.token_urlsafe(24).replace("-", "_") + endung
    (ziel / name).write_bytes(inhalt)
    return name


def bild_pfad(name: str) -> Path | None:
    """Pfad zu einem abgelegten Bild — oder ``None``.

    Der Name kommt aus der Adresszeile. Geprüft wird deshalb nicht, ob er
    „irgendwie passt", sondern ob er genau die Form hat, die
    ``speichere_bild`` vergibt: ein Teil, keine Trennzeichen, bekannte
    Endung. Damit ist ein ``../`` gar nicht erst denkbar.
    """
    stamm, punkt, endung = name.rpartition(".")
    if not punkt or "." + endung not in {e for _, e in _BILDARTEN}:
        return None
    if not stamm or not all(z.isalnum() or z == "_" for z in stamm):
        return None
    pfad = bildverzeichnis() / name
    return pfad if pfad.is_file() else None


def loesche_bilder(namen: list[str]) -> None:
    """Entfernt abgelegte Bilder. Fehlende sind kein Fehler."""
    for name in namen:
        pfad = bild_pfad(name)
        if pfad is None:
            continue
        try:
            pfad.unlink()
        except OSError:
            protokoll.exception("Bild %s nicht gelöscht", name)


# ---------------------------------------------------------------- GitHub

def lege_issue_an(titel: str, koerper: str, label: str) -> tuple[int, str]:
    """Legt ein Issue an und liefert (Nummer, Adresse)."""
    repo, token = _zugang()
    if not repo or not token:
        raise MeldungFehler(
            "Kein GitHub-Zugang eingetragen (Adminbereich → Meldungen)."
        )
    try:
        antwort = httpx.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Rechnungsblatt",
            },
            json={"title": titel[:250], "body": koerper, "labels": [label]},
            timeout=15.0,
        )
    except httpx.HTTPError as fehler:
        raise MeldungFehler(f"GitHub nicht erreichbar: {fehler}") from fehler
    if antwort.status_code == 401:
        raise MeldungFehler("GitHub weist den Token ab (401). Ist er abgelaufen?")
    if antwort.status_code == 403:
        raise MeldungFehler(
            "GitHub verweigert den Zugriff (403). Fehlt dem Token das Recht "
            "„Issues: read and write“ auf diesem Repository?"
        )
    if antwort.status_code == 404:
        raise MeldungFehler(
            f"GitHub kennt „{repo}“ nicht (404) — oder der Token darf es nicht "
            "sehen. Bei einem privaten Repository muss er ausdrücklich dafür "
            "ausgestellt sein."
        )
    if antwort.status_code == 410:
        raise MeldungFehler(
            f"Für „{repo}“ sind Issues abgeschaltet (410). "
            "In den Repository-Einstellungen einschalten."
        )
    if antwort.status_code >= 400:
        raise MeldungFehler(
            f"GitHub antwortet mit {antwort.status_code}: {antwort.text[:200]}"
        )
    daten = antwort.json()
    return int(daten.get("number", 0)), str(daten.get("html_url", ""))


def baue_koerper(
    art: str,
    text: str,
    nutzer_id: int,
    seite: str,
    browser: str,
    stand: str,
    bild_adressen: list[str],
) -> str:
    """Der Text des Issues: erst die Schilderung, dann die Umstände.

    Die Schilderung steht oben, weil sie gelesen wird; die Umstände stehen
    unten, weil sie nachgeschlagen werden.
    """
    zeilen = [text.strip(), "", "---", ""]
    for bezeichnung, wert in (
        ("Art", ARTEN.get(art, art)),
        ("Konto", f"#{nutzer_id}"),
        ("Seite", seite or "—"),
        ("Stand", stand or "unbekannt"),
        ("Browser", browser or "—"),
    ):
        zeilen.append(f"- **{bezeichnung}:** {wert}")
    if bild_adressen:
        zeilen.append("")
        for nummer, adresse in enumerate(bild_adressen, start=1):
            zeilen.append(f"![Bild {nummer}]({adresse})")
    zeilen += [
        "",
        "<sub>Aus dem Arbeitsbereich von Rechnungsblatt gemeldet. "
        "Die E-Mail-Adresse des Kontos steht absichtlich nicht hier — "
        "sie steht im Adminbereich unter der Kontonummer.</sub>",
    ]
    return "\n".join(zeilen)
