"""Die Besucherzählung — über die eigene Adresse statt über Plausible.

**Warum das nötig ist.** Plausible läuft im internen Netz: keine
Portfreigabe, kein Zertifikat, keine eigene Adresse. Der Browser eines
Besuchers käme dort nicht hin. Ein Bericht vom 01.09.2026 zeigte genau
das — ``http://vh-statistic-plausible-1:8000/js/script.js`` wurde als
Mixed Content blockiert, und der Containername ist von außen ohnehin
nicht auflösbar. Gezählt wurde also nichts.

Rechnungsblatt liefert das Skript deshalb selbst aus und reicht die
Ereignisse nach innen weiter:

    Besucher → rechnungsblatt.de/statistik/zaehler.js → Plausible
    Besucher → rechnungsblatt.de/statistik/ereignis   → Plausible

**Zwei Fliegen mit einer Klappe.** Ein Skript, dessen Adresse
``plausible`` enthält, schlucken die gängigen Werbeblockerlisten — nicht
aus Bosheit, sie kennen die Adresse, nicht das Verhalten. Über die eigene
Adresse ist es eine Datei wie jede andere. Nebenbei braucht die
Sicherheitsrichtlinie keine Ausnahme für einen fremden Host.

Das Muster stammt aus vh-website, wo es sich im Betrieb bewährt hat.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Request, Response

from . import konten
from .basis import PLAUSIBLE_URL, protokoll

wege = APIRouter()

# Der Zeilenumbruch als Konstante — siehe _mit_wache.
NEUE_ZEILE = chr(10)

# Größer kann ein Zählereignis nicht sein — alles darüber ist Unfug.
MAX_BYTES = 8 * 1024

# So lange wird dasselbe Skript weitergereicht, bevor neu geholt wird.
FRISCHE = 3600.0

# Kurze Frist, wenn es klemmt: So renkt es sich von selbst wieder ein,
# statt eine Stunde lang ein leeres Skript auszuliefern.
FRISCHE_IM_FEHLER = 60

_gemerkt: tuple[float, str] | None = None


def zaehladresse() -> str:
    """Die interne Adresse von Plausible — aus Verwaltung oder Umgebung."""
    try:
        werte = konten.einstellungen()
    except Exception:          # Datenbank noch nicht erreichbar
        werte = {}
    return (werte.get("plausible_url") or PLAUSIBLE_URL).rstrip("/")


def _mit_wache(skript: str) -> str:
    """Unter Fernsteuerung wird nicht gezählt.

    Sonst verfälschten die eigenen PageSpeed-Läufe und jeder
    Testdurchlauf die Statistik. Die Entscheidung fällt im Browser,
    weil nur der weiß, ob er ferngesteuert ist.
    """
    # Als Liste und nicht als ein String mit Escape-Sequenzen: Ein
    # Backslash-n wird beim Erzeugen solcher Dateien leicht zum echten
    # Umbruch und zerreißt dann das Literal.
    return NEUE_ZEILE.join([
        "/* Unter Fernsteuerung wird nicht gezählt. */",
        "if (navigator.webdriver || /HeadlessChrome/.test(navigator.userAgent)) {",
        "  window.plausible = window.plausible || function () {};",
        "} else {",
        skript,
        "}",
        "",
    ])


def _auslieferung(text: str, sekunden: int = 3600) -> Response:
    return Response(
        text,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": f"public, max-age={sekunden}"},
    )


@wege.get("/statistik/zaehler.js")
def zaehlskript() -> Response:
    """Das Zählskript, geholt aus dem internen Plausible.

    Ohne eingerichtete Zählung ein **leeres** Skript statt eines 404: Das
    Skript-Tag steht womöglich schon im Seitenkopf, und ein Fehler in der
    Konsole des Kunden sähe nach einem kaputten Dienst aus.
    """
    global _gemerkt

    if _gemerkt and time.monotonic() - _gemerkt[0] < FRISCHE:
        return _auslieferung(_gemerkt[1])

    adresse = zaehladresse()
    if not adresse:
        return _auslieferung("/* keine Zählung eingerichtet */" + NEUE_ZEILE, 300)

    try:
        antwort = httpx.get(f"{adresse}/js/script.js", timeout=5.0)
        antwort.raise_for_status()
    except httpx.HTTPError as fehler:
        protokoll.warning("Zählskript nicht erreichbar: %s", fehler)
        # Eine fehlende Besucherzählung ist kein Grund, die Seite zu stören.
        return _auslieferung("/* Zählung gerade nicht erreichbar */" + NEUE_ZEILE,
                             FRISCHE_IM_FEHLER)

    text = _mit_wache(antwort.text)
    _gemerkt = (time.monotonic(), text)
    return _auslieferung(text)


def _herkunft(anfrage: Request) -> str | None:
    """Die Adresse des Besuchers, wie sie durch den Proxy hereinkommt.

    In ``X-Forwarded-For`` steht eine Kette; der **erste** Eintrag ist der
    Besucher, dahinter die Zwischenstationen. Wer den letzten nimmt, misst
    seinen eigenen Proxy.
    """
    kette = anfrage.headers.get("x-forwarded-for")
    if kette:
        erster = kette.split(",")[0].strip()
        if erster:
            return erster
    return anfrage.headers.get("x-real-ip")


@wege.post("/statistik/ereignis")
async def ereignis(anfrage: Request) -> Response:
    """Nimmt ein Zählereignis an und reicht es nach innen weiter.

    **Die Herkunft muss mitgeschickt werden.** Sonst sieht Plausible als
    Absender immer denselben: diesen Server. Aus tausend Besuchern würde
    ein einziger, der sehr viel liest, und das Land wäre bei allen
    dasselbe.

    Aus Adresse und Browserkennung bildet Plausible mit einem täglich
    wechselnden Salz seinen Fingerabdruck. Gespeichert wird keins von
    beidem — deshalb braucht es kein Einwilligungsbanner.
    """
    adresse = zaehladresse()
    # Ohne eingerichtete Zählung stillschweigend nichts tun: Der Zähler im
    # Browser wartet auf keine Antwort und soll keine Fehler melden.
    if not adresse:
        return Response(status_code=202)

    roh = await anfrage.body()
    if len(roh) > MAX_BYTES:
        return Response(status_code=413)

    kopf = {"Content-Type": "text/plain"}
    if (ip := _herkunft(anfrage)):
        kopf["X-Forwarded-For"] = ip
    if (browser := anfrage.headers.get("user-agent")):
        kopf["User-Agent"] = browser

    try:
        async with httpx.AsyncClient(timeout=5.0) as klient:
            antwort = await klient.post(f"{adresse}/api/event",
                                        content=roh, headers=kopf)
        if antwort.status_code >= 400:
            protokoll.warning("Zählung abgewiesen: %s", antwort.status_code)
    except httpx.HTTPError as fehler:
        protokoll.warning("Zählung nicht weitergereicht: %s", fehler)

    # Immer 202, auch wenn drinnen etwas schiefging. Ein verlorener
    # Seitenaufruf in der Statistik ist ärgerlich; ein Fehler in der
    # Konsole des Kunden wäre schlimmer und säße auf jeder Seite. Wo es
    # klemmt, steht im Protokoll — dort sucht man es auch.
    return Response(status_code=202)
