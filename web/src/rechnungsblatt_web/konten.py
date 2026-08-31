"""Konten, Sitzungen und Tarife — die Mandantenschicht über PostgreSQL.

Der Kern kennt keine Nutzer, und die Seiten kennen kein SQL. Alles, was mit
Anmeldung, Freigabe, Rolle und Kontingent zu tun hat, liegt hier.

Passwörter werden mit scrypt aus der Standardbibliothek gehasht — das
erspart eine weitere Abhängigkeit und ist für den Zweck ausreichend.
Sitzungsschlüssel liegen nur als SHA-256 in der Datenbank: Wer die
Datenbank liest, kann sich damit nicht anmelden.

Die Nutzdaten einer Rechnung (Briefpapier, Stammdaten, Ablage) liegen
weiterhin als Dateien je Mandant im Datenverzeichnis — hier steht nur, wem
welches Verzeichnis gehört und was er darf.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import tresor

DATENBANK_URL = os.environ.get(
    "DATENBANK_URL",
    "postgresql://rechnungsblatt:rechnungsblatt@datenbank:5432/rechnungsblatt",
)

SITZUNG_TAGE = int(os.environ.get("SITZUNG_TAGE", "30"))

# scrypt-Parameter (RFC 7914). n=2^14 braucht rund 16 MB je Prüfung — genug
# Härte gegen Wörterbuchangriffe, ohne die Anmeldung spürbar zu bremsen.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

MINDESTLAENGE_PASSWORT = 10

# Rollen und Kontostatus
ROLLE_KUNDE = "kunde"
ROLLE_ADMIN = "admin"
STATUS_WARTET = "wartet"
STATUS_FREI = "frei"
STATUS_GESPERRT = "gesperrt"

_EMAIL_MUSTER = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


class KontoFehler(Exception):
    """Fachlicher Fehler der Kontenschicht (Meldung ist für Nutzer bestimmt)."""


class KontingentErschoepft(KontoFehler):
    """Inklusivmenge aufgebraucht und kein Guthaben für eine weitere Rechnung."""


# ---------------------------------------------------------------- Modelle

@dataclasses.dataclass(frozen=True)
class Tarif:
    schluessel: str
    name: str
    beschreibung: str
    monatsbeitrag_cent: int
    inklusiv_rechnungen: int | None  # None = unbegrenzt
    preis_je_rechnung_cent: int
    reihenfolge: int
    sichtbar: bool
    # Vorgabe False: kein hervorgehobener Tarif ist ein gültiger Zustand,
    # keine Ausnahme. Damit bleiben auch die Standardtarife unverändert.
    hervorheben: bool = False
    # Die Stripe-Preis-ID des Abos, leer bei Tarifen ohne Abo. Sie gehört
    # zum Tarif und nicht in eine globale Einstellung: Es gibt mehr als
    # einen Abo-Tarif, und jeder braucht seinen eigenen Preis bei Stripe.
    stripe_preis: str = ""


@dataclasses.dataclass(frozen=True)
class Nutzer:
    id: int
    email: str
    rolle: str
    status: str
    tarif: str
    guthaben_cent: int
    passwort_wechseln: bool
    angelegt: dt.datetime
    zuletzt_angemeldet: dt.datetime | None
    # NULL, solange die Adresse nicht per Code bestätigt wurde.
    email_bestaetigt: dt.datetime | None = None

    @property
    def ist_admin(self) -> bool:
        return self.rolle == ROLLE_ADMIN

    @property
    def ist_frei(self) -> bool:
        return self.status == STATUS_FREI

    @property
    def ist_bestaetigt(self) -> bool:
        return self.email_bestaetigt is not None


@dataclasses.dataclass(frozen=True)
class Kontingent:
    """Was der Nutzer diesen Monat schon verbraucht hat und noch darf."""

    tarif: Tarif
    verbraucht: int
    inklusiv: int | None
    guthaben_cent: int

    @property
    def frei_uebrig(self) -> int | None:
        if self.inklusiv is None:
            return None
        return max(0, self.inklusiv - self.verbraucht)

    @property
    def naechste_kostet_cent(self) -> int:
        if self.inklusiv is None or self.verbraucht < self.inklusiv:
            return 0
        return self.tarif.preis_je_rechnung_cent

    @property
    def darf_erzeugen(self) -> bool:
        kosten = self.naechste_kostet_cent
        return kosten == 0 or self.guthaben_cent >= kosten


# ---------------------------------------------------------------- Verbindung

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATENBANK_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row}
        )
    return _pool


def schliesse_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def verbindung() -> Iterator[psycopg.Connection]:
    """Verbindung aus dem Pool; committet am Ende des Blocks."""
    return pool().connection()


# ---------------------------------------------------------------- Schema

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tarife (
    schluessel             TEXT PRIMARY KEY,
    name                   TEXT NOT NULL,
    beschreibung           TEXT NOT NULL DEFAULT '',
    monatsbeitrag_cent     INTEGER NOT NULL DEFAULT 0,
    inklusiv_rechnungen    INTEGER,
    preis_je_rechnung_cent INTEGER NOT NULL DEFAULT 0,
    reihenfolge            INTEGER NOT NULL DEFAULT 0,
    sichtbar               BOOLEAN NOT NULL DEFAULT TRUE,
    -- Hebt die öffentliche Preistafel diesen Tarif hervor? Bewusst ein
    -- Datensatz und keine Regel im Code: welcher Tarif empfohlen wird, ist
    -- eine Entscheidung des Betreibers und ändert sich ohne Neubau.
    hervorheben            BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_preis           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS nutzer (
    id                 BIGSERIAL PRIMARY KEY,
    email              TEXT NOT NULL UNIQUE,
    passwort_hash      TEXT NOT NULL,
    rolle              TEXT NOT NULL DEFAULT 'kunde',
    status             TEXT NOT NULL DEFAULT 'wartet',
    tarif              TEXT NOT NULL REFERENCES tarife(schluessel),
    guthaben_cent      INTEGER NOT NULL DEFAULT 0,
    passwort_wechseln  BOOLEAN NOT NULL DEFAULT FALSE,
    angelegt           TIMESTAMPTZ NOT NULL DEFAULT now(),
    freigegeben        TIMESTAMPTZ,
    zuletzt_angemeldet TIMESTAMPTZ,
    -- Die beiden Hüllen um den Datenschlüssel (siehe tresor.py). Der
    -- Schlüssel selbst steht NIRGENDS in der Datenbank.
    huelle_passwort    BYTEA,
    huelle_code        BYTEA,
    -- Wann die Adresse per Code bestätigt wurde. NULL = noch offen.
    -- Getrennt vom Status: Bestätigung macht der Kunde, Freigabe der Admin.
    email_bestaetigt   TIMESTAMPTZ,
    -- Blind Index über USt-IdNr. bzw. Steuernummer: erlaubt den Vergleich
    -- zweier Konten, ohne die Nummer lesbar abzulegen. Die Nummer selbst
    -- steht verschlüsselt in den Stammdaten des Mandanten.
    steuer_index       TEXT,
    -- Stripe-Kunde und laufendes Abo. Nur Fremdschlüssel, keine
    -- Zahlungsdaten — die liegen bei Stripe.
    stripe_kunde       TEXT,
    stripe_abo         TEXT
);

CREATE TABLE IF NOT EXISTS sitzungen (
    kennung   TEXT PRIMARY KEY,
    nutzer    BIGINT NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
    angelegt  TIMESTAMPTZ NOT NULL DEFAULT now(),
    laeuft_ab TIMESTAMPTZ NOT NULL,
    -- Der Datenschlüssel, verschlüsselt mit dem Sitzungsschlüssel, den nur
    -- der Browser hat (hier steht davon nur der SHA-256 in `kennung`).
    -- Ohne das Cookie ist dieser Eintrag wertlos.
    schluessel BYTEA
);
CREATE INDEX IF NOT EXISTS sitzungen_nutzer ON sitzungen (nutzer);

CREATE TABLE IF NOT EXISTS verbrauch (
    id          BIGSERIAL PRIMARY KEY,
    nutzer      BIGINT NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
    nummer      TEXT NOT NULL,
    kosten_cent INTEGER NOT NULL DEFAULT 0,
    zeitpunkt   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS verbrauch_nutzer_zeit ON verbrauch (nutzer, zeitpunkt);

-- Betriebseinstellungen, im Adminbereich pflegbar (SMTP-Zugang).
-- Bewusst als Datensatz statt als Stack-Variable: so lässt sich der
-- Postausgang ändern, ohne den Stack neu zu deployen.
CREATE TABLE IF NOT EXISTS einstellungen (
    schluessel TEXT PRIMARY KEY,
    wert       TEXT NOT NULL DEFAULT '',
    -- Geheimnisse (SMTP-Passwort) liegen verschlüsselt; siehe tresor.
    geheim     BOOLEAN NOT NULL DEFAULT FALSE
);

-- Einmalige Nachweise: E-Mail bestätigen (6-stelliger Code) und Passwort
-- zurücksetzen (langer Link-Anteil). Beide laufen ab, beide werden nach
-- Gebrauch gelöscht. Gespeichert wird nur der SHA-256 — wer die
-- Datenbank liest, kann damit nichts anfangen.
CREATE TABLE IF NOT EXISTS nachweise (
    kennung    TEXT PRIMARY KEY,
    nutzer     BIGINT NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
    zweck      TEXT NOT NULL,
    versuche   INTEGER NOT NULL DEFAULT 0,
    angelegt   TIMESTAMPTZ NOT NULL DEFAULT now(),
    laeuft_ab  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS nachweise_nutzer ON nachweise (nutzer, zweck);

-- Verbuchte Zahlungen. Der Fremdschluessel von Stripe ist eindeutig:
-- Webhooks kommen laut Stripe MEHRFACH an, und ohne diese Sperre buchte
-- dieselbe Zahlung zweimal Guthaben.
CREATE TABLE IF NOT EXISTS zahlungen (
    stripe_id  TEXT PRIMARY KEY,
    nutzer     BIGINT NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
    art        TEXT NOT NULL,
    betrag_cent INTEGER NOT NULL DEFAULT 0,
    zeitpunkt  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS zahlungen_nutzer ON zahlungen (nutzer, zeitpunkt);
"""

