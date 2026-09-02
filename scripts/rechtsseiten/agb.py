# -*- coding: utf-8 -*-
"""Schreibt agb.html."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from gemeinsam import BETRIEB, huelle

INHALT = """
  <h2>1. Anbieter und Geltung</h2>
  <p>
    Diese Bedingungen gelten f&uuml;r die Nutzung der Anwendung
    Rechnungsblatt, angeboten von {firma}, {strasse}, {ort}
    (nachfolgend &bdquo;Anbieter&ldquo;).
  </p>
  <p>
    Abweichende Bedingungen des Nutzers gelten nur, wenn der Anbieter ihnen
    schriftlich zustimmt.
  </p>

  <h2>2. Gegenstand der Leistung</h2>
  <p>
    Rechnungsblatt erzeugt Rechnungen als PDF mit eingebetteter
    XML-Rechnung nach EN&nbsp;16931 (ZUGFeRD/Factur-X) sowie auf Wunsch als
    XRechnung. Die Belege entstehen auf dem Briefpapier des Nutzers und
    werden f&uuml;r ihn abgelegt.
  </p>
  <p>
    Der Anbieter pr&uuml;ft die erzeugten Rechnungen gegen die
    Pflichtangaben des &sect;&nbsp;14 UStG und die Regeln der EN&nbsp;16931.
    <strong>Diese Pr&uuml;fung ist technisch, nicht steuerlich.</strong> Ob
    ein Gesch&auml;ftsvorfall zutreffend erfasst, richtig bewertet und
    zutreffend besteuert ist, beurteilt allein der Nutzer &mdash;
    gegebenenfalls mit steuerlicher Beratung. Der Anbieter erbringt keine
    Steuerberatung und keine Rechtsberatung.
  </p>

  <h2>3. Konto</h2>
  <p>
    Die Nutzung setzt ein Konto voraus. Der Nutzer h&auml;lt seine
    Zugangsdaten geheim und die angegebene E-Mail-Adresse aktuell.
  </p>
  <p>
    <strong>Zugangsdaten k&ouml;nnen nicht wiederhergestellt werden.</strong>
    Die Daten des Nutzers liegen verschl&uuml;sselt; der Schl&uuml;ssel wird
    aus dem Kennwort abgeleitet und ist dem Anbieter nicht bekannt. Gehen
    Kennwort und Wiederherstellungscode verloren, ist der Zugang zu den
    abgelegten Daten endg&uuml;ltig verloren. Der Anbieter kann in diesem
    Fall nicht helfen; er weist hierauf ausdr&uuml;cklich hin.
  </p>
  <p>
    Der Anbieter kann die Freischaltung eines Kontos verweigern oder
    zur&uuml;cknehmen, wenn ein sachlicher Grund vorliegt &mdash;
    insbesondere bei missbr&auml;uchlicher Nutzung.
  </p>

  <h2>4. Verg&uuml;tung</h2>
  <p>
    Die jeweils geltenden Preise stehen auf der &ouml;ffentlichen Seite. Der
    Anbieter ist Kleinunternehmer nach &sect;&nbsp;19 UStG; die Preise
    enthalten keine Umsatzsteuer, und es wird keine ausgewiesen.
  </p>

  <h3>Guthaben</h3>
  <p>
    Guthaben wird im Voraus erworben und mit den erzeugten Rechnungen
    verbraucht. Es verf&auml;llt nicht und wird nicht verzinst.
  </p>
  <p>
    <strong>Eine Auszahlung nicht verbrauchten Guthabens erfolgt
    nicht.</strong> Das gilt auch, wenn der Nutzer den Vertrag beendet
    oder die Anwendung nicht mehr verwendet, und ebenso, wenn der
    Anbieter das Konto aus einem Grund im Verhalten des Nutzers sperrt.
  </p>
  <p>
    Stellt der Anbieter die Anwendung ein, k&uuml;ndigt er dies
    mindestens drei Monate vorher an. Der Nutzer kann sein Guthaben
    innerhalb dieser Frist aufbrauchen. Guthaben, das danach noch
    besteht, wird auf Verlangen erstattet.
  </p>

  <h3>Abonnement</h3>
  <p>
    Ein Abonnement l&auml;uft monatlich und verl&auml;ngert sich jeweils um
    einen Monat, wenn es nicht vorher gek&uuml;ndigt wird. Die K&uuml;ndigung
    ist jederzeit zum Ende des laufenden Abrechnungszeitraums m&ouml;glich,
    im Konto unter &bdquo;Zahlungen verwalten&ldquo;. Bereits gezahlte
    Beitr&auml;ge f&uuml;r den laufenden Zeitraum werden nicht anteilig
    erstattet; die Leistung steht bis zum Ende des Zeitraums zur
    Verf&uuml;gung.
  </p>

  <h2>5. Widerrufsrecht f&uuml;r Verbraucher</h2>
  <p>
    Verbrauchern steht ein Widerrufsrecht von vierzehn Tagen zu
    (&sect;&nbsp;355 BGB). Die Frist beginnt mit Vertragsschluss.
  </p>
  <p>
    Der Widerruf ist in Textform an
    <a href="mailto:{email}">{email}</a> zu richten. Eine Begr&uuml;ndung ist
    nicht erforderlich.
  </p>
  <p>
    <strong>Erl&ouml;schen des Widerrufsrechts:</strong> Bei digitalen
    Inhalten erlischt das Widerrufsrecht, wenn der Anbieter mit der
    Ausf&uuml;hrung begonnen hat, nachdem der Verbraucher ausdr&uuml;cklich
    zugestimmt und best&auml;tigt hat, dass er sein Widerrufsrecht damit
    verliert (&sect;&nbsp;356 Abs.&nbsp;5 BGB). Wer vor Ablauf der Frist eine
    Rechnung erzeugt, veranlasst diese Ausf&uuml;hrung.
  </p>
  <p>
    Gegen&uuml;ber Unternehmern besteht kein Widerrufsrecht.
  </p>

  <h2>6. Verf&uuml;gbarkeit</h2>
  <p>
    Der Anbieter bem&uuml;ht sich um einen st&ouml;rungsfreien Betrieb,
    schuldet aber <strong>keine bestimmte Verf&uuml;gbarkeit</strong>.
    Wartungsarbeiten, St&ouml;rungen bei Vorleistern und Ma&szlig;nahmen zur
    Abwehr von Angriffen k&ouml;nnen zu Unterbrechungen f&uuml;hren.
  </p>
  <p>
    Der Anbieter kann den Leistungsumfang &auml;ndern oder einzelne
    Funktionen einstellen, wenn ein sachlicher Grund vorliegt. Wesentliche
    Einschr&auml;nkungen werden mit angemessener Frist angek&uuml;ndigt.
  </p>

  <h2>7. Pflichten des Nutzers</h2>
  <ul>
    <li>
      Die Richtigkeit der eingegebenen Daten pr&uuml;fen &mdash; insbesondere
      Betr&auml;ge, Steuers&auml;tze und Empf&auml;ngerangaben. Die
      Vorschau zeigt den Beleg vor dem Erzeugen.
    </li>
    <li>
      Eigene steuerliche und handelsrechtliche Pflichten erf&uuml;llen,
      einschlie&szlig;lich Aufbewahrung und Verfahrensdokumentation.
    </li>
    <li>
      Keine rechtswidrigen Inhalte einstellen und die Anwendung nicht
      &uuml;berm&auml;&szlig;ig automatisiert abrufen.
    </li>
    <li>
      Bei der Verarbeitung von Empf&auml;ngerdaten die eigenen
      datenschutzrechtlichen Pflichten beachten.
    </li>
  </ul>

  <h2>8. Aufbewahrung und Datenexport</h2>
  <p>
    <strong>Die Aufbewahrungspflicht trifft den Nutzer.</strong> Wer eine
    Rechnung ausstellt, hat ein Doppel acht Jahre aufzubewahren
    (&sect;&nbsp;147 Abs.&nbsp;3 AO, &sect;&nbsp;14b Abs.&nbsp;1 UStG).
    Das ist seine steuerliche Pflicht; der Anbieter erf&uuml;llt sie nicht
    f&uuml;r ihn und schuldet keine Archivierung f&uuml;r diesen
    Zeitraum.
  </p>
  <p>
    Solange der Vertrag l&auml;uft, bleiben die erzeugten Belege im Konto
    abrufbar. Sie lassen sich jederzeit vollst&auml;ndig herunterladen
    &mdash; Konto &rarr; F&uuml;r die Betriebspr&uuml;fung liefert alle
    Belege eines Zeitraums als ZIP, mit PDF, XML und einer
    &Uuml;bersichtstabelle. <strong>Der Nutzer sollte das regelm&auml;&szlig;ig
    tun</strong>, damit seine Unterlagen unabh&auml;ngig von diesem Dienst
    vorliegen.
  </p>
  <p>
    Ein Weg zum L&ouml;schen einzelner Belege besteht nicht, und eine
    vergebene Rechnungsnummer wird nicht erneut verwendet &mdash; beides
    folgt aus der Unver&auml;nderbarkeit, die das Steuerrecht verlangt.
  </p>
  <p>
    <strong>Nach Vertragsende bleiben die Belege sechs Monate
    abrufbar.</strong> Endet der Vertrag, weil der Anbieter die Anwendung
    einstellt, gilt zus&auml;tzlich die Ank&uuml;ndigungsfrist aus
    Ziffer&nbsp;4. Danach werden die Daten gel&ouml;scht; der Nutzer
    hat sie bis dahin zu sichern.
  </p>

  <h2>9. Haftung</h2>
  <p>
    Der Anbieter haftet unbeschr&auml;nkt bei Vorsatz und grober
    F&auml;hrlichkeit, bei Verletzung von Leben, K&ouml;rper oder Gesundheit
    sowie nach dem Produkthaftungsgesetz.
  </p>
  <p>
    Bei leicht fahrl&auml;ssiger Verletzung einer wesentlichen
    Vertragspflicht haftet er auf den vorhersehbaren, vertragstypischen
    Schaden. Im &Uuml;brigen ist die Haftung ausgeschlossen.
  </p>
  <p>
    <strong>Nicht &uuml;bernommen wird die Haftung f&uuml;r steuerliche
    Folgen</strong> unrichtiger oder unvollst&auml;ndiger Angaben des
    Nutzers &mdash; auch dann nicht, wenn die technische Pr&uuml;fung sie
    nicht beanstandet hat. Die Pr&uuml;fung erfasst formale Anforderungen,
    nicht die inhaltliche Richtigkeit eines Gesch&auml;ftsvorfalls.
  </p>
  <p>
    Der Nutzer sichert seine Daten selbst, indem er sie herunterl&auml;dt.
    F&uuml;r Datenverlust haftet der Anbieter nur nach den vorstehenden
    Ma&szlig;st&auml;ben.
  </p>

  <h2>10. Vertragsdauer und Beendigung</h2>
  <p>
    Der Nutzungsvertrag l&auml;uft auf unbestimmte Zeit. Beide Seiten
    k&ouml;nnen ihn jederzeit ohne Frist beenden; f&uuml;r Abonnements gilt
    zus&auml;tzlich Ziffer&nbsp;4.
  </p>
  <p>
    Das Recht zur K&uuml;ndigung aus wichtigem Grund bleibt unber&uuml;hrt.
  </p>

  <h2>11. &Auml;nderungen dieser Bedingungen</h2>
  <p>
    Der Anbieter kann diese Bedingungen mit Wirkung f&uuml;r die Zukunft
    &auml;ndern, wenn ein sachlicher Grund vorliegt. &Auml;nderungen werden
    mindestens sechs Wochen vorher per E-Mail angek&uuml;ndigt. Widerspricht
    der Nutzer nicht bis zum Wirksamwerden, gelten sie als angenommen;
    hierauf wird in der Ank&uuml;ndigung hingewiesen. Der Nutzer kann in
    diesem Fall bis zum Wirksamwerden k&uuml;ndigen.
  </p>

  <h2>12. Schlussbestimmungen</h2>
  <p>
    Es gilt deutsches Recht. Gegen&uuml;ber Verbrauchern bleiben zwingende
    Schutzvorschriften ihres Aufenthaltsstaats unber&uuml;hrt.
  </p>
  <p>
    Ist der Nutzer Kaufmann, juristische Person des &ouml;ffentlichen Rechts
    oder &ouml;ffentlich-rechtliches Sonderverm&ouml;gen, ist Gerichtsstand
    der Sitz des Anbieters.
  </p>
  <p>
    Sollte eine Bestimmung unwirksam sein, bleibt der &uuml;brige Vertrag
    wirksam.
  </p>

  <p class="stand">
    Stand: {stand}. Weitere Angaben:
    <a href="/impressum">Impressum</a> &middot;
    <a href="/datenschutz">Datenschutzerkl&auml;rung</a>
  </p>
""".format(stand="September 2026", **BETRIEB)

ziel = pathlib.Path("web/src/rechnungsblatt_web/seiten/agb.html")
ziel.write_text(
    huelle("Allgemeine Gesch&auml;ftsbedingungen",
           "agb",
           "Nutzungsbedingungen für Rechnungsblatt: Leistungsumfang, Guthaben und Abo, Widerruf, Haftung und Aufbewahrung der erzeugten Belege.",
           INHALT),
    encoding="utf-8")
print("agb.html:", len(ziel.read_text(encoding="utf-8").splitlines()), "Zeilen")
