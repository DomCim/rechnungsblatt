# -*- coding: utf-8 -*-
"""Schreibt impressum.html."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from gemeinsam import BETRIEB, huelle

INHALT = """
  <h2>Anbieter</h2>
  <address class="anschrift">
    <strong>{firma}</strong><br>
    {strasse}<br>
    {ort}<br>
    {land}
  </address>

  <h2>Kontakt</h2>
  <dl>
    <dt>E-Mail</dt>
    <dd><a href="mailto:{email}">{email}</a></dd>
    <dt>Weitere Adresse</dt>
    <dd><a href="mailto:{email_zweit}">{email_zweit}</a></dd>
  </dl>

  <h2>Verantwortlich f&uuml;r den Inhalt</h2>
  <p>Dominik Dill, Anschrift wie oben.</p>

  <h2>Umsatzsteuer</h2>
  <p>
    Kleinunternehmer nach &sect;&nbsp;19 UStG. Es wird keine Umsatzsteuer
    berechnet und daher keine ausgewiesen; eine
    Umsatzsteuer-Identifikationsnummer liegt nicht vor.
  </p>

  <h2>Streitbeilegung</h2>
  <p>
    Zur Teilnahme an einem Streitbeilegungsverfahren vor einer
    Verbraucherschlichtungsstelle ist der Anbieter nicht verpflichtet und
    nicht bereit.
  </p>

  <h2>Haftung f&uuml;r Verweise</h2>
  <p>
    Diese Seite verweist an einzelnen Stellen auf fremde Angebote. Auf deren
    Inhalte hat der Anbieter keinen Einfluss. Zum Zeitpunkt der Verkn&uuml;pfung
    waren keine Rechtsverst&ouml;&szlig;e erkennbar; wird einer bekannt, wird
    der Verweis entfernt.
  </p>

  <h2>Urheberrecht</h2>
  <p>
    Die Inhalte dieser Seite und die Software Rechnungsblatt sind urheberrechtlich
    gesch&uuml;tzt. Die mit Rechnungsblatt erzeugten Rechnungen geh&ouml;ren
    dagegen ausschlie&szlig;lich dem jeweiligen Nutzer &mdash; an ihnen werden
    keine Rechte beansprucht.
  </p>

  <p class="stand">
    Weitere Angaben: <a href="/datenschutz">Datenschutzerkl&auml;rung</a>
    &middot; <a href="/agb">Allgemeine Gesch&auml;ftsbedingungen</a>
  </p>
""".format(**BETRIEB)

ziel = pathlib.Path("web/src/rechnungsblatt_web/seiten/impressum.html")
ziel.write_text(
    huelle("Impressum",
           "impressum",
           "Anbieterangaben nach § 5 DDG für Rechnungsblatt: Betreiber, Anschrift und Kontakt. Betrieben von DiD0m — Dominik Dill in Naila.",
           INHALT),
    encoding="utf-8")
print(f"impressum.html: {len(ziel.read_text(encoding='utf-8').splitlines())} Zeilen")
