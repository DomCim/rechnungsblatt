#!/usr/bin/env python3
"""Erzeugt das Demo-Briefpapier für den Schreibzonen-Editor.

Testbogen → Normalisierung (Ghostscript) → PNG-Vorschau nach
``web/zonen-editor/briefpapier.png``. Im Produkt liefert der Server an
dieser Stelle die Vorschau des Kunden-Uploads.

Aufruf: python scripts/zonen_editor_demo.py
Danach: python -m http.server -d web/zonen-editor 8000
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from rechnungsblatt_kern import erzeuge_vorschau_png, normalisiere_briefpapier
from rechnungsblatt_kern.testbogen import erzeuge_testbogen

ZIEL = Path(__file__).resolve().parent.parent / "web" / "zonen-editor" / "briefpapier.png"


def main() -> None:
    with tempfile.TemporaryDirectory() as verzeichnis:
        arbeit = Path(verzeichnis)
        upload = arbeit / "upload.pdf"
        upload.write_bytes(erzeuge_testbogen("gut"))
        norm = normalisiere_briefpapier(upload, arbeit / "norm.pdf")
        erzeuge_vorschau_png(norm.pfad, ZIEL, dpi=150)
    print(f"erzeugt: {ZIEL} ({ZIEL.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
