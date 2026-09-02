# Die Rechtsseiten erzeugen

`impressum.html`, `datenschutz.html` und `agb.html` unter
`web/src/rechnungsblatt_web/seiten/` sind **erzeugt**, nicht von Hand
geschrieben. Wer sie direkt bearbeitet, verliert die Änderung beim
nächsten Lauf.

```bash
python scripts/rechtsseiten/impressum.py
python scripts/rechtsseiten/datenschutz.py
python scripts/rechtsseiten/agb.py
```

Aufruf aus dem Wurzelverzeichnis. Die Betreiberangaben stehen einmal in
`gemeinsam.py` (`BETRIEB`) — Anschrift und E-Mail also dort ändern, nicht
dreimal.

## Warum erzeugt und nicht handgeschrieben

Die drei Seiten teilen Aufbau, Stil und die Betreiberangaben. Von Hand
gepflegt liefen sie auseinander: eine geänderte Anschrift stünde an zwei
Stellen richtig und an einer falsch — und genau das fällt bei
Pflichtangaben niemandem auf, bis es zählt.

## Was beim Ändern zu beachten ist

- **`beschreibung` zwischen 70 und 155 Zeichen.** Bing meldet kürzere als
  „too short", längere als „too long". Die erste Fassung lag bei 39 bis 60
  Zeichen und wäre beanstandet worden.
- **Kein `data-i18n`.** Die Seiten sind bewusst nur deutsch: Bei
  abweichenden Übersetzungen wäre unklar, welche Fassung gilt. Ein Test
  hält das fest.
- **Keine Steuernummer im Impressum.** § 5 DDG verlangt allein die
  USt-IdNr.; die gibt es beim Kleinunternehmer nicht. Ein Test sperrt das.
- Nach dem Erzeugen `web/tests/test_rechtsseiten.py` laufen lassen — dort
  stehen die Pflichtangaben unter Test.
