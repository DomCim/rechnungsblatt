"""Die Verfahrensdokumentation — ein Entwurf zum Weiterschreiben.

**Warum die Software das ueberhaupt anbietet.** Die Verfahrensdokumentation
schuldet der Steuerpflichtige, nicht der Hersteller (GoBD Rz. 21, 151).
Genau das macht sie fuer einen Einzelunternehmer zur Huerde: Er soll etwas
beschreiben, dessen technischen Teil nur der Hersteller kennt.

Dieses Modul schreibt deshalb den Teil, den Rechnungsblatt belegen kann —
wie eine Rechnung entsteht, was geprueft wird, warum sie sich nicht
aendern laesst, wie lange sie liegt. Was das Unternehmen selbst regeln
muss, steht als offene Frage in Abschnitt 8 und nicht als erfundene
Behauptung im Text.

**Bewusst kein Freibrief.** Abschnitt 5.2 sagt ausdruecklich, dass die
Ablage im Dateisystem die Unveraenderbarkeit fuer sich genommen nicht
gewaehrleistet (GoBD Rz. 110) und dass die Bewertung dem steuerlichen
Berater zusteht. Ein Dokument, das dem Kunden Sicherheit verspricht, die
es nicht geben kann, schadet ihm in der Pruefung mehr als es nuetzt.
"""

from __future__ import annotations

import datetime as dt
import os
from importlib import metadata
from pathlib import Path

from . import siegel
from .ablage import lese_json

# Als chr() und nicht als Escape: Beim Erzeugen dieser Datei wuerde ein
# Backslash-n leicht zum echten Umbruch im Quelltext.
CRLF = chr(13) + chr(10)

