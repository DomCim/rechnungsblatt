"""rechnungsblatt-web — die Web-Schicht über dem Rechnungskern.

Einzelmandant (der Betreiber selbst); Konten und Bezahlung je Rechnung
kommen später (MVP-Schnitt, Übergabe §8). Alle Zustandsdaten liegen im
Datenverzeichnis (Umgebungsvariable ``DATEN_VERZEICHNIS``, Standard
``/daten``) — im Docker-Betrieb ein Volume.
"""
