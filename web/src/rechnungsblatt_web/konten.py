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

    @property
    def ist_admin(self) -> bool:
        return self.rolle == ROLLE_ADMIN

    @property
    def ist_frei(self) -> bool:
        return self.status == STATUS_FREI


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
    sichtbar               BOOLEAN NOT NULL DEFAULT TRUE
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
    zuletzt_angemeldet TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sitzungen (
    kennung   TEXT PRIMARY KEY,
    nutzer    BIGINT NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
    angelegt  TIMESTAMPTZ NOT NULL DEFAULT now(),
    laeuft_ab TIMESTAMPTZ NOT NULL
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
                   preis_je_rechnung_cent, reihenfolge, sichtbar)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (schluessel) DO UPDATE SET
                   name = EXCLUDED.name,
                   beschreibung = EXCLUDED.beschreibung,
                   monatsbeitrag_cent = EXCLUDED.monatsbeitrag_cent,
                   inklusiv_rechnungen = EXCLUDED.inklusiv_rechnungen,
                   preis_je_rechnung_cent = EXCLUDED.preis_je_rechnung_cent,
                   reihenfolge = EXCLUDED.reihenfolge,
                   sichtbar = EXCLUDED.sichtbar""",
            (
                tarif_neu.schluessel,
                tarif_neu.name,
                tarif_neu.beschreibung,
                tarif_neu.monatsbeitrag_cent,
                tarif_neu.inklusiv_rechnungen,
                tarif_neu.preis_je_rechnung_cent,
                tarif_neu.reihenfolge,
                tarif_neu.sichtbar,
            ),
        )
    return tarif(tarif_neu.schluessel)


# ---------------------------------------------------------------- Nutzer

_NUTZER_SPALTEN = (
    "id, email, rolle, status, tarif, guthaben_cent, passwort_wechseln, "
    "angelegt, zuletzt_angemeldet"
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
    )


def registriere(email: str, passwort: str) -> Nutzer:
    """Legt ein Konto an. Es wartet auf Freigabe durch den Admin."""
    email = normalisiere_email(email)
    pruefe_passwortregeln(passwort)
    with verbindung() as verb:
        vorhanden = verb.execute(
            "SELECT 1 FROM nutzer WHERE email = %s", (email,)
        ).fetchone()
        if vorhanden:
            raise KontoFehler("Für diese E-Mail-Adresse gibt es bereits ein Konto.")
        zeile = verb.execute(
            f"""INSERT INTO nutzer (email, passwort_hash, rolle, status, tarif)
                VALUES (%s, %s, %s, %s, %s) RETURNING {_NUTZER_SPALTEN}""",
            (email, hashe_passwort(passwort), ROLLE_KUNDE, STATUS_WARTET,
             STANDARD_TARIF),
        ).fetchone()
    return _nutzer_aus_zeile(zeile)


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


def pruefe_anmeldung(email: str, passwort: str) -> Nutzer:
    """Prüft E-Mail und Passwort. Wirft bei jedem Fehlschlag dieselbe Meldung."""
    falsch = KontoFehler("E-Mail-Adresse oder Passwort stimmt nicht.")
    try:
        email = normalisiere_email(email)
    except KontoFehler:
        raise falsch from None
    with verbindung() as verb:
        zeile = verb.execute(
            f"SELECT {_NUTZER_SPALTEN}, passwort_hash FROM nutzer WHERE email = %s",
            (email,),
        ).fetchone()
    if zeile is None or not passwort_stimmt(passwort, zeile["passwort_hash"]):
        raise falsch
    return _nutzer_aus_zeile(zeile)


def setze_passwort(nutzer_id: int, passwort: str) -> None:
    pruefe_passwortregeln(passwort)
    with verbindung() as verb:
        verb.execute(
            "UPDATE nutzer SET passwort_hash = %s, passwort_wechseln = FALSE "
            "WHERE id = %s",
            (hashe_passwort(passwort), nutzer_id),
        )


def wechsle_passwort(nutzer_id: int, alt: str, neu: str) -> None:
    with verbindung() as verb:
        zeile = verb.execute(
            "SELECT passwort_hash FROM nutzer WHERE id = %s", (nutzer_id,)
        ).fetchone()
    if zeile is None or not passwort_stimmt(alt, zeile["passwort_hash"]):
        raise KontoFehler("Das bisherige Passwort stimmt nicht.")
    setze_passwort(nutzer_id, neu)


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


# ---------------------------------------------------------------- Sitzungen

def _kennung(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode("utf-8")).hexdigest()


def starte_sitzung(nutzer_id: int) -> str:
    """Legt eine Sitzung an und liefert den Schlüssel für das Cookie."""
    schluessel = secrets.token_urlsafe(32)
    laeuft_ab = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SITZUNG_TAGE)
    with verbindung() as verb:
        verb.execute(
            "INSERT INTO sitzungen (kennung, nutzer, laeuft_ab) VALUES (%s, %s, %s)",
            (_kennung(schluessel), nutzer_id, laeuft_ab),
        )
        verb.execute(
            "UPDATE nutzer SET zuletzt_angemeldet = now() WHERE id = %s", (nutzer_id,)
        )
    return schluessel


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
                    passwort_wechseln, freigegeben)
                VALUES (%s, %s, 'admin', 'frei', %s, TRUE, now())
                RETURNING {_NUTZER_SPALTEN}""",
            (email, hashe_passwort(passwort), ADMIN_TARIF),
        ).fetchone()
    return _nutzer_aus_zeile(zeile), erzeugt