_VORLAGE: list[str] = [
    # --- kopf ---
        'VERFAHRENSDOKUMENTATION',
        'Ausgangsrechnungen mit Rechnungsblatt',
        '',
        'Unternehmen:      {firma}',
        'Anschrift:        {anschrift}',
        'Steuernummer:     {steuernummer}',
        'USt-IdNr.:        {ustid}',
    'Besteuerung:      {steuerart}',
        '',
        'Stand:            {stand}',
        'Softwarestand:    Rechnungsblatt {version}',
        '',
        'ENTWURF. Dieses Dokument beschreibt den technischen Teil des',
        'Verfahrens. Es ist zu ergänzen und zu verantworten vom',
        'Steuerpflichtigen (GoBD Rz. 21, 151). Siehe Abschnitt 8.',
        '',
    # --- 1 ---
        '1. ZWECK UND GELTUNGSBEREICH',
        '',
        'Diese Dokumentation beschreibt, wie im oben genannten Unternehmen',
        'Ausgangsrechnungen entstehen, ausgegeben und aufbewahrt werden.',
        '',
        'Sie erfasst ausschließlich die Fakturierung. Buchführung,',
        'Eingangsrechnungen, Kasse und Zahlungsverkehr sind nicht Gegenstand',
        'dieses Dokuments und bedürfen eigener Beschreibungen.',
        '',
        'Die GoBD nennen die Fakturierung ausdrücklich als Vor- bzw.',
        'Nebensystem (BMF-Schreiben vom 28.11.2019, Rz. 20). Der Betrieb in',
        'einer Cloud ist dort ebenso ausdrücklich erfasst.',
        '',
    # --- 2 ---
        '2. EINGESETZTES SYSTEM',
        '',
        'Bezeichnung:      Rechnungsblatt',
        'Betriebsart:      Webanwendung, Zugriff über Browser',
        'Stand:            {version}',
        'Datenhaltung:     je Mandant getrenntes Verzeichnis;',
        '                  Konten und Verbrauch in PostgreSQL',
        '',
        'Rechnungsblatt schreibt Rechnungen auf das Briefpapier des',
        'Unternehmens und erzeugt dabei zugleich die elektronische Rechnung',
        'nach EN 16931 (ZUGFeRD/Factur-X im PDF, auf Wunsch XRechnung als',
        'reines XML).',
        '',
        'Programmidentität (GoBD Rz. 154): Der Softwarestand ist oben',
        'benannt und wird bei jeder Ausgabe dieses Dokuments mitgeführt.',
        'Aendert sich die Version, ist dieses Dokument neu zu erzeugen und',
        'die alte Fassung aufzubewahren.',
        '',
    # --- 3 ---
        '3. DER WEG EINER RECHNUNG',
        '',
        '3.1 Erfassung',
        '',
        'Der Anwender erfasst Empfänger, Leistungen, Mengen und Preise. Aus',
        'dem Kundenstamm und dem Artikelstamm lässt sich übernehmen, was',
        'bereits erfasst wurde; wiederkehrende Positionslisten stehen als',
        'Vorlage bereit. Beträge werden durchgängig als Dezimalzahl mit',
        'zwei Nachkommastellen geführt und kaufmännisch gerundet',
        '(ROUND_HALF_UP). Gleitkommazahlen kommen nicht zum Einsatz.',
        '',
        '3.2 Prüfung vor der Ausgabe',
        '',
        'Vor der Ausgabe prüft das System die Pflichtangaben nach',
        '§ 14 UStG sowie die Regeln der EN 16931. Jeder Befund',
        'trägt einen festen Code. Eine Rechnung mit schwerem Befund wird',
        'nicht ausgegeben.',
        '',
        'Geprüft werden unter anderem:',
        '',
        '  - Pflichtangaben beider Parteien einschließlich Anschrift',
        '  - Steuernummer oder USt-IdNr. des Ausstellers',
        '  - fortlaufende Rechnungsnummer, Rechnungsdatum, Leistungszeitpunkt',
        '  - Übereinstimmung von Positionssummen und Gesamtsumme',
        '  - Kleinunternehmerregelung (§ 19 UStG): kein Steuerausweis,',
        '    und umgekehrt kein Kleinunternehmerhinweis bei Steuerausweis',
        '  - Reverse Charge, innergemeinschaftliche Lieferung und Ausfuhr:',
        '    USt-IdNr. beider Parteien, Hinweistext',
        '  - IBAN mit echter Prüfsumme nach MOD 97',
        '',
        '3.3 Ausgabe',
        '',
        'PDF und XML entstehen aus denselben erfassten Daten im selben',
        'Vorgang. Ein bereits erzeugtes PDF wird nie nachträglich',
        'angereichert. Damit kann der bildhafte Teil nicht vom',
        'strukturierten abweichen.',
        '',
        'Das PDF wird als PDF/A-3B erzeugt; die XML-Datei ist als Anhang mit',
        'der Beziehung Alternative eingebettet. Bei hybriden Formaten ist der',
        'strukturierte Teil maßgeblich und darf nicht durch',
        'Formatumwandlung verlorengehen (GoBD Rz. 125 in der Fassung vom',
        '14.07.2025). Rechnungsblatt bewahrt beide Teile auf.',
        '',
        '3.4 Ausgang',
        '',
        'Der Versand an den Empfänger erfolgt außerhalb von Rechnungsblatt.',
        'Wie er geschieht und wie er nachgewiesen wird, ist in Abschnitt 8',
        'zu ergänzen.',
        '',
    # --- 4 ---
        '4. NUMMERNKREIS',
        '',
        'Jede Rechnung trägt eine eindeutige Nummer. Das System schlägt die',
        'nächste freie Nummer vor und führt den Kreis fort.',
        '',
        'Eine bereits vergebene Nummer wird nicht überschrieben. Der Versuch',
        'wird abgewiesen, bevor irgendetwas geschrieben wird. Es gibt keinen',
        'Weg, eine vergebene Nummer erneut zu verwenden.',
        '',
        'Aktuell vergeben: {anzahl_belege} Beleg(e).',
        '{nummernspanne}',
        '',
    # --- 5 ---
        '5. UNVERÄNDERBARKEIT UND KORREKTUREN',
        '',
        'Eine ausgegebene Rechnung wird nicht geändert. Das System bietet',
        'dafür keinen Weg an - weder über die Oberfläche noch über die',
        'Schnittstelle. Es gibt ebenso keinen Weg, einen abgelegten Beleg zu',
        'löschen.',
        '',
        'Ist eine Rechnung falsch, entsteht ein zweiter Beleg:',
        '',
        '  Gutschrift (Belegart 381)   hebt die Rechnung auf',
        '  Korrektur  (Belegart 384)   berichtigt sie',
        '',
        'Beide tragen die Nummer und das Datum des Urbelegs im XML',
        '(InvoiceReferencedDocument). Der Zusammenhang bleibt damit auch',
        'maschinell nachvollziehbar.',
        '',
        '5.1 Belegprotokoll',
        '',
        'Neben jedem Beleg liegt ein Protokoll. Es wird nur angehängt, nie',
        'geändert, und hält fest:',
        '',
        '  - wann der Beleg entstand, mit Nummer, Art, Betrag und Empfänger',
        '  - ob und wann er aufgehoben oder berichtigt wurde, und wodurch',
        '',
        'Wird eine Rechnung storniert, erhalten beide Belege einen Eintrag -',
        'der neue mit dem Bezug, der alte mit dem Vermerk der Aufhebung.',
        '',
        '5.2 Siegelkette',
        '',
        'Beim Erzeugen erhält jeder Beleg ein Siegel: den SHA-256 über PDF,',
        'XML und Eingabedaten, verknüpft mit dem Siegel des vorhergehenden',
        'Belegs. Die Siegel stehen in siegel.jsonl neben der Ablage.',
        '',
        'Wird ein Beleg nachträglich verändert oder entfernt, passt sein',
        'Siegel nicht mehr. Da jedes Glied am vorigen hängt, lässt sich die',
        'Kette nicht an einer Stelle stillschweigend neu bilden - die',
        'Abweichung würde an allen folgenden Belegen sichtbar.',
        '',
        'Die Kette lässt sich jederzeit nachrechnen (Konto - Für die',
        'Betriebsprüfung) und liegt der Belegausgabe vollständig bei. Sie',
        'ist unverschlüsselt, damit sie auch dann noch prüfbar ist, wenn der',
        'Zugang zum Konto verloren geht; sie enthält nur Prüfsummen.',
        '',
        'Geprüft am {stand}: {siegelstand}',
        '',
        '5.3 Was diese Maßnahmen nicht leisten',
        '',
        'Die Belege liegen als Dateien. Die GoBD halten fest, dass die',
        'Ablage im Dateisystem die Unveränderbarkeit für sich genommen',
        'regelmäßig nicht gewährleistet, solange keine zusätzlichen',
        'Maßnahmen hinzutreten (Rz. 110).',
        '',
        'Als solche Maßnahmen wirken hier: die Nummernsperre, das Fehlen',
        'jedes Lösch- und Änderungswegs, das fortgeschriebene Protokoll, die',
        'Siegelkette nach 5.2 und die Verschlüsselung der abgelegten Dateien.',
        '',
        'Die Siegelkette ist kein Zeitstempel einer anerkannten Stelle. Wer',
        'Schreibzugriff auf die Ablage hat, könnte sie im Ganzen neu bilden;',
        'sie belegt, dass punktuell nichts geändert wurde, nicht dass es',
        'niemand könnte. Eine Ablage außerhalb des eigenen Zugriffs leistet',
        'mehr - Rechnungsblatt bietet sie nicht an.',
        '',
        'Ob die Maßnahmen im Einzelfall genügen, ist eine Bewertung, die der',
        'steuerliche Berater vornimmt. Diese Dokumentation trifft sie nicht.',
        '',
    # --- 6 ---
        '6. AUFBEWAHRUNG',
        '',
        'Frist:  acht Jahre (§ 147 Abs. 3 AO, § 14b Abs. 1 UStG in der',
        '        Fassung seit 01.01.2025). Sie beginnt mit dem Ende des',
        '        Kalenderjahres der Ausstellung.',
        '',
        'Zu beachten: Die Frist läuft nicht ab, solange die Unterlagen für',
        'eine noch nicht verjährte Steuerfestsetzung von Bedeutung sind',
        '(§ 147 Abs. 3 Satz 5 AO). Ein Löschen allein nach Fristablauf',
        'wäre daher nicht ausreichend geprüft.',
        '',
        'Aufbewahrt wird je Beleg:',
        '',
        '  rechnung.pdf     der Beleg als PDF/A-3B mit eingebettetem XML',
        '  factur-x.xml     der strukturierte Teil zusätzlich einzeln',
        '  daten.json       die Eingaben, aus denen beides entstand',
        '  protokoll.jsonl  das Belegprotokoll nach Abschnitt 5.1',
        '',
        'Die Dateien liegen verschlüsselt. Der Schlüssel hängt am Konto',
        'und wird beim Anmelden aus dem Kennwort abgeleitet; der Betreiber',
        'kann die Belege nicht einsehen.',
        '',
        '6.1 Zugriff durch die Betriebsprüfung',
        '',
        'Über Konto - Für die Betriebsprüfung gibt das System alle Belege',
        'eines Zeitraums als ZIP heraus: je Beleg die vier oben genannten',
        'Dateien, dazu eine Tabelle uebersicht.csv und eine Erläuterung.',
        'Damit ist der Bestand ohne Zugriff auf das laufende System',
        'auswertbar.',
        '',
    # --- 7 ---
        '7. ZUGRIFF UND BERECHTIGUNGEN',
        '',
        'Der Zugang erfolgt mit Benutzername und Kennwort. Jeder Mandant',
        'sieht ausschließlich seine eigenen Daten; sie liegen in getrennten',
        'Verzeichnissen.',
        '',
        'Wer im Unternehmen Rechnungen schreiben darf und wie die',
        'Zugangsdaten verwahrt werden, ist in Abschnitt 8 zu ergänzen.',
        '',
    # --- 8 ---
        '8. ZU ERGÄNZEN DURCH DAS UNTERNEHMEN',
        '',
        'Die folgenden Punkte kann die Software nicht beschreiben, weil sie',
        'die Abläufe im Unternehmen betreffen. Sie sind Bestandteil der',
        'Verfahrensdokumentation und vom Steuerpflichtigen zu verantworten',
        '(GoBD Rz. 21).',
        '',
        '  1. Wer erfasst Rechnungen, wer gibt sie frei, wer vertritt',
        '     diese Personen bei Abwesenheit?',
        '',
        '  2. Wie gelangt die Rechnung zum Empfänger (E-Mail, Portal, Post)',
        '     und wie wird der Versand nachgewiesen?',
        '',
        '  3. Wie gelangen die Rechnungsdaten in die Buchführung, und in',
        '     welchem Abstand geschieht das?',
        '',
        '  4. Wie wird mit Rechnungen verfahren, die vor Einführung dieses',
        '     Systems entstanden sind?',
        '',
        '  5. Welche Sicherung besteht zusätzlich zur Ablage im System, und',
        '     wer prüft sie wie oft?',
        '',
        '  6. Wie wird der Zugang bei Ausscheiden eines Mitarbeiters',
        '     entzogen?',
        '',
        '  7. Wer prüft diese Dokumentation, in welchem Abstand, und wo',
        '     werden die früheren Fassungen aufbewahrt?',
        '',
        'Ein Muster für die übrigen Teile einer Verfahrensdokumentation',
        'geben die AWV und die Bundessteuerberaterkammer kostenfrei heraus.',
        '',
    # --- 9 ---
        '9. RECHTLICHER HINWEIS',
        '',
        'Dieser Entwurf ersetzt keine steuerliche Beratung. Für die',
        'Ordnungsmäßigkeit ist allein der Steuerpflichtige verantwortlich,',
        'auch bei Auslagerung an Dritte (GoBD Rz. 21).',
        '',
        'Eine Zertifizierung der Ordnungsmäßigkeit durch die',
        'Finanzverwaltung gibt es nicht; Testate Dritter entfalten ihr',
        'gegenüber keine Bindungswirkung (GoBD Rz. 179 bis 181).',
        '',
        'Herangezogene Quellen:',
        '',
        '  BMF-Schreiben vom 28.11.2019 (GoBD), zuletzt geändert durch',
        '  BMF-Schreiben vom 14.07.2025',
        '  BMF-Schreiben vom 15.10.2025 zur obligatorischen E-Rechnung',
        '  § 146, 147 AO; § 14, 14b, 19 UStG',
        '',
]


