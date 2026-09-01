"""Holt die Webschriften ins Repository — einmalig und bei Erneuerung.

**Warum selbst ausliefern.** Vorher lud jede Seite von
``fonts.googleapis.com``. Zwei Gründe für den Wechsel, beide gemessen
bzw. belegt:

*Tempo.* Zwei fremde Verbindungen standen vor dem ersten sichtbaren
Zeichen — erst ``googleapis.com`` für das Stylesheet, dann
``gstatic.com`` für die Dateien selbst. PageSpeed maß dafür 3,3 s First
Contentful Paint bei 0 ms Blockierzeit: reine Wartezeit, kein Rechnen.

*Datenschutz.* Google Fonts überträgt die IP-Adresse jedes Besuchers an
Google (LG München I, 20.01.2022, 3 O 17493/20). Für ein Produkt, das
mit Verschlüsselung wirbt, ist das ein Widerspruch.

**Zwei Einsparungen, beide nachgerechnet** (350,5 → 219,9 KB, −37 %):

1. Die ``SOFT``-Achse von Fraunces entfällt. Sie kostete allein 111 KB
   und wurde nur mit den Werten 20 und 30 auf einer Skala bis 100
   benutzt — nebeneinander kaum zu unterscheiden.
2. Nur ``latin`` und ``latin-ext``. Die vietnamesische Teilmenge von
   Fraunces braucht diese Oberfläche nicht.

Die Achsenbereiche einzuengen bringt dagegen **nichts**: Google liefert
für jede Anfrage dieselbe Variable-Font-Datei. Auch geprüft, auch
verworfen.

Aufruf aus dem Wurzelverzeichnis::

    python scripts/hole_schriften.py
"""

from __future__ import annotations

import pathlib
import re
import urllib.request

# Ohne User-Agent liefert Google ein CSS für alte Browser — mit TTF
# statt woff2, also ein Vielfaches an Bytes.
KOPF = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

QUELLE = (
    "https://fonts.googleapis.com/css2"
    "?family=Fraunces:opsz,wght@9..144,400..800"
    "&family=Instrument+Sans:wght@400..600"
    "&family=Spline+Sans+Mono:wght@400..600"
    "&display=swap"
)

TEILMENGEN = ("latin", "latin-ext")

# Als Konstante: Ein Zeilenumbruch mitten in einem f-Ausdruck ist beim
# Erzeugen dieser Datei schon einmal zum echten Umbruch geworden.
KOMMENTAR = '/* {} */' + chr(10)

ZIEL = pathlib.Path("web/src/rechnungsblatt_web/seiten/schriften")

KOPFZEILE = """/* Selbst ausgelieferte Webschriften — NICHT von Hand ändern.

   Erzeugt von scripts/hole_schriften.py. Dort steht auch, warum die
   Schriften nicht mehr von Google kommen und was dabei eingespart wurde.
*/

"""


# Wird an das erzeugte CSS angehaengt. Steht hier und nicht nur
# in der CSS-Datei, weil ein neuer Lauf diese sonst ueberschriebe
# und der Layout-Sprung stillschweigend zurueckkaeme.
ERSATZSCHRIFTEN = '\n\n/* --- Metrisch angeglichene Ersatzschriften ---------------------------\n\n   Bei font-display:swap zeigt der Browser erst die Ersatzschrift und\n   tauscht dann. Weichen die Metriken ab, springt das Layout: gemessen\n   als CLS 0,117 (PageSpeed mobil, 01.09.2026). Vor allem Segoe UI ist\n   schuld — ascent 1,0791 gegen 0,9700 bei Instrument Sans.\n\n   Die Werte unten sind aus den Schriftdateien gerechnet, nicht\n   geschätzt: size-adjust gleicht die x-Höhen an, ascent- und\n   descent-override die Zeilenhöhe. Wer die Schriften wechselt, muss sie\n   neu rechnen — sonst wirken sie in die falsche Richtung.\n\n   Verwendung: In den font-family-Stacks steht "Fraunces Ersatz" bzw.\n   "Instrument Sans Ersatz" VOR der nackten Systemschrift.            */\n\n@font-face {\n  font-family: "Fraunces Ersatz";\n  src: local("Georgia"), local("Times New Roman"), local("Times");\n  size-adjust: 100.12%;\n  ascent-override: 97.68%;\n  descent-override: 25.47%;\n  line-gap-override: 0%;\n}\n\n@font-face {\n  font-family: "Instrument Sans Ersatz";\n  src: local("Segoe UI"), local("Helvetica Neue"), local("Arial");\n  size-adjust: 102.00%;\n  ascent-override: 95.10%;\n  descent-override: 24.51%;\n  line-gap-override: 0%;\n}\n'

def hole() -> None:
    css = urllib.request.urlopen(
        urllib.request.Request(QUELLE, headers=KOPF)
    ).read().decode("utf-8")

    ZIEL.mkdir(parents=True, exist_ok=True)
    for alt in ZIEL.glob("*.woff2"):
        alt.unlink()  # sonst bleiben Reste einer früheren Auswahl liegen

    bloecke: list[str] = []
    # Dieselbe Datei taucht mehrfach auf, wenn mehrere Schnitte darauf
    # zeigen — ohne diese Zuordnung lüde man sie mehrfach herunter und
    # zählte sie mehrfach.
    schon_geholt: dict[str, str] = {}
    gesamt = 0

    # Google schreibt vor jeden Block einen Kommentar mit der Teilmenge:
    #     /* latin-ext */
    #     @font-face { … }
    # Beides zusammen greifen, statt am Kommentar zu zerteilen — sonst
    # zerschneidet man die Blöcke an ihren eigenen Klammern.
    muster = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{[^}]*\})", re.S)
    for teilmenge, block in muster.findall(css):
        if teilmenge not in TEILMENGEN:
            continue

        adresse = re.search(r"url\((https://[^)]+)\)", block)
        familie = re.search(r"font-family:\s*'([^']+)'", block)
        if not (adresse and familie):
            continue

        url = adresse.group(1)
        if url in schon_geholt:
            name = schon_geholt[url]
        else:
            daten = urllib.request.urlopen(url).read()
            kurz = familie.group(1).lower().replace(" ", "-")
            name = f"{kurz}-{teilmenge}.woff2"
            (ZIEL / name).write_bytes(daten)
            schon_geholt[url] = name
            gesamt += len(daten)
            print(f"{len(daten) / 1024:8.1f} KB  {name}")

        # Der Kommentar mit der Teilmenge gehört mit ins erzeugte CSS —
        # sonst weiß beim nächsten Blick niemand, welcher Block welchen
        # Zeichensatz trägt.
        umgebogen = block.replace(url, f'/seiten/schriften/{name}')
        bloecke.append(KOMMENTAR.format(teilmenge) + umgebogen.strip())

    (ZIEL / "schriften.css").write_text(
        KOPFZEILE + "\n\n".join(bloecke) + "\n"
        + ERSATZSCHRIFTEN,
        encoding="utf-8",
    )
    print("-" * 40)
    print(f"{gesamt / 1024:8.1f} KB  in {len(schon_geholt)} Dateien")


if __name__ == "__main__":
    hole()