# Nachträgliche Spalten.
#
# Das Schema oben stellt nur her, was NOCH NICHT da ist — auf einer
# bestehenden Datenbank überspringt `CREATE TABLE IF NOT EXISTS` die
# Tabelle samt aller später hinzugekommenen Spalten. Ohne diesen Block
# fehlte eine neue Spalte dort still, und erst der nächste Zugriff bräche.
#
# Wer eine Spalte ergänzt, trägt sie deshalb an BEIDEN Stellen ein: oben
# ins CREATE TABLE (für neue Datenbanken) und hier (für bestehende).
# Beides ist idempotent und läuft bei jedem Start mit.
_NACHTRAEGE = """
ALTER TABLE tarife ADD COLUMN IF NOT EXISTS
    hervorheben BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tarife ADD COLUMN IF NOT EXISTS
    stripe_preis TEXT NOT NULL DEFAULT '';
ALTER TABLE nutzer ADD COLUMN IF NOT EXISTS huelle_passwort BYTEA;
ALTER TABLE nutzer ADD COLUMN IF NOT EXISTS huelle_code     BYTEA;
ALTER TABLE sitzungen ADD COLUMN IF NOT EXISTS schluessel   BYTEA;
ALTER TABLE nutzer ADD COLUMN IF NOT EXISTS steuer_index TEXT;
-- Der Stripe-Kunde, damit ein Wiederkaeufer nicht jedes Mal neu angelegt
-- wird und sein Abo auffindbar bleibt.
ALTER TABLE nutzer ADD COLUMN IF NOT EXISTS stripe_kunde TEXT;
ALTER TABLE nutzer ADD COLUMN IF NOT EXISTS stripe_abo TEXT;
CREATE INDEX IF NOT EXISTS nutzer_steuer_index ON nutzer (steuer_index)
  WHERE steuer_index IS NOT NULL;
ALTER TABLE nutzer ADD COLUMN IF NOT EXISTS email_bestaetigt TIMESTAMPTZ;
-- Konten, die es vor der Bestätigungspflicht schon gab, gelten als
-- bestätigt: Sie haben sich nie registrieren können, ohne dass jemand
-- sie von Hand freigeschaltet hat. Ohne diese Zeile sperrte sich der
-- Betreiber beim ersten Start selbst aus.
UPDATE nutzer SET email_bestaetigt = angelegt
 WHERE email_bestaetigt IS NULL AND angelegt < now() - interval '1 minute';
"""

# Seed-Tarife. Bewusst so gewählt, dass beide diskutierten Modelle abgebildet
# sind — Prepaid-Guthaben und Monatsbeitrag mit Inklusivmenge. Welches davon
# gilt, entscheidet der Adminbereich, nicht der Code.
_STANDARD_TARIFE = (
    Tarif(
        schluessel="probe",
        name="Probe",
        beschreibung="Zum Ausprobieren: drei vollwertige Rechnungen, kein Abo, "
        "keine Zahlungsdaten.",
        monatsbeitrag_cent=0,
        inklusiv_rechnungen=3,
        preis_je_rechnung_cent=290,
        reihenfolge=10,
        sichtbar=True,
    ),
    Tarif(
        schluessel="guthaben",
        name="Guthaben",
        beschreibung="Bezahlt wird je Rechnung, das Guthaben verfällt nicht. "
        "Passt zum stoßweisen Schreiben.",
        monatsbeitrag_cent=0,
        inklusiv_rechnungen=0,
        preis_je_rechnung_cent=249,
        reihenfolge=20,
        sichtbar=True,
    ),
    Tarif(
        schluessel="monat",
        name="Monatlich",
        beschreibung="Zehn Rechnungen im Monat inklusive, jede weitere aus dem "
        "Guthaben.",
        monatsbeitrag_cent=900,
        inklusiv_rechnungen=10,
        preis_je_rechnung_cent=190,
        reihenfolge=30,
        sichtbar=True,
    ),
    Tarif(
        schluessel="unbegrenzt",
        name="Unbegrenzt",
        beschreibung="Ohne Mengenbegrenzung — für Vielschreiber und für den "
        "Betreiber selbst.",
        monatsbeitrag_cent=1900,
        inklusiv_rechnungen=None,
        preis_je_rechnung_cent=0,
        reihenfolge=40,
        sichtbar=False,
    ),
)

STANDARD_TARIF = "probe"
ADMIN_TARIF = "unbegrenzt"


