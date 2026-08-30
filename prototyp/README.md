# Prototyp (Vorgespräch, August 2026)

Die beiden Skripte sind der **unveränderte** Prototyp, mit dem der PDF/A-3-Kern
bewiesen wurde. Sie bleiben als Referenz liegen — die produktive, portierte
Fassung lebt in [`kern/`](../kern/).

| Datei | Zweck |
|---|---|
| `mk_briefpapier.py` | Erzeugt Testbögen mit den realen Problemfällen: CMYK-Flächen, RGB-Transparenz, Alphakanal-Logo. Modus `gut` = Schriften eingebettet (Liberation TTF), `boese` = Base-14 ohne Einbettung. |
| `mk_zugferd.py` | Briefpapier als Unterlage → reportlab-Overlay → CII-XML → PDF/A-3B mit OutputIntent, `factur-x.xml`-Anhang und XMP inkl. Factur-X-Extension-Schema. |

Validiertes Ergebnis beider Testfälle (nach Normalisierung per Ghostscript,
siehe `docs/uebergabe.md` §4):

```
PDF/A-3B validation profile — isCompliant="true"
passedRules=124  failedRules=0  failedChecks=0
XML: profile urn:cen.eu:en16931:2017 — status valid
```

Hinweise:

- `mk_zugferd.py` erwartet das **normalisierte** Briefpapier als Eingabe.
  Ohne den Ghostscript-Schritt scheitert die PDF/A-Prüfung an gemischten
  Farbräumen (siehe Übergabe, §4).
- Der ICC-Pfad (`/usr/share/texlive/...`) ist umgebungsspezifisch; die
  portierte Fassung in `kern/` sucht mehrere bekannte Pfade ab.
