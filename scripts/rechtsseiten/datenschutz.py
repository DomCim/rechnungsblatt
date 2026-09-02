# -*- coding: utf-8 -*-
"""Schreibt datenschutz.html — aus dem, was die Anwendung wirklich tut."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from gemeinsam import BETRIEB, huelle

INHALT = """
  <p>
    Diese Erkl&auml;rung beschreibt, welche Daten bei der Nutzung von
    Rechnungsblatt anfallen, wozu sie verarbeitet werden und wie lange sie
    bleiben.
  </p>

  <h2>1. Verantwortlicher</h2>
  <address class="anschrift">
    <strong>{firma}</strong><br>
    {strasse}<br>
    {ort}<br>
    E-Mail: <a href="mailto:{email}">{email}</a>
  </address>
  <p>
    Ein Datenschutzbeauftragter ist nicht zu benennen: Der Betrieb
    besch&auml;ftigt nicht mehr als zwanzig Personen mit der Verarbeitung
    (&sect;&nbsp;38 BDSG).
  </p>

  <h2>2. Was beim Aufruf der Seite anf&auml;llt</h2>
  <p>
    Der Server verarbeitet die Angaben, die jeder Browser beim Abruf
    &uuml;bermittelt &mdash; darunter IP-Adresse, Zeitpunkt, aufgerufene
    Adresse und Browserkennung. Sie sind technisch notwendig, um die Seite
    ausliefern zu k&ouml;nnen.
  </p>
  <p>
    <strong>Rechtsgrundlage:</strong> Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;f
    DSGVO &mdash; berechtigtes Interesse am Betrieb und an der Sicherheit
    des Angebots.
  </p>

  <h2>3. Konto</h2>
  <p>Zu einem Konto werden gespeichert:</p>
  <table>
    <tr><th>Angabe</th><th>Wozu</th></tr>
    <tr><td>E-Mail-Adresse</td><td>Anmeldung, Best&auml;tigungscode, Kennwort zur&uuml;cksetzen</td></tr>
    <tr><td>Kennwort</td><td>nur als Hashwert &mdash; im Klartext liegt es nirgends</td></tr>
    <tr><td>Zeitpunkte</td><td>Anlegen, Freischalten, letzte Anmeldung, Best&auml;tigung</td></tr>
    <tr><td>Tarif und Guthaben</td><td>Abrechnung der erzeugten Rechnungen</td></tr>
  </table>
  <p>
    <strong>Rechtsgrundlage:</strong> Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;b
    DSGVO &mdash; Erf&uuml;llung des Nutzungsvertrags.
  </p>

  <h3>Anmeldung</h3>
  <p>
    Eine Anmeldung setzt ein technisch notwendiges Cookie
    (<span class="kennung">rb_sitzung</span>). Es enth&auml;lt nur einen
    Zufallswert, keine Inhalte, gilt {sitzung} Tage und wird beim Abmelden
    ung&uuml;ltig. Ohne dieses Cookie ist eine Anmeldung nicht m&ouml;glich;
    eine Einwilligung ist daf&uuml;r nicht erforderlich
    (&sect;&nbsp;25 Abs.&nbsp;2 Nr.&nbsp;2 TDDDG).
  </p>

  <h2>4. Rechnungsdaten &mdash; verschl&uuml;sselt</h2>
  <p>
    Die eingegebenen Rechnungsdaten, das Briefpapier und die erzeugten Belege
    liegen <strong>verschl&uuml;sselt</strong> auf dem Server. Der
    Schl&uuml;ssel wird beim Anmelden aus dem Kennwort abgeleitet und nur
    f&uuml;r die Dauer der Sitzung gehalten; gespeichert wird er nicht.
  </p>
  <p>
    <strong>Das hat eine Folge, die ausdr&uuml;cklich genannt sei:</strong>
    Der Anbieter kann die Rechnungen nicht einsehen &mdash; auch nicht auf
    Bitte des Nutzers. Wer Kennwort und Wiederherstellungscode verliert,
    verliert den Zugang zu den Daten endg&uuml;ltig. Das ist der Preis
    daf&uuml;r, dass niemand sonst hineinsehen kann.
  </p>
  <p>
    Die Empf&auml;ngerdaten in den Rechnungen verarbeitet der Nutzer als
    Verantwortlicher; der Anbieter ist insoweit Auftragsverarbeiter
    (Art.&nbsp;28 DSGVO). Ein Vertrag zur Auftragsverarbeitung wird auf
    Anfrage gestellt.
  </p>

  <h2>5. Aufbewahrung</h2>
  <table>
    <tr><th>Daten</th><th>Dauer</th></tr>
    <tr><td>Erzeugte Rechnungen</td><td>solange das Konto besteht, danach sechs Monate. <strong>Die achtj&auml;hrige Aufbewahrungspflicht (&sect;&nbsp;147 Abs.&nbsp;3 AO, &sect;&nbsp;14b Abs.&nbsp;1 UStG) trifft den Nutzer</strong> &mdash; er erf&uuml;llt sie durch den Export</td></tr>
    <tr><td>Belege &uuml;ber Zahlungen an den Anbieter</td><td>acht Jahre &mdash; hier ist der Anbieter selbst der Aussteller und aufbewahrungspflichtig</td></tr>
    <tr><td>Konto</td><td>bis zur L&ouml;schung, danach nur was aufbewahrungspflichtig ist</td></tr>
    <tr><td>Sitzungen</td><td>{sitzung} Tage, dann automatisch entfernt</td></tr>
  </table>
  <p>
    <strong>Rechnungen lassen sich nicht l&ouml;schen</strong>, auch nicht auf
    Wunsch: Sie unterliegen der Aufbewahrungspflicht, und eine vergebene
    Rechnungsnummer darf nicht erneut verwendet werden. Das ist keine
    Bequemlichkeit des Anbieters, sondern eine Anforderung des Steuerrechts.
  </p>
  <p>
    Am Ende des Vertrags werden die Daten gel&ouml;scht &mdash; nach einer
    Frist von sechs Monaten, in der sie noch abrufbar bleiben. <strong>Bis
    dahin sollte der Nutzer seine Belege gesichert haben</strong>, denn
    seine eigene Aufbewahrungspflicht l&auml;uft danach weiter.
  </p>

  <h2>6. Zahlungen &uuml;ber Stripe</h2>
  <p>
    F&uuml;r Zahlungen wird Stripe eingesetzt (Stripe Payments Europe, Ltd.,
    Dublin, Irland). Beim Bezahlen werden E-Mail-Adresse, Betrag und eine
    Kundenkennung an Stripe &uuml;bermittelt.
  </p>
  <p>
    <strong>Kartendaten erreichen diesen Server nie.</strong> Sie werden
    ausschlie&szlig;lich bei Stripe eingegeben und dort verarbeitet.
    Gespeichert werden hier nur die Stripe-Kundennummer, die Abo-Kennung und
    die Betr&auml;ge &mdash; keine Karten- oder Kontodaten.
  </p>
  <p>
    <strong>Rechtsgrundlage:</strong> Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;b
    DSGVO. Stripes eigene Angaben:
    <a href="https://stripe.com/de/privacy" target="_blank" rel="noopener">stripe.com/de/privacy</a>.
  </p>

  <h2>7. Besucherz&auml;hlung</h2>
  <p>
    Die Seitenaufrufe werden mit Plausible gez&auml;hlt &mdash; einer
    selbst betriebenen Software auf demselben Server.
    <strong>Ohne Cookies und ohne Wiedererkennung.</strong> Aus IP-Adresse
    und Browserkennung wird mit einem t&auml;glich wechselnden Zusatzwert ein
    Kennzeichen gebildet, das nicht gespeichert wird; &uuml;ber den Tag
    hinaus l&auml;sst sich niemand wiedererkennen.
  </p>
  <p>
    Es werden keine Daten an Dritte &uuml;bertragen und keine Profile
    gebildet. Deshalb gibt es hier keinen Einwilligungsbanner &mdash; es gibt
    nichts einzuwilligen.
  </p>
  <p>
    <strong>Rechtsgrundlage:</strong> Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;f
    DSGVO &mdash; berechtigtes Interesse an einer Reichweitenmessung ohne
    Personenbezug.
  </p>

  <h2>8. Keine fremden Dienste in der Seite</h2>
  <p>
    Schriften, Stilvorlagen und Skripte werden vom eigenen Server
    ausgeliefert. Es werden <strong>keine</strong> externen Dienste
    eingebunden &mdash; insbesondere keine Google Fonts, keine
    Auslieferungsnetze, keine sozialen Netzwerke, keine Werbenetzwerke. Beim
    Aufruf der Seite entsteht damit keine Verbindung zu Dritten.
  </p>

  <h2>9. E-Mails</h2>
  <p>
    Best&auml;tigungscodes und Links zum Zur&uuml;cksetzen des Kennworts
    werden &uuml;ber einen Mailanbieter versendet, der die
    &uuml;bermittelten Adressen dabei verarbeitet. Ein Newsletter wird nicht
    versendet.
  </p>

  <h2>10. Ihre Rechte</h2>
  <ul>
    <li>Auskunft &uuml;ber die gespeicherten Daten (Art.&nbsp;15 DSGVO)</li>
    <li>Berichtigung unrichtiger Daten (Art.&nbsp;16)</li>
    <li>L&ouml;schung, soweit keine Aufbewahrungspflicht entgegensteht (Art.&nbsp;17)</li>
    <li>Einschr&auml;nkung der Verarbeitung (Art.&nbsp;18)</li>
    <li>Daten&uuml;bertragbarkeit (Art.&nbsp;20)</li>
    <li>Widerspruch gegen Verarbeitungen auf Grundlage von lit.&nbsp;f (Art.&nbsp;21)</li>
  </ul>
  <p>
    Eine Nachricht an <a href="mailto:{email}">{email}</a> gen&uuml;gt.
    Die Belege eines Kontos lassen sich zudem jederzeit selbst am
    St&uuml;ck herunterladen (Konto &rarr; F&uuml;r die Betriebspr&uuml;fung)
    &mdash; das erf&uuml;llt Art.&nbsp;20 ohne Umweg.
  </p>

  <h2>11. Beschwerderecht</h2>
  <p>
    Es besteht das Recht, sich bei einer Aufsichtsbeh&ouml;rde zu beschweren.
    Zust&auml;ndig ist das Bayerische Landesamt f&uuml;r Datenschutzaufsicht,
    Promenade 18, 91522 Ansbach.
  </p>

  <p class="stand">
    Stand: {stand}. Weitere Angaben:
    <a href="/impressum">Impressum</a> &middot;
    <a href="/agb">Allgemeine Gesch&auml;ftsbedingungen</a>
  </p>
""".format(sitzung=30, stand="September 2026", **BETRIEB)

ziel = pathlib.Path("web/src/rechnungsblatt_web/seiten/datenschutz.html")
ziel.write_text(
    huelle("Datenschutz",
           "datenschutz",
           "Welche Daten Rechnungsblatt verarbeitet, wozu und wie lange: Konto, verschlüsselte Belege, Zahlungen über Stripe, Zählung ohne Cookies.",
           INHALT),
    encoding="utf-8")
print("datenschutz.html:", len(ziel.read_text(encoding="utf-8").splitlines()), "Zeilen")
