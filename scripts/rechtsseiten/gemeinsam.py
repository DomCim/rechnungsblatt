# -*- coding: utf-8 -*-
"""Gemeinsame Huelle der Rechtsseiten.

Sie sind bewusst schlicht: kein Skript, keine Anmeldung, keine
Uebersetzung. Ein Impressum muss ohne Umwege erreichbar sein — auch wenn
sonst etwas klemmt.
"""

BETRIEB = {
    "firma": "DiD0m &mdash; Dominik Dill",
    "strasse": "Goldammerweg 25",
    "ort": "95119 Naila",
    "land": "Deutschland",
    "email": "d.dill@rechnungsblatt.de",
    "email_zweit": "d.dill@did0m.dev",
}


def huelle(titel: str, pfad: str, beschreibung: str, inhalt: str) -> str:
    """Eine Rechtsseite als vollstaendiges HTML.

    ``pfad`` getrennt vom Titel: Der Titel darf HTML-Entities tragen
    (&auml;), eine Adresse nicht.

    ``beschreibung`` sollte 70 bis 155 Zeichen haben. Bing meldet
    kuerzere als "too short" und laengere als "too long"; die drei
    Rechtsseiten lagen zuerst bei 39 bis 60.
    """
    return f"""<!doctype html>
<html lang="de" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{titel} &mdash; Rechnungsblatt</title>
<meta name="description" content="{beschreibung}">
<link rel="canonical" href="/{pfad}">
<link rel="stylesheet" href="/seiten/schriften/schriften.css">
<link rel="stylesheet" href="/seiten/basis.css">
<link rel="icon" href="/seiten/symbole/favicon.ico" sizes="any">
<style>
  /* Ein Rechtstext wird gelesen, nicht durchgeblättert: schmales Maß,
     ruhiger Zeilenabstand, keine Effekte. */
  .rechtsseite {{
    max-width: 68ch;
    margin: 0 auto;
    padding: calc(28px + env(safe-area-inset-top, 0px))
             calc(22px + env(safe-area-inset-right, 0px))
             80px
             calc(22px + env(safe-area-inset-left, 0px));
  }}
  .rechtsseite .marke {{
    font-family: "Fraunces", "Fraunces Ersatz", Georgia, serif;
    font-variation-settings: "opsz" 40;
    font-size: 15px;
    letter-spacing: 0.01em;
  }}
  .rechtsseite h1 {{
    font-size: clamp(26px, 6vw, 38px);
    margin: 6px 0 26px;
  }}
  .rechtsseite h2 {{
    font-size: clamp(17px, 3.4vw, 21px);
    margin: 34px 0 10px;
  }}
  .rechtsseite h3 {{
    font-size: 15.5px;
    margin: 22px 0 6px;
    color: var(--tinte);
  }}
  .rechtsseite p,
  .rechtsseite li {{
    color: var(--tinte-2);
    line-height: 1.62;
    font-size: 14.5px;
  }}
  .rechtsseite ul, .rechtsseite ol {{ padding-left: 20px; margin: 8px 0; }}
  .rechtsseite li {{ margin-bottom: 5px; }}
  .rechtsseite dl {{ margin: 8px 0; }}
  .rechtsseite dt {{
    font-weight: 600;
    color: var(--tinte);
    font-size: 13px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    margin-top: 14px;
  }}
  .rechtsseite dd {{
    margin: 2px 0 0;
    color: var(--tinte-2);
    line-height: 1.6;
    font-size: 14.5px;
  }}
  .rechtsseite a {{ color: var(--akzent-tinte); }}
  .rechtsseite .anschrift {{
    font-style: normal;
    color: var(--tinte-2);
    line-height: 1.62;
    font-size: 14.5px;
  }}
  .rechtsseite .stand {{
    margin-top: 46px;
    padding-top: 16px;
    border-top: 1px solid var(--kante);
    font-size: 13px;
  }}
  .rechtsseite .zurueck {{ margin-top: 30px; }}
  /* Tabellen in Rechtstexten: Verantwortlichkeiten, Fristen. */
  .rechtsseite table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 14px;
  }}
  .rechtsseite th, .rechtsseite td {{
    text-align: left;
    padding: 8px 10px;
    border-bottom: 1px solid var(--kante);
    vertical-align: top;
    color: var(--tinte-2);
  }}
  .rechtsseite th {{ color: var(--tinte); font-weight: 600; }}
</style>
</head>
<body>
<main class="rechtsseite">
  <div class="marke">Rechnungsblatt</div>
  <h1>{titel}</h1>
{inhalt}
  <div class="zurueck">
    <a class="knopf leise" href="/">Zur Startseite</a>
  </div>
</main>
</body>
</html>
"""