def softwarestand() -> str:
    """Welcher Stand laeuft — fuer die Programmidentitaet (GoBD Rz. 154).

    Im Stack setzt ``RECHNUNGSBLATT_VERSION`` fest, welches Image gezogen
    wird; steht dort ein Datum oder ``sha-<commit>``, ist das die
    genauere Angabe. Ohne die Variable (``latest``) bleibt die
    Paketversion, die bei jedem Bau mitwandert.
    """
    aus_umgebung = (os.environ.get("RECHNUNGSBLATT_VERSION") or "").strip()
    if aus_umgebung and aus_umgebung != "latest":
        return aus_umgebung
    try:
        return metadata.version("rechnungsblatt-web")
    except metadata.PackageNotFoundError:
        return "unbekannt"


def _stammzeile(stamm: dict, *schluessel: str) -> str:
    """Der erste gefuellte Wert — sonst eine Marke zum Ausfuellen."""
    for name in schluessel:
        wert = (stamm.get(name) or "").strip()
        if wert:
            return wert
    return "[ bitte ergänzen ]"


def _anschrift(stamm: dict) -> str:
    """Die Anschrift liegt verschachtelt unter ``anschrift``."""
    anschrift = stamm.get("anschrift") or {}
    teile = [
        (anschrift.get("strasse") or "").strip(),
        " ".join(t for t in ((anschrift.get("plz") or "").strip(),
                             (anschrift.get("ort") or "").strip()) if t),
    ]
    zeile = ", ".join(t for t in teile if t)
    return zeile or "[ bitte ergänzen ]"


