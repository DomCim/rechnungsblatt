"""Die verschlüsselte Dateiablage eines Mandanten.

Die Nutzdaten liegen verschlüsselt auf der Platte; der Schlüssel kommt aus
der Sitzung (siehe ``tresor``). Ohne Schlüssel wird im Klartext gelesen und
geschrieben — das betrifft nur Konten aus der Zeit davor und die Tests.

**Der Schlüssel hängt am Pfadobjekt, nicht an einer Kontextvariablen.**
FastAPI führt synchrone Endpunkte in einem Threadpool aus, und eine in
``mandant`` gesetzte ContextVar erreicht den Endpunkt dort nicht.
``mandant`` liefert ohnehin genau dieses Pfadobjekt an jeden Endpunkt — der
Schlüssel reist damit mit, ohne durch jede Hilfsfunktion gereicht zu werden.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path

from fastapi import HTTPException

from . import tresor


# --- Verschlüsselte Ablage --------------------------------------------
#
# Die Nutzdaten liegen verschlüsselt auf der Platte; der Schlüssel kommt
# aus der Sitzung (siehe `tresor`). Ohne Schlüssel wird im Klartext
# gelesen und geschrieben — das betrifft nur Konten aus der Zeit davor und
# die Tests.
#
# Der Schlüssel hängt am Mandantenverzeichnis, nicht an einer
# Kontextvariablen: FastAPI führt synchrone Endpunkte in einem Threadpool
# aus, und eine in `mandant` gesetzte ContextVar erreicht den Endpunkt
# dort nicht. `mandant` liefert ohnehin genau dieses Pfadobjekt an jeden
# Endpunkt — der Schlüssel reist damit mit, ohne durch jede
# Hilfsfunktion gereicht zu werden.
class Mandantenpfad(Path):
    """Pfad des Mandantenverzeichnisses samt seinem Datenschlüssel."""

    _flavour = type(Path())._flavour        # von pathlib verlangt
    schluessel: bytes | None = None

    def _make_child_relpath(self, name):    # noqa: N802 (pathlib-Vorgabe)
        kind = super()._make_child_relpath(name)
        kind.schluessel = self.schluessel
        return kind

    def __truediv__(self, andere):
        kind = super().__truediv__(andere)
        if isinstance(kind, Mandantenpfad):
            kind.schluessel = self.schluessel
        return kind


def schluessel_zu(pfad: Path) -> bytes | None:
    """Findet den Schlüssel zu einem Pfad innerhalb des Mandantenordners."""
    if isinstance(pfad, Mandantenpfad):
        return pfad.schluessel
    for eltern in pfad.parents:
        if isinstance(eltern, Mandantenpfad):
            return eltern.schluessel
    return None


def lies_datei(pfad: Path, schluessel: bytes | None = None) -> bytes:
    """Rohbytes einer Mandantendatei, entschlüsselt wenn nötig."""
    inhalt = pfad.read_bytes()
    if schluessel is None:
        schluessel = schluessel_zu(pfad)
    if schluessel is None:
        if tresor.ist_verschluesselt(inhalt):
            raise HTTPException(
                409,
                detail={
                    "code": "kein_schluessel",
                    "grund": "Die Daten sind verschlüsselt, aber diese Sitzung "
                    "trägt keinen Schlüssel. Bitte neu anmelden.",
                },
            )
        return inhalt
    try:
        return tresor.entschluessle(inhalt, schluessel)
    except tresor.TresorFehler as fehler:
        raise HTTPException(
            409,
            detail={"code": "schluessel_passt_nicht",
                    "grund": "Diese Datei lässt sich nicht entschlüsseln."},
        ) from fehler


def schreibe_datei(pfad: Path, inhalt: bytes,
                   schluessel: bytes | None = None) -> None:
    """Schreibt eine Mandantendatei, verschlüsselt wenn ein Schlüssel da ist."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    if schluessel is None:
        schluessel = schluessel_zu(pfad)
    if schluessel is not None:
        inhalt = tresor.verschluessle(inhalt, schluessel)
    pfad.write_bytes(inhalt)


def lese_json(pfad: Path) -> dict | None:
    if not pfad.exists():
        return None
    return json.loads(lies_datei(pfad).decode("utf-8"))


def schreibe_json(pfad: Path, daten: dict) -> None:
    schreibe_datei(
        pfad, json.dumps(daten, ensure_ascii=False, indent=2).encode("utf-8")
    )


@contextlib.contextmanager
def im_klartext(pfad: Path):
    """Stellt eine Mandantendatei kurz entschlüsselt bereit.

    Der Kern nimmt Pfade, keine Bytes — er öffnet das Briefpapier selbst.
    Ein Schlüssel ist ihm fremd und soll es bleiben: Verschlüsselung ist
    Sache der Web-Schicht (``docs/uebergabe.md`` §2).

    Die Kopie liegt in einem Temporärverzeichnis **innerhalb** des
    Mandantenordners und verschwindet mit dem Block — auch bei einer
    Ausnahme. Nicht in /tmp: dort läge Klartext außerhalb des Volumes.
    """
    if not pfad.exists():
        yield pfad
        return
    inhalt = lies_datei(pfad)
    with tempfile.TemporaryDirectory(dir=pfad.parent) as arbeit:
        klar = Path(arbeit) / pfad.name
        klar.write_bytes(inhalt)
        yield klar


def briefpapier_pfad(wurzel: Path) -> Path:
    return wurzel / "briefpapier_norm.pdf"


def vorschau_pfad(wurzel: Path) -> Path:
    return wurzel / "briefpapier_vorschau.png"


def ist_bereit(wurzel: Path) -> bool:
    return bool(
        lese_json(wurzel / "briefpapier.json")
        and lese_json(wurzel / "schreibzone.json")
        and lese_json(wurzel / "stammdaten.json")
    )


def ablage_ordner(wurzel: Path, nummer: str) -> Path:
    ordner = (wurzel / "ablage" / nummer).resolve()
    if not ordner.is_relative_to((wurzel / "ablage").resolve()) or not ordner.is_dir():
        raise HTTPException(404, detail={"grund": "Beleg nicht gefunden."})
    # resolve() baut ein neues Pfadobjekt und verliert dabei den Schlüssel
    # — hier wieder anheften, sonst stehen die Belege ohne ihn da.
    if isinstance(wurzel, Mandantenpfad):
        ordner = Mandantenpfad(ordner)
        ordner.schluessel = wurzel.schluessel
    return ordner