def richte_schema_ein() -> None:
    """Legt Tabellen und Standardtarife an. Mehrfacher Aufruf ist harmlos."""
    with verbindung() as verb:
        verb.execute(_SCHEMA)
        verb.execute(_NACHTRAEGE)
        for tarif in _STANDARD_TARIFE:
            verb.execute(
                """INSERT INTO tarife (schluessel, name, beschreibung,
                       monatsbeitrag_cent, inklusiv_rechnungen,
                       preis_je_rechnung_cent, reihenfolge, sichtbar)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (schluessel) DO NOTHING""",
                (
                    tarif.schluessel,
                    tarif.name,
                    tarif.beschreibung,
                    tarif.monatsbeitrag_cent,
                    tarif.inklusiv_rechnungen,
                    tarif.preis_je_rechnung_cent,
                    tarif.reihenfolge,
                    tarif.sichtbar,
                ),
            )


# ---------------------------------------------------------------- Passwörter

def hashe_passwort(passwort: str) -> str:
    salz = secrets.token_bytes(16)
    kern = hashlib.scrypt(
        passwort.encode("utf-8"),
        salt=salz,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salz.hex()}${kern.hex()}"


def passwort_stimmt(passwort: str, gespeichert: str) -> bool:
    try:
        art, n, r, p, salz_hex, kern_hex = gespeichert.split("$")
        if art != "scrypt":
            return False
        kern = hashlib.scrypt(
            passwort.encode("utf-8"),
            salt=bytes.fromhex(salz_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_SCRYPT_MAXMEM,
            dklen=len(kern_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(kern.hex(), kern_hex)


def pruefe_passwortregeln(passwort: str) -> None:
    if len(passwort) < MINDESTLAENGE_PASSWORT:
        raise KontoFehler(
            f"Das Passwort braucht mindestens {MINDESTLAENGE_PASSWORT} Zeichen."
        )


def normalisiere_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL_MUSTER.match(email):
        raise KontoFehler("Das sieht nicht nach einer E-Mail-Adresse aus.")
    return email


# ---------------------------------------------------------------- Tarife

def _tarif_aus_zeile(zeile: dict) -> Tarif:
    return Tarif(
        schluessel=zeile["schluessel"],
        name=zeile["name"],
        beschreibung=zeile["beschreibung"],
        monatsbeitrag_cent=zeile["monatsbeitrag_cent"],
        inklusiv_rechnungen=zeile["inklusiv_rechnungen"],
        preis_je_rechnung_cent=zeile["preis_je_rechnung_cent"],
        reihenfolge=zeile["reihenfolge"],
        sichtbar=zeile["sichtbar"],
        hervorheben=zeile["hervorheben"],
        stripe_preis=zeile["stripe_preis"] or "",
    )


def tarife(nur_sichtbare: bool = False) -> list[Tarif]:
    bedingung = "WHERE sichtbar" if nur_sichtbare else ""
    with verbindung() as verb:
        zeilen = verb.execute(
            f"SELECT * FROM tarife {bedingung} ORDER BY reihenfolge, schluessel"
        ).fetchall()
    return [_tarif_aus_zeile(zeile) for zeile in zeilen]


def tarif(schluessel: str) -> Tarif:
    with verbindung() as verb:
        zeile = verb.execute(
            "SELECT * FROM tarife WHERE schluessel = %s", (schluessel,)
        ).fetchone()
    if zeile is None:
        raise KontoFehler(f"Unbekannter Tarif: {schluessel!r}.")
    return _tarif_aus_zeile(zeile)


def speichere_tarif(tarif_neu: Tarif) -> Tarif:
    with verbindung() as verb:
        verb.execute(
            """INSERT INTO tarife (schluessel, name, beschreibung,
                   monatsbeitrag_cent, inklusiv_rechnungen,
                   preis_je_rechnung_cent, reihenfolge, sichtbar, hervorheben,
                   stripe_preis)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (schluessel) DO UPDATE SET
                   name = EXCLUDED.name,
                   beschreibung = EXCLUDED.beschreibung,
                   monatsbeitrag_cent = EXCLUDED.monatsbeitrag_cent,
                   inklusiv_rechnungen = EXCLUDED.inklusiv_rechnungen,
                   preis_je_rechnung_cent = EXCLUDED.preis_je_rechnung_cent,
                   reihenfolge = EXCLUDED.reihenfolge,
                   sichtbar = EXCLUDED.sichtbar,
                   hervorheben = EXCLUDED.hervorheben,
                   stripe_preis = EXCLUDED.stripe_preis""",
            (
                tarif_neu.schluessel,
                tarif_neu.name,
                tarif_neu.beschreibung,
                tarif_neu.monatsbeitrag_cent,
                tarif_neu.inklusiv_rechnungen,
                tarif_neu.preis_je_rechnung_cent,
                tarif_neu.reihenfolge,
                tarif_neu.sichtbar,
                tarif_neu.hervorheben,
                tarif_neu.stripe_preis,
            ),
        )
    return tarif(tarif_neu.schluessel)


# ---------------------------------------------------------------- Nutzer

_NUTZER_SPALTEN = (
    "id, email, rolle, status, tarif, guthaben_cent, passwort_wechseln, "
    "angelegt, zuletzt_angemeldet, email_bestaetigt"
)


def _nutzer_aus_zeile(zeile: dict) -> Nutzer:
    return Nutzer(
        id=zeile["id"],
        email=zeile["email"],
        rolle=zeile["rolle"],
        status=zeile["status"],
        tarif=zeile["tarif"],
        guthaben_cent=zeile["guthaben_cent"],
        passwort_wechseln=zeile["passwort_wechseln"],
        angelegt=zeile["angelegt"],
        zuletzt_angemeldet=zeile["zuletzt_angemeldet"],
        email_bestaetigt=zeile["email_bestaetigt"],
    )


def registriere(email: str, passwort: str) -> tuple[Nutzer, str]:
    """Legt ein Konto an und liefert es samt Wiederherstellungscode.

    Der Code wird **einmalig** hier zurückgegeben und nirgends gespeichert
    — nur seine Hülle um den Datenschlüssel. Wer ihn verliert und sein
    Passwort vergisst, kommt an die Daten nicht mehr heran; das ist der
    Zweck (siehe ``tresor``).
    """
    email = normalisiere_email(email)
    pruefe_passwortregeln(passwort)
    datenschluessel = tresor.neuer_datenschluessel()
    code = tresor.neuer_wiederherstellungscode()
    with verbindung() as verb:
        vorhanden = verb.execute(
            "SELECT 1 FROM nutzer WHERE email = %s", (email,)
        ).fetchone()
        if vorhanden:
            raise KontoFehler("Für diese E-Mail-Adresse gibt es bereits ein Konto.")
        zeile = verb.execute(
            f"""INSERT INTO nutzer (email, passwort_hash, rolle, status, tarif,
                                    huelle_passwort, huelle_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_NUTZER_SPALTEN}""",
            (email, hashe_passwort(passwort), ROLLE_KUNDE, STATUS_WARTET,
             STANDARD_TARIF,
             tresor.verpacke(datenschluessel, passwort),
             tresor.verpacke(datenschluessel, tresor.normalisiere_code(code))),
        ).fetchone()
    return _nutzer_aus_zeile(zeile), code


def nutzer(nutzer_id: int) -> Nutzer | None:
    with verbindung() as verb:
        zeile = verb.execute(
            f"SELECT {_NUTZER_SPALTEN} FROM nutzer WHERE id = %s", (nutzer_id,)
        ).fetchone()
    return _nutzer_aus_zeile(zeile) if zeile else None


def nutzer_liste() -> list[Nutzer]:
    with verbindung() as verb:
        zeilen = verb.execute(
            f"SELECT {_NUTZER_SPALTEN} FROM nutzer ORDER BY angelegt DESC"
        ).fetchall()
    return [_nutzer_aus_zeile(zeile) for zeile in zeilen]


def pruefe_anmeldung(email: str, passwort: str) -> tuple[Nutzer, bytes | None]:
    """Prüft E-Mail und Passwort, öffnet dabei die Hülle.

    Liefert den Nutzer und seinen **Datenschlüssel** — hier ist der
    einzige Moment, in dem das Passwort im Klartext vorliegt und die Hülle
    sich öffnen lässt. Danach lebt der Schlüssel nur noch verpackt in der
    Sitzung.

    ``None`` steht für ein Konto ohne Hülle — aus der Zeit vor dieser
    Änderung. Der Aufrufer legt sie dann nach.

    Bei jedem Fehlschlag dieselbe Meldung: Ob die Adresse existiert, geht
    niemanden etwas an.
    """
    falsch = KontoFehler("E-Mail-Adresse oder Passwort stimmt nicht.")
    try:
        email = normalisiere_email(email)
    except KontoFehler:
        raise falsch from None
    with verbindung() as verb:
        zeile = verb.execute(
            f"SELECT {_NUTZER_SPALTEN}, passwort_hash, huelle_passwort "
            f"FROM nutzer WHERE email = %s",
            (email,),
        ).fetchone()
    if zeile is None or not passwort_stimmt(passwort, zeile["passwort_hash"]):
        raise falsch
    person = _nutzer_aus_zeile(zeile)
    huelle = zeile["huelle_passwort"]
    if not huelle:
        return person, None
    try:
        return person, tresor.oeffne(bytes(huelle), passwort)
    except tresor.TresorFehler:
        # Passwort stimmt, Hülle nicht — etwa nach einem Zurúcksetzen ohne
        # Wiederherstellungscode. Der Zugang steht, die Daten bleiben zu.
        return person, None


def lege_huellen_an(nutzer_id: int, passwort: str) -> bytes:
    """Legt Datenschlüssel und Hülle für ein Konto ohne beides an.

    Betrifft Konten aus der Zeit vor der Verschlüsselung und den
    Startadmin aus der Umgebung, der ohne Registrierung entsteht. Der
    Wiederherstellungscode fehlt dabei — er kann nur dort gezeigt werden,
    wo jemand zusieht; ``erneuere_code`` holt das nach.
    """
    datenschluessel = tresor.neuer_datenschluessel()
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET huelle_passwort = %s WHERE id = %s",
            (tresor.verpacke(datenschluessel, passwort), nutzer_id),
        )
    return datenschluessel


def erneuere_code(nutzer_id: int, datenschluessel: bytes) -> str:
    """Neuer Wiederherstellungscode für denselben Datenschlüssel.

    Der alte verfällt damit. Nur einmal zurückgegeben, nie gespeichert.
    """
    code = tresor.neuer_wiederherstellungscode()
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET huelle_code = %s WHERE id = %s",
            (tresor.verpacke(datenschluessel, tresor.normalisiere_code(code)),
             nutzer_id),
        )
    return code


def setze_passwort(nutzer_id: int, passwort: str) -> None:
    pruefe_passwortregeln(passwort)
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET passwort_hash = %s, passwort_wechseln = FALSE "
            "WHERE id = %s",
            (hashe_passwort(passwort), nutzer_id),
        )


