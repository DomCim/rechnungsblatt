/* Rechnungsblatt — gemeinsame Seiten-Werkzeuge: Sprache (DE/EN),
   Befund-Übersetzung, kleine Helfer. Kein Framework, kein Build. */

window.RB = (function () {
  "use strict";

  var gemeinsam = {
    de: {
      navEinrichtung: "Einrichtung",
      navRechnung: "Neue Rechnung",
      speichern: "Speichern",
      gespeichert: "Gespeichert ✓",
      laedt: "Einen Moment …",
      fehlerAllgemein: "Das hat nicht geklappt. Bitte erneut versuchen.",
      befunde: {
        S1: "Firmierung fehlt.",
        S2: "Anschrift des Rechnungsstellers ist unvollständig.",
        S3: "Steuernummer oder USt-IdNr. ist Pflicht.",
        S4: "USt-IdNr. hat kein gültiges Format.",
        S5: "IBAN fehlt.",
        S6: "IBAN ist ungültig (Prüfsumme).",
        E1: "Name des Empfängers fehlt.",
        E2: "Anschrift des Empfängers ist unvollständig.",
        R1: "Rechnungsnummer fehlt.",
        R2: "Rechnungsdatum fehlt.",
        R3: "Leistungsdatum oder Leistungszeitraum ist Pflicht.",
        R4: "Leistungszeitraum: Beginn liegt nach Ende.",
        P0: "Mindestens eine Position ist Pflicht.",
        P1: "Bezeichnung fehlt.",
        P2: "Menge muss größer 0 sein.",
        P3: "Einheit fehlt.",
        P4: "Einzelpreis darf nicht negativ sein.",
        K1: "Als Kleinunternehmer (§ 19 UStG) dürfen Sie keine Umsatzsteuer ausweisen — Steuersatz „§ 19 UStG“ wählen.",
        K2: "„§ 19 UStG“ ist nur möglich, wenn die Stammdaten Kleinunternehmer ausweisen.",
        RC1: "Reverse Charge braucht die USt-IdNr. des Empfängers.",
        RC2: "Reverse Charge braucht Ihre eigene USt-IdNr. (Stammdaten).",
        IG1: "Innergemeinschaftliche Lieferung braucht die USt-IdNr. beider Seiten.",
        G1: "Gutschrift/Korrektur braucht die Nummer der Ursprungsrechnung.",
        X1: "XRechnung braucht eine Leitweg-ID.",
        X2: "XRechnung braucht Kontaktname, Telefon und E-Mail (Stammdaten).",
        X3: "XRechnung braucht die E-Mail-Adresse des Empfängers."
      }
    },
    en: {
      navEinrichtung: "Setup",
      navRechnung: "New invoice",
      speichern: "Save",
      gespeichert: "Saved ✓",
      laedt: "One moment …",
      fehlerAllgemein: "That didn’t work. Please try again.",
      befunde: {
        S1: "Company name is missing.",
        S2: "Your address is incomplete.",
        S3: "Tax number or VAT ID is required.",
        S4: "VAT ID has an invalid format.",
        S5: "IBAN is missing.",
        S6: "IBAN is invalid (checksum).",
        E1: "Recipient name is missing.",
        E2: "Recipient address is incomplete.",
        R1: "Invoice number is missing.",
        R2: "Invoice date is missing.",
        R3: "Delivery date or period is required.",
        R4: "Delivery period: start is after end.",
        P0: "At least one line item is required.",
        P1: "Description is missing.",
        P2: "Quantity must be greater than 0.",
        P3: "Unit is missing.",
        P4: "Unit price must not be negative.",
        K1: "As a small business (§ 19 UStG) you must not charge VAT — choose the “§ 19 UStG” rate.",
        K2: "“§ 19 UStG” is only possible if your master data marks you as a small business.",
        RC1: "Reverse charge requires the recipient’s VAT ID.",
        RC2: "Reverse charge requires your own VAT ID (setup).",
        IG1: "Intra-community supply requires both VAT IDs.",
        G1: "Credit note/correction requires the original invoice number.",
        X1: "XRechnung requires a Leitweg-ID.",
        X2: "XRechnung requires contact name, phone and e-mail (setup).",
        X3: "XRechnung requires the recipient’s e-mail address."
      }
    }
  };

  var sprache = "de";
  try {
    var gespeichert = localStorage.getItem("rechnungsblatt.sprache");
    if (gespeichert === "en" || gespeichert === "de") sprache = gespeichert;
  } catch (fehler) { /* Speicher nicht verfügbar */ }

  var seitentexte = { de: {}, en: {} };
  var beiWechsel = [];

  function t(schluessel) {
    return seitentexte[sprache][schluessel] || gemeinsam[sprache][schluessel] || schluessel;
  }

  function befundText(code, ersatz) {
    return gemeinsam[sprache].befunde[code] || ersatz || code;
  }

  function uebersetze() {
    document.documentElement.lang = sprache;
    var elemente = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < elemente.length; i++) {
      elemente[i].textContent = t(elemente[i].getAttribute("data-i18n"));
    }
    var platzhalter = document.querySelectorAll("[data-i18n-platzhalter]");
    for (var p = 0; p < platzhalter.length; p++) {
      platzhalter[p].setAttribute(
        "placeholder", t(platzhalter[p].getAttribute("data-i18n-platzhalter"))
      );
    }
    var knoepfe = document.querySelectorAll(".sprachen button");
    for (var k = 0; k < knoepfe.length; k++) {
      knoepfe[k].setAttribute(
        "aria-pressed", String(knoepfe[k].getAttribute("data-sprache") === sprache)
      );
    }
    for (var w = 0; w < beiWechsel.length; w++) beiWechsel[w](sprache);
  }

  function starte(texte) {
    if (texte) seitentexte = texte;
    var umschalter = document.querySelector(".sprachen");
    if (umschalter) {
      umschalter.addEventListener("click", function (ereignis) {
        var knopf = ereignis.target.closest("button[data-sprache]");
        if (!knopf) return;
        sprache = knopf.getAttribute("data-sprache");
        try { localStorage.setItem("rechnungsblatt.sprache", sprache); }
        catch (fehler) { /* Speicher nicht verfügbar */ }
        uebersetze();
      });
    }
    uebersetze();
  }

  async function api(pfad, optionen) {
    var antwort = await fetch(pfad, optionen);
    var daten = null;
    var typ = antwort.headers.get("content-type") || "";
    if (typ.indexOf("application/json") >= 0) daten = await antwort.json();
    return { ok: antwort.ok, status: antwort.status, daten: daten, antwort: antwort };
  }

  function zeigeBefunde(befunde, formular) {
    var kaestchen = formular.querySelectorAll(".feld.hat-fehler");
    for (var i = 0; i < kaestchen.length; i++) kaestchen[i].classList.remove("hat-fehler");
    var uebrig = [];
    for (var b = 0; b < befunde.length; b++) {
      var befund = befunde[b];
      var feld = formular.querySelector('[data-feld="' + befund.feld + '"]');
      if (!feld) {
        // Positionsfelder: rechnung.positionen[2] → Sammelanzeige je Code
        var basis = befund.feld.replace(/\[\d+\]$/, "");
        feld = formular.querySelector('[data-feld="' + basis + '"]');
      }
      if (feld) {
        feld.classList.add("hat-fehler");
        var meldung = feld.querySelector(".fehler");
        if (meldung) meldung.textContent = befundText(befund.code, befund.text);
      } else {
        uebrig.push(befundText(befund.code, befund.text));
      }
    }
    return uebrig;
  }

  return {
    t: t,
    starte: starte,
    api: api,
    befundText: befundText,
    zeigeBefunde: zeigeBefunde,
    sprache: function () { return sprache; },
    beiSprachwechsel: function (fn) { beiWechsel.push(fn); }
  };
})();
