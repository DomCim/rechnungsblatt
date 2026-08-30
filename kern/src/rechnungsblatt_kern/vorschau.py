"""Vorschau-Rendering: normalisiertes Briefpapier → PNG.

Die Web-Schicht braucht ein Bild des Bogens für den Schreibzonen-Editor
(zwei Regler) und die Rechnungsvorschau. Gerendert wird mit Ghostscript —
dasselbe Werkzeug, das schon die Normalisierung übernimmt.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class VorschauFehlgeschlagen(Exception):
    pass


def erzeuge_vorschau_png(
    pdf: str | Path,
    ausgabe: str | Path,
    dpi: int = 150,
    gs_programm: str = "gs",
) -> Path:
    """Rendert die erste Seite eines PDFs als PNG (A4 bei 150 dpi ≈ 1240×1754)."""
    pdf = Path(pdf)
    ausgabe = Path(ausgabe)
    if shutil.which(gs_programm) is None:
        raise VorschauFehlgeschlagen(f"Ghostscript ({gs_programm!r}) ist nicht installiert.")
    lauf = subprocess.run(
        [
            gs_programm,
            "-dQUIET",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=png16m",
            f"-r{dpi}",
            "-dFirstPage=1",
            "-dLastPage=1",
            "-dTextAlphaBits=4",
            "-dGraphicsAlphaBits=4",
            f"-sOutputFile={ausgabe}",
            str(pdf),
        ],
        capture_output=True,
        text=True,
    )
    if lauf.returncode != 0 or not ausgabe.exists() or ausgabe.stat().st_size == 0:
        raise VorschauFehlgeschlagen(
            f"PNG-Vorschau fehlgeschlagen (Exit {lauf.returncode}): "
            f"{lauf.stderr.strip() or lauf.stdout.strip()}"
        )
    return ausgabe