def wechsle_passwort(nutzer_id: int, alt: str, neu: str) -> None:
    """Passwort ändern und die Hülle mitnehmen — verlustfrei.

    Wie bei einer Wallet wird **nur die Hülle** neu verschlüsselt; der
    Datenschlüssel darin bleibt derselbe. Keine einzige Datei muss
    angefasst werden.

    Beides zusammen in einem Vorgang: Bliebe die alte Hülle stehen,
    während der Hash schon neu ist, käme niemand mehr an die Daten.
    """
    with verbindung() as verb:
        zeile = verb.execute(
            "SELECT passwort_hash, huelle_passwort FROM nutzer WHERE id = %s",
            (nutzer_id,),
        ).fetchone()
        if zeile is None or not passwort_stimmt(alt, zeile["passwort_hash"]):
            raise KontoFehler("Das bisherige Passwort stimmt nicht.")
        pruefe_passwortregeln(neu)

        huelle_neu = None
        if zeile["huelle_passwort"]:
            try:
                datenschluessel = tresor.oeffne(bytes(zeile["huelle_passwort"]), alt)
                huelle_neu = tresor.verpacke(datenschluessel, neu)
            except tresor.TresorFehler:
                # Hülle unbrauchbar (etwa nach einem Zurúcksetzen ohne Code).
                # Das Passwort darf trotzdem wechseln — die Daten sind ohnehin
                # schon unerreichbar, und ein Abbruch hälfe niemandem.
                huelle_neu = None

        if huelle_neu is None:
            verb.execute(
                "UPDATE nutzer SET passwort_hash = %s, passwort_wechseln = FALSE "
                "WHERE id = %s",
                (hashe_passwort(neu), nutzer_id),
            )
        else:
            verb.execute(
                "UPDATE nutzer SET passwort_hash = %s, passwort_wechseln = FALSE, "
                "huelle_passwort = %s WHERE id = %s",
                (hashe_passwort(neu), huelle_neu, nutzer_id),
            )


def stelle_mit_code_wieder_her(email: str, code: str, neues_passwort: str) -> Nutzer:
    """Zugang über den Wiederherstellungscode zurückholen — mit den Daten.

    Der Code öffnet Hülle B, daraus kommt der Datenschlüssel, und mit dem
    neuen Passwort entsteht Hülle A neu. Genau der Weg, den eine Wallet
    über ihre Wiederherstellungswörter geht.
    """
    falsch = KontoFehler("Adresse oder Wiederherstellungscode stimmt nicht.")
    try:
        email = normalisiere_email(email)
    except KontoFehler:
        raise falsch from None
    pruefe_passwortregeln(neues_passwort)
    sauber = tresor.normalisiere_code(code)
    with verbindung() as verb:
        zeile = verb.execute(
            f"SELECT {_NUTZER_SPALTEN}, huelle_code FROM nutzer WHERE email = %s",
            (email,),
        ).fetchone()
        if zeile is None or not zeile["huelle_code"]:
            raise falsch
        try:
            datenschluessel = tresor.oeffne(bytes(zeile["huelle_code"]), sauber)
        except tresor.TresorFehler:
            raise falsch from None
        verb.execute(
            "UPDATE nutzer SET passwort_hash = %s, passwort_wechseln = FALSE, "
            "huelle_passwort = %s WHERE id = %s",
            (hashe_passwort(neues_passwort),
             tresor.verpacke(datenschluessel, neues_passwort),
             zeile["id"]),
        )
    return _nutzer_aus_zeile(zeile)