def _belegstand(wurzel: Path) -> tuple[int, str]:
    """Wie viele Belege liegen da, und von welcher Nummer bis welcher.

    Die Zahl steht im Dokument, weil ein Pruefer sie mit dem Archiv
    abgleichen kann — eine Angabe, die sich pruefen laesst, wiegt mehr
    als eine, die man glauben muss.
    """
    basis = wurzel / "ablage"
    if not basis.is_dir():
        return 0, "Noch keine Rechnung ausgegeben."
    nummern = sorted(o.name for o in basis.iterdir() if o.is_dir())
    if not nummern:
        return 0, "Noch keine Rechnung ausgegeben."
    if len(nummern) == 1:
        return 1, f"Vergebene Nummer: {nummern[0]}"
    return len(nummern), f"Von {nummern[0]} bis {nummern[-1]}."


def _siegelstand(bericht: dict) -> str:
    """Das Ergebnis der Kettenpruefung als ein Satz.

    Steht im Dokument, weil eine Aussage, die zum Zeitpunkt der Ausgabe
    nachgerechnet wurde, mehr wiegt als eine allgemeine Zusicherung.
    """
    if not bericht["glieder"]:
        return "Noch keine Siegel vorhanden."
    if bericht["heil"]:
        satz = f"{bericht['glieder']} Siegel geprueft, Kette unversehrt."
    else:
        satz = (f"{bericht['glieder']} Siegel geprueft, "
                f"{len(bericht['befunde'])} Abweichung(en) - siehe Konto.")
    ohne = bericht.get("ohne_siegel") or []
    if ohne:
        satz += (f" {len(ohne)} Beleg(e) ohne Siegel (vor Einfuehrung der "
                 "Kette entstanden).")
    return satz


