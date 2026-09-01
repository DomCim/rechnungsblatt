"""Das Belegprotokoll — was wann mit einem Beleg geschah.

**Wozu.** Die GoBD verlangen, dass sich Geschäftsvorfälle nachvollziehen
lassen: Wann ist ein Beleg entstanden, was ist danach mit ihm passiert.
Rechnungsblatt erfüllt den harten Teil davon schon lange — es gibt keinen
Weg, einen Beleg zu löschen, und eine vergebene Nummer lässt sich nicht
überschreiben (409 ``nummer_vergeben``). Nur sehen konnte man das nicht.

Das Protokoll macht es sichtbar. Es liegt als eine Zeile JSON je Ereignis
neben dem Beleg und wird **nur angehängt**, nie geändert. Wer eine
Rechnung storniert, erzeugt keinen Eintrag „geändert", sondern einen
zweiten Beleg mit Bezug — und beide Protokolle halten fest, dass sie
zusammengehören.

**Kein Ersatz für eine Verfahrensdokumentation.** Die schuldet der
Steuerpflichtige, nicht die Software (GoBD Rz. 151 f.). Rechnungsblatt
liefert unter ``/api/pruefung/verfahrensdokumentation`` einen Entwurf, der
den technischen Teil beschreibt; ergänzen muss ihn der Kunde selbst.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .ablage import lies_datei, schreibe_datei

DATEI = "protokoll.jsonl"


def _jetzt() -> str:
    """Zeitstempel mit Zeitzone — ohne sie ist er beim Prüfer wertlos."""
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def haenge_an(ordner: Path, ereignis: str, **einzelheiten) -> None:
    """Schreibt eine Zeile ans Protokoll eines Belegs.

    Angehängt, nicht ersetzt: Ein Protokoll, das sich überschreiben lässt,
    beweist nichts. Bestehende Zeilen werden gelesen und unverändert
    mitgeschrieben — die Datei liegt verschlüsselt, ein reines Anhängen
    ginge daran vorbei.
    """
    pfad = ordner / DATEI
    zeilen = []
    if pfad.exists():
        zeilen = lies_datei(pfad).decode("utf-8").splitlines()
    eintrag = {"zeitpunkt": _jetzt(), "ereignis": ereignis, **einzelheiten}
    zeilen.append(json.dumps(eintrag, ensure_ascii=False, sort_keys=True))
    schreibe_datei(pfad, ("\n".join(zeilen) + "\n").encode("utf-8"))


def lies(ordner: Path) -> list[dict]:
    """Das Protokoll eines Belegs, älteste Zeile zuerst.

    Leere Liste, wenn es keines gibt: Belege aus der Zeit vor dem
    Protokoll sollen deshalb nicht als fehlerhaft gelten.
    """
    pfad = ordner / DATEI
    if not pfad.exists():
        return []
    eintraege = []
    for zeile in lies_datei(pfad).decode("utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            eintraege.append(json.loads(zeile))
        except ValueError:
            # Eine unlesbare Zeile darf nicht das ganze Protokoll
            # verschlucken — sie wird als solche gemeldet.
            eintraege.append({"ereignis": "unlesbar", "roh": zeile[:200]})
    return eintraege