def setze_status(nutzer_id: int, status: str) -> Nutzer:
    if status not in (STATUS_WARTET, STATUS_FREI, STATUS_GESPERRT):
        raise KontoFehler(f"Unbekannter Status: {status!r}.")
    with verbindung() as verb:
        zeile = verb.execute(
            f"""UPDATE nutzer SET status = %s,
                    freigegeben = CASE WHEN %s = 'frei' AND freigegeben IS NULL
                                       THEN now() ELSE freigegeben END
                WHERE id = %s RETURNING {_NUTZER_SPALTEN}""",
            (status, status, nutzer_id),
        ).fetchone()
        if status == STATUS_GESPERRT:
            # Gesperrte Konten sollen nicht mit einer offenen Sitzung weiterlaufen.
            verb.execute("DELETE FROM sitzungen WHERE nutzer = %s", (nutzer_id,))
    if zeile is None:
        raise KontoFehler("Konto nicht gefunden.")
    return _nutzer_aus_zeile(zeile)


def setze_rolle(nutzer_id: int, rolle: str) -> Nutzer:
    if rolle not in (ROLLE_KUNDE, ROLLE_ADMIN):
        raise KontoFehler(f"Unbekannte Rolle: {rolle!r}.")
    with verbindung() as verb:
        if rolle == ROLLE_KUNDE:
            uebrig = verb.execute(
                "SELECT count(*) AS anzahl FROM nutzer WHERE rolle = 'admin' "
                "AND id <> %s",
                (nutzer_id,),
            ).fetchone()
            if uebrig["anzahl"] == 0:
                raise KontoFehler(
                    "Das ist der letzte Admin — die Rolle lässt sich nicht entziehen."
                )
        zeile = verb.execute(
            f"UPDATE nutzer SET rolle = %s WHERE id = %s RETURNING {_NUTZER_SPALTEN}",
            (rolle, nutzer_id),
        ).fetchone()
    if zeile is None:
        raise KontoFehler("Konto nicht gefunden.")
    return _nutzer_aus_zeile(zeile)


def setze_tarif(nutzer_id: int, schluessel: str) -> Nutzer:
    tarif(schluessel)  # wirft, wenn es den Tarif nicht gibt
    with verbindung() as verb:
        zeile = verb.execute(
            f"UPDATE nutzer SET tarif = %s WHERE id = %s RETURNING {_NUTZER_SPALTEN}",
            (schluessel, nutzer_id),
        ).fetchone()
    if zeile is None:
        raise KontoFehler("Konto nicht gefunden.")
    return _nutzer_aus_zeile(zeile)


def buche_guthaben(nutzer_id: int, cent: int) -> Nutzer:
    """Schreibt Guthaben gut (positiv) oder ab (negativ). Nie unter null."""
    with verbindung() as verb:
        zeile = verb.execute(
            f"""UPDATE nutzer SET guthaben_cent = GREATEST(0, guthaben_cent + %s)
                WHERE id = %s RETURNING {_NUTZER_SPALTEN}""",
            (cent, nutzer_id),
        ).fetchone()
    if zeile is None:
        raise KontoFehler("Konto nicht gefunden.")
    return _nutzer_aus_zeile(zeile)


def loesche_nutzer(nutzer_id: int) -> None:
    with verbindung() as verb:
        uebrig = verb.execute(
            "SELECT count(*) AS anzahl FROM nutzer WHERE rolle = 'admin' AND id <> %s",
            (nutzer_id,),
        ).fetchone()
        eigen = verb.execute(
            "SELECT rolle FROM nutzer WHERE id = %s", (nutzer_id,)
        ).fetchone()
        if eigen is None:
            raise KontoFehler("Konto nicht gefunden.")
        if eigen["rolle"] == ROLLE_ADMIN and uebrig["anzahl"] == 0:
            raise KontoFehler("Das ist der letzte Admin — er lässt sich nicht löschen.")
        verb.execute("DELETE FROM nutzer WHERE id = %s", (nutzer_id,))


# ---------------------------------------------------------------- Einstellungen

# Der Serverschlüssel schützt Geheimnisse, die die App SELBST lesen muss —
# das SMTP-Passwort etwa. Anders als bei den Mandantendaten geht hier keine
# Betreiber-Blindheit: Wer die App starten kann, kann auch Mails versenden.
# Der Schlüssel hält einen gestohlenen Datenbank-Dump auf, nicht mehr.
#
# Ohne gesetzten Schlüssel wird im Klartext gespeichert und eine Warnung
# geloggt — sonst stünde die lokale Entwicklung still.
SERVERSCHLUESSEL = os.environ.get("RECHNUNGSBLATT_SCHLUESSEL", "")

SMTP_FELDER = ("smtp_host", "smtp_port", "smtp_benutzer", "smtp_passwort",
               "smtp_absender", "smtp_tls", "oeffentliche_adresse",
               # Plausible gehört in dieselbe Kategorie wie der Postausgang:
               # Betriebseinstellung, die sich ändern lässt, ohne den Stack
               # neu zu deployen.
               "plausible_url", "plausible_domain",
               # Stripe. Der geheime Schluessel und das Webhook-Geheimnis
               # liegen verschluesselt (siehe _GEHEIME_FELDER).
               # Die Preis-ID eines Abos steht am Tarif, nicht hier: Es gibt
               # mehr als einen Abo-Tarif.
               "stripe_secret", "stripe_webhook_secret", "stripe_aufladungen")
_GEHEIME_FELDER = {"smtp_passwort", "stripe_secret", "stripe_webhook_secret"}


def einstellungen(mit_geheimnissen: bool = False) -> dict[str, str]:
    """Alle Betriebseinstellungen. Geheimnisse nur auf ausdrücklichen Wunsch."""
    with verbindung() as verb:
        zeilen = verb.execute("SELECT * FROM einstellungen").fetchall()
    ergebnis: dict[str, str] = {}
    for zeile in zeilen:
        if zeile["geheim"]:
            if not mit_geheimnissen:
                # Für die Oberfläche: nur zeigen, DASS etwas gesetzt ist.
                ergebnis[zeile["schluessel"]] = "••••••" if zeile["wert"] else ""
                continue
            ergebnis[zeile["schluessel"]] = _entpacke_geheimnis(zeile["wert"])
        else:
            ergebnis[zeile["schluessel"]] = zeile["wert"]
    return ergebnis


def setze_einstellungen(werte: dict[str, str]) -> None:
    """Schreibt die übergebenen Felder; unbekannte werden verworfen."""
    with verbindung() as verb:
        for feld, wert in werte.items():
            if feld not in SMTP_FELDER:
                continue
            geheim = feld in _GEHEIME_FELDER
            if geheim:
                # Leer heißt „unverändert lassen" — die Oberfläche schickt
                # Punkte zurück, nicht das echte Passwort.
                if not wert or set(wert) <= {"•"}:
                    continue
                wert = _verpacke_geheimnis(wert)
            verb.execute(
                """INSERT INTO einstellungen (schluessel, wert, geheim)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (schluessel) DO UPDATE
                   SET wert = EXCLUDED.wert, geheim = EXCLUDED.geheim""",
                (feld, wert, geheim),
            )


def _verpacke_geheimnis(klartext: str) -> str:
    if not SERVERSCHLUESSEL:
        return klartext
    roh = tresor.verpacke(klartext.encode("utf-8"), SERVERSCHLUESSEL)
    return "v1:" + roh.hex()