def erzeuge(wurzel: Path) -> str:
    """Der Entwurf als Text, mit den Stammdaten des Mandanten gefuellt."""
    stamm = lese_json(wurzel / "stamm.json") or {}
    anzahl, spanne = _belegstand(wurzel)
    bericht = siegel.pruefe(wurzel)
    werte = {
        "firma": _stammzeile(stamm, "firmierung"),
        "anschrift": _anschrift(stamm),
        "steuernummer": _stammzeile(stamm, "steuernummer"),
        "ustid": _stammzeile(stamm, "ust_idnr"),
        # Ob nach Paragraph 19 abgerechnet wird, aendert die ganze
        # Steuerdarstellung — das gehoert in die Beschreibung, nicht in
        # eine Fussnote.
        "steuerart": (
            "Kleinunternehmer nach Paragraph 19 UStG, kein Steuerausweis"
            if stamm.get("kleinunternehmer")
            else "Regelbesteuerung mit Steuerausweis"
        ),
        "stand": f"{dt.date.today():%d.%m.%Y}",
        "version": softwarestand(),
        "anzahl_belege": anzahl,
        "nummernspanne": spanne,
        "siegelstand": _siegelstand(bericht),
    }
    # format_map statt format: Ein unbekannter Platzhalter faellt so beim
    # Erzeugen auf und nicht erst im Dokument des Kunden.
    return CRLF.join(zeile.format_map(werte) for zeile in _VORLAGE) + CRLF
