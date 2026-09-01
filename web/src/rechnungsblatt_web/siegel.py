"""Die Siegelkette — macht nachträgliche Änderungen sichtbar.

**Das Problem, das sie löst.** Die GoBD halten fest, dass die Ablage von
Dokumenten in einem Dateisystem die Unveränderbarkeit „regelmäßig nicht"
gewährleistet, solange keine zusätzlichen Maßnahmen hinzutreten
(BMF-Schreiben vom 28.11.2019, Rz. 110). Rechnungsblatt legt seine Belege
als Dateien ab. Nummernsperre und fehlender Löschweg sind solche
Maßnahmen — aber sie wirken nur *innerhalb* der Anwendung. Wer an den
Dateien vorbei ans Volume kommt, hinterlässt keine Spur.

**Was die Kette tut.** Für jeden Beleg wird beim Erzeugen ein Siegel
gebildet: der SHA-256 über PDF, XML und Eingabedaten, verknüpft mit dem
Siegel des vorhergehenden Belegs. Jedes Glied hängt damit an allen
vorherigen. Wird ein Beleg später verändert oder entfernt, passt sein
Siegel nicht mehr — und weil die folgenden Glieder darauf aufbauen, lässt
sich die Kette auch nicht stillschweigend neu rechnen, ohne dass die
Änderung an allen Nachfolgern sichtbar würde.

**Bewusst unverschlüsselt.** Die Belege liegen verschlüsselt; der
Betreiber kann sie nicht lesen. Diese Datei liegt im Klartext, weil sie
nur Hashes und Nummern enthält — nichts, was schützenswert wäre. Läge sie
verschlüsselt, wäre der Nachweis mit einem verlorenen Kennwort ebenfalls
verloren, und genau dann braucht man ihn.

**Was sie nicht ist.** Kein Zeitstempel einer anerkannten Stelle und kein
Beweis gegenüber Dritten: Wer Schreibzugriff auf das Volume hat, kann die
ganze Kette neu bilden. Sie zeigt, dass *punktuell* nichts geändert wurde
— nicht, dass der Betreiber es nicht könnte. Für mehr bräuchte es eine
Ablage außerhalb des eigenen Zugriffs. Das steht so auch in der
Verfahrensdokumentation; ein Nachweis, der mehr verspricht als er hält,
schadet in der Prüfung.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

DATEI = "siegel.jsonl"

# Die Dateien, die ein Siegel umfasst — in dieser Reihenfolge, sonst
# fiele der Hash je nach Verzeichnisreihenfolge anders aus.
GESIEGELT = ("rechnung.pdf", "factur-x.xml", "daten.json")

# Das erste Glied hat keinen Vorgänger. Ein fester Anker statt eines
# leeren Werts, damit auch das erste Siegel eine feste Länge hat.
ANKER = "0" * 64


def _kettendatei(wurzel: Path) -> Path:
    return wurzel / "ablage" / DATEI


def _abdruck(ordner: Path) -> str:
    """SHA-256 über die Dateien eines Belegs, so wie sie auf der Platte liegen.

    Über die **verschlüsselten** Bytes, nicht über den Klartext: Geprüft
    werden soll, ob jemand an den Dateien war — und dafür ist maßgeblich,
    was dort steht, nicht was es bedeutet. So lässt sich die Kette zudem
    ohne Schlüssel prüfen.
    """
    hasher = hashlib.sha256()
    for name in GESIEGELT:
        pfad = ordner / name
        # Der Name geht mit ein, damit ein Vertauschen zweier Dateien
        # nicht denselben Abdruck ergäbe.
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        if pfad.exists():
            hasher.update(pfad.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _glied(nummer: str, abdruck: str, vorher: str, zeitpunkt: str) -> str:
    """Verknüpft den Abdruck mit dem Vorgänger — das macht die Kette."""
    roh = "|".join((vorher, nummer, abdruck, zeitpunkt))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def lies(wurzel: Path) -> list[dict]:
    """Die Kette, ältestes Glied zuerst. Leere Liste, wenn es keine gibt."""
    pfad = _kettendatei(wurzel)
    if not pfad.exists():
        return []
    glieder = []
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            glieder.append(json.loads(zeile))
        except ValueError:
            glieder.append({"nummer": "?", "fehler": "unlesbar"})
    return glieder


def siegle(wurzel: Path, nummer: str) -> dict:
    """Hängt ein Glied für einen frisch erzeugten Beleg an.

    Wird nach dem Schreiben von PDF, XML und Daten aufgerufen — vorher
    stünde im Abdruck nicht das, was am Ende auf der Platte liegt.
    """
    ordner = wurzel / "ablage" / nummer
    kette = lies(wurzel)
    vorher = kette[-1]["siegel"] if kette else ANKER
    zeitpunkt = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(
        timespec="seconds")
    abdruck = _abdruck(ordner)
    glied = {
        "nummer": nummer,
        "zeitpunkt": zeitpunkt,
        "abdruck": abdruck,
        "vorher": vorher,
        "siegel": _glied(nummer, abdruck, vorher, zeitpunkt),
    }
    pfad = _kettendatei(wurzel)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    # Anhängen, nicht neu schreiben: Ein Fehler beim Schreiben soll die
    # bestehende Kette nicht mitnehmen.
    with pfad.open("a", encoding="utf-8") as datei:
        datei.write(json.dumps(glied, ensure_ascii=False, sort_keys=True) + "\n")
    return glied


def pruefe(wurzel: Path) -> dict:
    """Rechnet die Kette nach und meldet, wo sie nicht mehr aufgeht.

    Drei Arten von Befund werden unterschieden, weil sie verschiedenes
    bedeuten:

    ``geaendert``  Die Dateien des Belegs ergeben einen anderen Abdruck
                   als beim Erzeugen — jemand hat sie angefasst.
    ``fehlt``      Der Beleg ist gar nicht mehr da.
    ``kette``      Das Glied verweist nicht auf seinen Vorgänger — es
                   wurde eingefügt, entfernt oder umgeschrieben.
    """
    kette = lies(wurzel)
    befunde: list[dict] = []
    vorher = ANKER
    for glied in kette:
        nummer = glied.get("nummer", "?")
        if glied.get("fehler"):
            befunde.append({"nummer": nummer, "art": "kette",
                            "hinweis": "Zeile nicht lesbar."})
            # Ohne lesbares Glied ist der Faden ab; die Kette dahinter
            # lässt sich nicht mehr sinnvoll nachrechnen.
            return {"glieder": len(kette), "heil": False, "befunde": befunde}

        if glied.get("vorher") != vorher:
            befunde.append({"nummer": nummer, "art": "kette",
                            "hinweis": "Verweist nicht auf das vorige Glied."})
        erwartet = _glied(nummer, glied.get("abdruck", ""),
                          glied.get("vorher", ""), glied.get("zeitpunkt", ""))
        if erwartet != glied.get("siegel"):
            befunde.append({"nummer": nummer, "art": "kette",
                            "hinweis": "Das Siegel passt nicht zu seinem Inhalt."})

        ordner = wurzel / "ablage" / nummer
        if not ordner.is_dir():
            befunde.append({"nummer": nummer, "art": "fehlt",
                            "hinweis": "Der Beleg liegt nicht mehr in der Ablage."})
        elif _abdruck(ordner) != glied.get("abdruck"):
            befunde.append({"nummer": nummer, "art": "geaendert",
                            "hinweis": "Die Dateien weichen vom Siegel ab."})

        vorher = glied.get("siegel", "")

    # Belege ohne Glied: aus der Zeit vor der Kette, oder danebengelegt.
    # Kein Fehler, aber eine Angabe, die in den Bericht gehört.
    basis = wurzel / "ablage"
    vorhanden = {o.name for o in basis.iterdir() if o.is_dir()} if basis.is_dir() else set()
    ohne_siegel = sorted(vorhanden - {g.get("nummer") for g in kette})

    return {
        "glieder": len(kette),
        "heil": not befunde,
        "befunde": befunde,
        "ohne_siegel": ohne_siegel,
    }