def _entpacke_geheimnis(gespeichert: str) -> str:
    if not gespeichert.startswith("v1:"):
        return gespeichert          # noch im Klartext abgelegt
    if not SERVERSCHLUESSEL:
        return ""
    try:
        return tresor.oeffne(bytes.fromhex(gespeichert[3:]),
                             SERVERSCHLUESSEL).decode("utf-8")
    except (tresor.TresorFehler, ValueError):
        return ""


# ---------------------------------------------------------------- Steuer-Index

def steuer_index(ust_idnr: str | None, steuernummer: str | None) -> str | None:
    """Blind Index über das Steuermerkmal eines Mandanten.

    Erlaubt die Frage „hat ein anderes Konto dieselbe Nummer?", ohne die
    Nummer lesbar zu speichern. Sie selbst liegt verschlüsselt in den
    Stammdaten; hier steht nur ein Abdruck.

    **Warum nicht im Klartext**, obwohl eine USt-IdNr. auf jeder Rechnung
    steht: Öffentlich ist die Nummer, nicht die Verknüpfung. Eine Spalte
    mit Klartextnummern wäre eine Kundenliste — genau das, was die
    Verschlüsselung sonst verhindert.

    Der Serverschlüssel geht als Pepper mit ein. Ohne ihn ließe sich der
    Abdruck durch Ausprobieren zurückrechnen: Der Suchraum einer USt-IdNr.
    ist klein genug dafür.

    Bevorzugt wird die USt-IdNr.; Kleinunternehmer haben oft keine, tragen
    aber zwingend eine Steuernummer (Befund S3 verlangt eines von beidem).
    """
    roh = (ust_idnr or "").strip() or (steuernummer or "").strip()
    if not roh:
        return None
    # Normalisieren: Steuernummern werden je Finanzamt unterschiedlich
    # geschrieben (123/456/78901 oder 12345678901). Ohne diesen Schritt
    # fände der Vergleich dieselbe Nummer nicht wieder.
    sauber = "".join(z for z in roh.upper() if z.isalnum())
    if not sauber:
        return None
    return hashlib.sha256(
        (sauber + "|" + SERVERSCHLUESSEL).encode("utf-8")
    ).hexdigest()


def setze_steuer_index(nutzer_id: int, abdruck: str | None) -> None:
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET steuer_index = %s WHERE id = %s",
            (abdruck, nutzer_id),
        )


def konten_mit_gleichem_steuermerkmal() -> list[dict]:
    """Konten, die sich ein Steuermerkmal teilen — für den Adminbereich.

    Bewusst nur eine Meldung, keine Sperre: Es gibt echte Doppelfälle
    (Betriebsübergabe, Wechsel der Steuernummer nach einem Umzug). Eine
    harte Sperre träfe die und wäre für den Betroffenen nicht erklärbar.
    """
    with verbindung() as verb:
        zeilen = verb.execute(
            """SELECT steuer_index,
                      count(*) AS anzahl,
                      array_agg(email ORDER BY angelegt) AS konten
               FROM nutzer
               WHERE steuer_index IS NOT NULL
               GROUP BY steuer_index
               HAVING count(*) > 1"""
        ).fetchall()
    # Der Abdruck selbst geht nicht nach draußen — er wäre für die
    # Oberfläche wertlos und im Log ein unnötiges Merkmal.
    return [{"konten": list(z["konten"]), "anzahl": z["anzahl"]} for z in zeilen]


# ---------------------------------------------------------------- Zahlungen

def merke_stripe_kunde(nutzer_id: int, kunde: str) -> None:
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET stripe_kunde = %s WHERE id = %s", (kunde, nutzer_id)
        )


def nutzer_zu_stripe_kunde(kunde: str) -> Nutzer | None:
    with verbindung() as verb:
        zeile = verb.execute(
            f"SELECT {_NUTZER_SPALTEN} FROM nutzer WHERE stripe_kunde = %s", (kunde,)
        ).fetchone()
    return _nutzer_aus_zeile(zeile) if zeile else None


def stripe_kunde_von(nutzer_id: int) -> str | None:
    with verbindung() as verb:
        zeile = verb.execute(
            "SELECT stripe_kunde FROM nutzer WHERE id = %s", (nutzer_id,)
        ).fetchone()
    return zeile["stripe_kunde"] if zeile else None


def verbuche_zahlung(
    stripe_id: str, nutzer_id: int, art: str, betrag_cent: int
) -> bool:
    """Bucht eine Zahlung genau einmal. Liefert False, wenn schon gebucht.

    **Der wichtigste Teil der Stripe-Anbindung.** Webhooks kommen laut
    Stripe mehrfach an — bei Zustellproblemen wird wiederholt, und auch
    im Normalbetrieb sind Doppelzustellungen zugesichert möglich. Ohne
    diese Sperre buchte dieselbe Zahlung zweimal Guthaben.

    Die Eindeutigkeit hängt am Primärschlüssel, nicht an einer Prüfung
    davor: Zwei gleichzeitige Zustellungen würden eine Abfrage beide
    passieren, aber nur ein INSERT gewinnt.
    """
    with verbindung() as verb:
        with verb.transaction():
            try:
                verb.execute(
                    "INSERT INTO zahlungen (stripe_id, nutzer, art, betrag_cent) "
                    "VALUES (%s, %s, %s, %s)",
                    (stripe_id, nutzer_id, art, betrag_cent),
                )
            except psycopg.errors.UniqueViolation:
                return False
            if art == "guthaben" and betrag_cent > 0:
                verb.execute(
                    "UPDATE nutzer SET guthaben_cent = guthaben_cent + %s "
                    "WHERE id = %s",
                    (betrag_cent, nutzer_id),
                )
    return True


def setze_abo(nutzer_id: int, abo: str | None, tarif_schluessel: str | None) -> None:
    """Trägt ein laufendes Abo ein und setzt den zugehörigen Tarif.

    ``abo=None`` beendet es: Der Tarif fällt auf den Standard zurück, das
    vorhandene Guthaben bleibt — es ist bezahlt.
    """
    with verbindung() as verb:
        if tarif_schluessel:
            verb.execute(
                "UPDATE nutzer SET stripe_abo = %s, tarif = %s WHERE id = %s",
                (abo, tarif_schluessel, nutzer_id),
            )
        else:
            verb.execute(
                "UPDATE nutzer SET stripe_abo = %s WHERE id = %s", (abo, nutzer_id)
            )


def zahlungen_von(nutzer_id: int, grenze: int = 20) -> list[dict]:
    with verbindung() as verb:
        zeilen = verb.execute(
            "SELECT art, betrag_cent, zeitpunkt FROM zahlungen "
            "WHERE nutzer = %s ORDER BY zeitpunkt DESC LIMIT %s",
            (nutzer_id, grenze),
        ).fetchall()
    return [dict(z) for z in zeilen]


# ---------------------------------------------------------------- Nachweise

ZWECK_EMAIL = "email"
ZWECK_RUECKSETZEN = "ruecksetzen"

# Der 6-stellige Code hat nur eine Million Möglichkeiten — er trägt allein
# durch die Begrenzung. Fünf Fehlversuche, dann ist er verbraucht.
MAX_VERSUCHE = 5
_GUELTIG = {ZWECK_EMAIL: 30, ZWECK_RUECKSETZEN: 60}   # Minuten


def _neuer_code() -> str:
    """Sechs Ziffern, gleichverteilt. `secrets`, nicht `random`."""
    return f"{secrets.randbelow(1_000_000):06d}"


def lege_nachweis_an(nutzer_id: int, zweck: str) -> str:
    """Erzeugt Code (E-Mail) oder Zeichenkette (Rücksetz-Link).

    Gespeichert wird nur der SHA-256 — dieselbe Logik wie bei den
    Sitzungen: Wer die Datenbank liest, kann damit nichts anfangen.

    Ältere Nachweise desselben Zwecks fallen weg. Sonst blieben nach
    mehrfachem Anfordern mehrere gültige Codes nebeneinander stehen.
    """
    wert = _neuer_code() if zweck == ZWECK_EMAIL else secrets.token_urlsafe(32)
    laeuft_ab = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        minutes=_GUELTIG.get(zweck, 30)
    )
    with verbindung() as verb:
        verb.execute(
            "DELETE FROM nachweise WHERE nutzer = %s AND zweck = %s",
            (nutzer_id, zweck),
        )
        verb.execute(
            "INSERT INTO nachweise (kennung, nutzer, zweck, laeuft_ab) "
            "VALUES (%s, %s, %s, %s)",
            (_kennung(wert), nutzer_id, zweck, laeuft_ab),
        )
    return wert


def loese_nachweis_ein(wert: str, zweck: str) -> int:
    """Prüft einen Nachweis und verbraucht ihn. Liefert die Nutzer-ID.

    Der Nachweis wird in jedem Fall entwertet — auch beim letzten
    Fehlversuch. Sonst ließen sich sechs Ziffern durchprobieren.
    """
    falsch = KontoFehler("Der Code stimmt nicht oder ist abgelaufen.")
    if not wert:
        raise falsch
    with verbindung() as verb:
        zeile = verb.execute(
            "SELECT nutzer, versuche, laeuft_ab FROM nachweise "
            "WHERE kennung = %s AND zweck = %s",
            (_kennung(wert), zweck),
        ).fetchone()
        if zeile is None:
            # Fehlversuch am RICHTIGEN Nachweis mitzählen, damit Raten
            # nicht unbegrenzt möglich ist. Ohne Treffer wissen wir aber
            # nicht, wessen Zähler gemeint ist — deshalb nur abweisen.
            raise falsch
        if zeile["laeuft_ab"] <= dt.datetime.now(dt.timezone.utc):
            verb.execute("DELETE FROM nachweise WHERE kennung = %s",
                         (_kennung(wert),))
            raise falsch
        verb.execute("DELETE FROM nachweise WHERE kennung = %s", (_kennung(wert),))
        return zeile["nutzer"]


def zaehle_fehlversuch(nutzer_id: int, zweck: str) -> None:
    """Erhöht den Zähler; verbraucht den Nachweis nach MAX_VERSUCHE.

    Getrennt vom Einlösen, weil der Fehlversuch am Konto hängt, nicht am
    geratenen Wert — sonst könnte man beliebig oft danebenliegen.
    """
    with verbindung() as verb:
        verb.execute(
            "UPDATE nachweise SET versuche = versuche + 1 "
            "WHERE nutzer = %s AND zweck = %s",
            (nutzer_id, zweck),
        )
        verb.execute(
            "DELETE FROM nachweise WHERE nutzer = %s AND zweck = %s AND versuche >= %s",
            (nutzer_id, zweck, MAX_VERSUCHE),
        )


def bestaetige_email(nutzer_id: int) -> None:
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET email_bestaetigt = now() WHERE id = %s", (nutzer_id,)
        )


def nutzer_zu_email(email: str) -> Nutzer | None:
    try:
        email = normalisiere_email(email)
    except KontoFehler:
        return None
    with verbindung() as verb:
        zeile = verb.execute(
            f"SELECT {_NUTZER_SPALTEN} FROM nutzer WHERE email = %s", (email,)
        ).fetchone()
    return _nutzer_aus_zeile(zeile) if zeile else None


# ---------------------------------------------------------------- Sitzungen

def _kennung(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode("utf-8")).hexdigest()


def starte_sitzung(nutzer_id: int, datenschluessel: bytes | None = None) -> str:
    """Legt eine Sitzung an und liefert den Schlüssel für das Cookie.

    Der Datenschlüssel reist mit, aber **verpackt**: verschlüsselt mit dem
    Sitzungsschlüssel, den nur der Browser bekommt. In der Datenbank steht
    davon nur ein SHA-256-Abdruck (``kennung``) — wer sie liest, kann den
    Eintrag nicht öffnen.
    """
    schluessel = secrets.token_urlsafe(32)
    laeuft_ab = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SITZUNG_TAGE)
    verpackt = (
        tresor.fuer_sitzung(datenschluessel, schluessel)
        if datenschluessel else None
    )
    with verbindung() as verb:
        verb.execute(
            "INSERT INTO sitzungen (kennung, nutzer, laeuft_ab, schluessel) "
            "VALUES (%s, %s, %s, %s)",
            (_kennung(schluessel), nutzer_id, laeuft_ab, verpackt),
        )
        verb.execute(
            "UPDATE nutzer SET zuletzt_angemeldet = now() WHERE id = %s", (nutzer_id,)
        )
    return schluessel


def datenschluessel_der_sitzung(schluessel: str | None) -> bytes | None:
    """Holt den Datenschlüssel aus der Sitzung zurück.

    Nur mit dem Sitzungsschlüssel aus dem Cookie zu öffnen. ``None``, wenn
    die Sitzung keinen trägt — etwa bei einem Konto ohne Hülle.
    """
    if not schluessel:
        return None
    with verbindung() as verb:
        zeile = verb.execute(
            "SELECT schluessel FROM sitzungen "
            "WHERE kennung = %s AND laeuft_ab > now()",
            (_kennung(schluessel),),
        ).fetchone()
    if zeile is None or not zeile["schluessel"]:
        return None
    try:
        return tresor.aus_sitzung(bytes(zeile["schluessel"]), schluessel)
    except tresor.TresorFehler:
        return None


def nutzer_zu_sitzung(schluessel: str | None) -> Nutzer | None:
    if not schluessel:
        return None
    with verbindung() as verb:
        zeile = verb.execute(
            f"""SELECT {', '.join('n.' + s.strip() for s in _NUTZER_SPALTEN.split(','))}
                FROM sitzungen s JOIN nutzer n ON n.id = s.nutzer
                WHERE s.kennung = %s AND s.laeuft_ab > now()""",
            (_kennung(schluessel),),
        ).fetchone()
    return _nutzer_aus_zeile(zeile) if zeile else None


def beende_sitzung(schluessel: str | None) -> None:
    if not schluessel:
        return
    with verbindung() as verb:
        verb.execute("DELETE FROM sitzungen WHERE kennung = %s", (_kennung(schluessel),))


def raeume_sitzungen_auf() -> int:
    with verbindung() as verb:
        ergebnis = verb.execute("DELETE FROM sitzungen WHERE laeuft_ab <= now()")
    return ergebnis.rowcount


# ---------------------------------------------------------------- Kontingent

def verbrauch_monat(nutzer_id: int, stichtag: dt.date | None = None) -> int:
    stichtag = stichtag or dt.date.today()
    with verbindung() as verb:
        zeile = verb.execute(
            """SELECT count(*) AS anzahl FROM verbrauch
               WHERE nutzer = %s
                 AND date_trunc('month', zeitpunkt) = date_trunc('month', %s::date)""",
            (nutzer_id, stichtag),
        ).fetchone()
    return zeile["anzahl"]


def kontingent(person: Nutzer) -> Kontingent:
    gewaehlt = tarif(person.tarif)
    return Kontingent(
        tarif=gewaehlt,
        verbraucht=verbrauch_monat(person.id),
        inklusiv=gewaehlt.inklusiv_rechnungen,
        guthaben_cent=person.guthaben_cent,
    )


def buche_rechnung(person: Nutzer, nummer: str) -> Kontingent:
    """Verbucht eine erzeugte Rechnung; zieht Guthaben, wenn nötig.

    Läuft in einer Transaktion mit Zeilensperre, damit zwei gleichzeitige
    Anfragen nicht beide das letzte Guthaben verbrauchen.
    """
    gewaehlt = tarif(person.tarif)
    with verbindung() as verb:
        with verb.transaction():
            zeile = verb.execute(
                "SELECT guthaben_cent FROM nutzer WHERE id = %s FOR UPDATE",
                (person.id,),
            ).fetchone()
            if zeile is None:
                raise KontoFehler("Konto nicht gefunden.")
            guthaben = zeile["guthaben_cent"]
            verbraucht = verb.execute(
                """SELECT count(*) AS anzahl FROM verbrauch
                   WHERE nutzer = %s
                     AND date_trunc('month', zeitpunkt) = date_trunc('month', now())""",
                (person.id,),
            ).fetchone()["anzahl"]

            inklusiv = gewaehlt.inklusiv_rechnungen
            kosten = 0
            if inklusiv is not None and verbraucht >= inklusiv:
                kosten = gewaehlt.preis_je_rechnung_cent
                if guthaben < kosten:
                    raise KontingentErschoepft(
                        "Die Inklusivmenge dieses Monats ist aufgebraucht und das "
                        "Guthaben reicht nicht für eine weitere Rechnung."
                    )
                guthaben -= kosten
                verb.execute(
                    "UPDATE nutzer SET guthaben_cent = %s WHERE id = %s",
                    (guthaben, person.id),
                )
            verb.execute(
                "INSERT INTO verbrauch (nutzer, nummer, kosten_cent) VALUES (%s, %s, %s)",
                (person.id, nummer, kosten),
            )
            verbraucht += 1
    return Kontingent(
        tarif=gewaehlt, verbraucht=verbraucht, inklusiv=inklusiv, guthaben_cent=guthaben
    )


def betriebszahlen() -> dict:
    """Zahlen für den Adminbereich — was im eigenen Haus messbar ist.

    Bewusst getrennt von Plausible: Das zählt Seitenaufrufe, hier geht es
    um Konten und erzeugte Belege. Beides zusammen ergibt erst ein Bild —
    wie viele kommen, und wie viele arbeiten wirklich damit.
    """
    with verbindung() as verb:
        konten_zahl = verb.execute(
            """SELECT
                   count(*) AS gesamt,
                   count(*) FILTER (WHERE status = 'frei') AS frei,
                   count(*) FILTER (WHERE status = 'wartet') AS wartet,
                   count(*) FILTER (WHERE status = 'gesperrt') AS gesperrt,
                   count(*) FILTER (WHERE email_bestaetigt IS NULL) AS unbestaetigt,
                   count(*) FILTER (WHERE angelegt > now() - interval '30 days')
                       AS neu_30t
               FROM nutzer"""
        ).fetchone()
        belege = verb.execute(
            """SELECT
                   count(*) AS gesamt,
                   count(*) FILTER (WHERE zeitpunkt >= date_trunc('month', now()))
                       AS monat,
                   count(*) FILTER (WHERE zeitpunkt > now() - interval '7 days')
                       AS woche,
                   coalesce(sum(kosten_cent), 0) AS umsatz_cent
               FROM verbrauch"""
        ).fetchone()
        # Wer arbeitet wirklich damit? Konten mit mindestens einem Beleg
        # im laufenden Monat — die aussagekräftigste Einzelzahl.
        aktiv = verb.execute(
            """SELECT count(DISTINCT nutzer) AS anzahl FROM verbrauch
               WHERE zeitpunkt >= date_trunc('month', now())"""
        ).fetchone()
        # Verlauf für ein kleines Balkenbild: die letzten zwölf Monate.
        verlauf = verb.execute(
            """SELECT to_char(date_trunc('month', zeitpunkt), 'YYYY-MM') AS monat,
                      count(*) AS anzahl
               FROM verbrauch
               WHERE zeitpunkt > now() - interval '12 months'
               GROUP BY 1 ORDER BY 1"""
        ).fetchall()
    return {
        "konten": dict(konten_zahl),
        "belege": dict(belege),
        "aktive_konten_monat": aktiv["anzahl"],
        "verlauf": [dict(z) for z in verlauf],
    }


def verbrauch_liste(nutzer_id: int, grenze: int = 50) -> list[dict]:
    with verbindung() as verb:
        zeilen = verb.execute(
            """SELECT nummer, kosten_cent, zeitpunkt FROM verbrauch
               WHERE nutzer = %s ORDER BY zeitpunkt DESC LIMIT %s""",
            (nutzer_id, grenze),
        ).fetchall()
    return [dict(zeile) for zeile in zeilen]


# ---------------------------------------------------------------- Admin-Start

def lege_admin_an() -> tuple[Nutzer, str | None] | None:
    """Legt beim Start den Admin aus ADMIN_EMAIL / ADMIN_PASSWORT an.

    Liefert (Nutzer, Passwort) beim Neuanlegen — das Passwort nur, wenn es
    erzeugt wurde und einmalig ins Log geschrieben werden muss. Existiert das
    Konto schon, wird es lediglich auf Adminrolle und Freigabe gehoben; das
    Passwort bleibt unangetastet, damit ein Neustart keine Änderung zurückdreht.
    """
    email_roh = os.environ.get("ADMIN_EMAIL", "").strip()
    if not email_roh:
        return None
    email = normalisiere_email(email_roh)

    with verbindung() as verb:
        vorhanden = verb.execute(
            f"SELECT {_NUTZER_SPALTEN} FROM nutzer WHERE email = %s", (email,)
        ).fetchone()

    if vorhanden is not None:
        person = _nutzer_aus_zeile(vorhanden)
        if not person.ist_admin or not person.ist_frei:
            with verbindung() as verb:
                zeile = verb.execute(
                    f"""UPDATE nutzer SET rolle = 'admin', status = 'frei',
                            freigegeben = COALESCE(freigegeben, now())
                        WHERE id = %s RETURNING {_NUTZER_SPALTEN}""",
                    (person.id,),
                ).fetchone()
            person = _nutzer_aus_zeile(zeile)
        return person, None

    passwort = os.environ.get("ADMIN_PASSWORT", "").strip()
    erzeugt = None
    if not passwort:
        passwort = secrets.token_urlsafe(15)
        erzeugt = passwort
    pruefe_passwortregeln(passwort)

    with verbindung() as verb:
        zeile = verb.execute(
            f"""INSERT INTO nutzer (email, passwort_hash, rolle, status, tarif,
                    passwort_wechseln, freigegeben, email_bestaetigt)
                VALUES (%s, %s, 'admin', 'frei', %s, TRUE, now(), now())
                RETURNING {_NUTZER_SPALTEN}""",
            (email, hashe_passwort(passwort), ADMIN_TARIF),
        ).fetchone()
    return _nutzer_aus_zeile(zeile), erzeugt
