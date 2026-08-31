/* Rechnungsblatt — gemeinsame Seiten-Werkzeuge: Sprache (DE/EN),
   Befund-Übersetzung, kleine Helfer. Kein Framework, kein Build. */

window.RB = (function () {
  "use strict";

  var gemeinsam = {
    de: {
      navEinrichtung: "Einrichtung",
      // Kurzformen fuer die Leiste am unteren Rand: dort hat ein
      // Eintrag rund 70 px, "Neue Rechnung" passt da nicht hinein.
      navKurzEinrichtung: "Einrichtung", navKurzRechnung: "Rechnung",
      navKurzStamm: "Stammdaten", navKurzAblage: "Ablage",
      navKurzKonto: "Konto", navKurzVerwaltung: "Verwaltung",
      navRechnung: "Neue Rechnung",
      navAblage: "Ablage",
      navStamm: "Stammdaten",
      navKonto: "Konto",
      navVerwaltung: "Verwaltung",
      abmelden: "Abmelden",
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
        P5: "Einzelpreis darf höchstens zwei Nachkommastellen haben — sonst widersprechen sich Preis und Betrag im XML. Bei krummen Preisen je Einheit besser die Menge anders wählen.",
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
      navKurzEinrichtung: "Setup", navKurzRechnung: "Invoice",
      navKurzStamm: "Master data", navKurzAblage: "Archive",
      navKurzKonto: "Account", navKurzVerwaltung: "Admin",
      navRechnung: "New invoice",
      navAblage: "Archive",
      navStamm: "Master data",
      navKonto: "Account",
      navVerwaltung: "Administration",
      abmelden: "Sign out",
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
        P5: "Unit price may have at most two decimal places — otherwise price and amount contradict each other in the XML. For awkward unit prices, choose a different quantity.",
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

  // --- Navigation ----------------------------------------------------
  // Baut aus den vorhandenen Reitern drei Formen: Hamburger mit
  // Ueberblende (ueberall), schmale Kopfleiste (Handy) und eine Leiste am
  // unteren Rand (nur in der installierten App).
  //
  // Bewusst hier statt in jeder Seite: Das Markup der neun Seiten bleibt
  // unangetastet, und eine Aenderung wirkt sofort ueberall.

  // Sinnbilder fuer die untere Leiste. Duenne Striche, keine Flaechen —
  // dieselbe Sprache wie der Rest der Oberflaeche.
  var ZEICHEN = {
    "/app/einrichtung": "M4 7h16M4 12h16M4 17h10",
    "/app/rechnung": "M6 3h9l5 5v13H6zM15 3v5h5M9 13h7M9 17h5",
    "/app/stamm": "M4 6h16M4 12h16M4 18h9M18 15v6M15 18h6",
    "/app/ablage": "M3 7h18v12H3zM3 7l2-3h6l2 3",
    "/app/konto": "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
    // Schieberegler fuer die Verwaltung -- sie erscheint nur bei Admins.
    "/app/verwaltung": "M4 7h6M14 7h6M4 17h10M18 17h2M12 5v4M16 15v4"
  };

  // Bei sechs Eintraegen wird die Leiste eng. Abmelden gehoert ohnehin
  // nicht dorthin -- es steht in der Ueberblende und im Konto.
  var NICHT_IN_LEISTE = ["#"];

  function kurzName(verweis) {
    // Die Leiste unten hat je Eintrag rund 70 px — der volle Name passt
    // dort nicht. Der Schluessel steht in den Seitentexten.
    var kurz = { navRechnung: "navKurzRechnung", navEinrichtung: "navKurzEinrichtung",
                 navStamm: "navKurzStamm", navAblage: "navKurzAblage",
                 navKonto: "navKurzKonto",
                 navVerwaltung: "navKurzVerwaltung" };
    var schluessel = verweis.getAttribute("data-i18n");
    var ersatz = kurz[schluessel];
    var text = ersatz ? t(ersatz) : "";
    return text && text !== ersatz ? text : verweis.textContent.trim();
  }

  function baueNavigation() {
    var reiter = document.querySelector("nav.reiter");
    var zeile = null;
    // Mehrfach aufrufbar: kopfKonto() haengt Verwaltung und Abmelden erst
    // nachtraeglich an die Reiter -- ohne Neuaufbau fehlten beide in
    // Ueberblende und Tableiste, und der Adminbereich waere in der App
    // ueberhaupt nicht erreichbar gewesen.
    var altSchicht = document.querySelector(".menue-schicht");
    if (altSchicht) altSchicht.remove();
    var altLeiste = document.querySelector(".kopfleiste");
    var altTab = document.querySelector(".tableiste");
    if (altTab) altTab.remove();
    var altKnopf = document.querySelector("header.kopf .menue-knopf");
    if (altKnopf) altKnopf.remove();
    var kopf = document.querySelector("header.kopf");
    if (!reiter || !kopf) return;
    var verweise = Array.prototype.slice.call(reiter.querySelectorAll("a"));
    if (!verweise.length) return;

    // --- Ueberblende ---
    var schicht = document.createElement("nav");
    schicht.className = "menue-schicht";
    schicht.id = "menueSchicht";
    schicht.setAttribute("aria-label", "Hauptnavigation");
    verweise.forEach(function (a) { schicht.appendChild(a.cloneNode(true)); });
    document.body.appendChild(schicht);

    // --- Knopf ---
    var knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "menue-knopf";
    knopf.setAttribute("aria-expanded", "false");
    knopf.setAttribute("aria-controls", "menueSchicht");
    knopf.setAttribute("aria-label", "Menü");
    knopf.innerHTML = "<i></i><i></i><i></i>";

    function umschalten(offen) {
      knopf.setAttribute("aria-expanded", offen ? "true" : "false");
      schicht.classList.toggle("offen", offen);
      // Solange die Ueberblende offen ist, soll die Seite dahinter nicht
      // mitscrollen.
      document.body.style.overflow = offen ? "hidden" : "";
    }
    knopf.addEventListener("click", function () {
      umschalten(knopf.getAttribute("aria-expanded") !== "true");
    });
    schicht.addEventListener("click", function (ereignis) {
      // Klick ins Leere schliesst; ein Verweis navigiert ohnehin.
      if (ereignis.target === schicht) umschalten(false);
    });
    document.addEventListener("keydown", function (ereignis) {
      if (ereignis.key === "Escape") umschalten(false);
    });

    // --- Schmale Kopfleiste (nur am Handy sichtbar, per CSS) ---
    var leiste = altLeiste || document.createElement("div");
    leiste.className = "kopfleiste";
    leiste.textContent = "";
    // Das Zeichen statt des Namens: In einer 42 px hohen Leiste braucht
    // "Rechnungsblatt" den halben Platz, den der Seitenname noetiger hat.
    // Als SVG nachgezeichnet, nicht als PNG -- so bleibt es auf jedem
    // Bildschirm scharf und nimmt die Textfarbe an.
    var marke = document.createElement("a");
    marke.className = "marke zeichen";
    marke.href = "/app/rechnung";
    marke.setAttribute("aria-label", "Rechnungsblatt");
    marke.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        // Der Bogen, leicht geneigt wie auf der Startseite.
        '<g transform="rotate(-2 12 12)">' +
          '<rect x="5" y="3" width="14" height="18" rx="1.5" ' +
                'fill="currentColor" opacity="0.14"/>' +
          '<rect x="5" y="3" width="14" height="4" rx="1.5" ' +
                'fill="currentColor" opacity="0.55"/>' +
          '<rect x="7.5" y="10" width="7" height="1.4" rx="0.7" fill="currentColor"/>' +
          '<rect x="7.5" y="13" width="5" height="1.4" rx="0.7" fill="currentColor"/>' +
          // Die Summenzeile in Stempelrot -- der einzige Farbtupfer.
          '<rect x="11" y="16.6" width="5.5" height="1.6" rx="0.8" ' +
                'fill="var(--akzent)"/>' +
        '</g>' +
      '</svg>';
    var wo = document.createElement("div");
    wo.className = "wo";
    var laufend = verweise.filter(function (a) {
      return a.getAttribute("aria-current") === "page";
    })[0];
    wo.textContent = laufend ? laufend.textContent.trim() : "";
    // Beim Sprachwechsel mitziehen.
    beiWechsel.push(function () {
      if (laufend) wo.textContent = laufend.textContent.trim();
    });
    leiste.appendChild(marke);
    leiste.appendChild(wo);
    // Am Handy ist der ganze Kopf ausgeblendet -- die Sprachumschaltung
    // muss deshalb mit in die Leiste, sonst waere sie dort nicht mehr
    // erreichbar. Am Rechner bleibt sie, wo sie war.
    var sprachen = kopf.querySelector(".sprachen");
    var schmal = window.matchMedia("(max-width: 700px)");
    function sprachenLage() {
      if (!sprachen) return;
      if (schmal.matches) leiste.insertBefore(sprachen, knopf);
      else if (zeile) zeile.insertBefore(sprachen, zeile.firstChild);
    }
    leiste.appendChild(knopf);
    if (!altLeiste) kopf.parentNode.insertBefore(leiste, kopf);

    // Am Rechner steht der Knopf neben der Sprachumschaltung; dort ist
    // die Kopfleiste ausgeblendet, der Knopf aber weiterhin noetig.
    sprachenLage();
    schmal.addEventListener("change", sprachenLage);
    zeile = kopf.querySelector(".zeile");
    if (zeile) {
      var zweiter = knopf.cloneNode(true);
      zweiter.addEventListener("click", function () {
        umschalten(knopf.getAttribute("aria-expanded") !== "true");
      });
      // Beide Knoepfe zeigen denselben Zustand.
      var beobachter = new MutationObserver(function () {
        zweiter.setAttribute("aria-expanded", knopf.getAttribute("aria-expanded"));
      });
      beobachter.observe(knopf, { attributes: true, attributeFilter: ["aria-expanded"] });
      zeile.appendChild(zweiter);
      // Nur am Rechner: am Handy traegt ihn die Kopfleiste.
      zweiter.style.display = "";
      var schmal = window.matchMedia("(max-width: 700px)");
      function knopfLage() { zweiter.style.display = schmal.matches ? "none" : ""; }
      knopfLage();
      schmal.addEventListener("change", knopfLage);
    }

    // --- Leiste unten (CSS zeigt sie nur in der installierten App) ---
    var unten = document.createElement("nav");
    unten.className = "tableiste";
    unten.setAttribute("aria-label", "Bereiche");
    verweise.forEach(function (a) {
      var ziel = a.getAttribute("href");
      if (NICHT_IN_LEISTE.indexOf(ziel) >= 0) return;
      var eintrag = document.createElement("a");
      eintrag.href = ziel;
      if (a.getAttribute("aria-current")) eintrag.setAttribute("aria-current", "page");
      var pfad = ZEICHEN[ziel];
      if (pfad) {
        eintrag.innerHTML =
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<path d="' + pfad + '"/></svg>';
      }
      var text = document.createElement("span");
      text.textContent = kurzName(a);
      beiWechsel.push(function () { text.textContent = kurzName(a); });
      eintrag.appendChild(text);
      unten.appendChild(eintrag);
    });
    document.body.appendChild(unten);
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
    baueNavigation();
  }

  // --- Sitzung überlebt den Neustart einer Web-App -------------------
  // iOS gibt einer zum Startbildschirm hinzugefügten Seite einen eigenen
  // Cookie-Speicher und räumt ihn beim Schließen häufig ab. Der Schlüssel
  // liegt deshalb zusätzlich lokal und wird nachgereicht.
  // Nur aktiv, wenn der Server ihn beim Anmelden mitliefert
  // (SITZUNG_KOPFZEILE=1) — im Produktivbetrieb über HTTPS nicht nötig.
  var SPEICHER = "rb_sitzung";

  function sitzungLesen() {
    try { return localStorage.getItem(SPEICHER); } catch (e) { return null; }
  }
  function sitzungMerken(schluessel) {
    try {
      if (schluessel) localStorage.setItem(SPEICHER, schluessel);
      else localStorage.removeItem(SPEICHER);
    } catch (e) { /* privater Modus: dann eben nicht */ }
  }
  function cookieGesetzt() {
    return document.cookie.indexOf(SPEICHER + "=") >= 0;
  }

  // Seitenaufrufe tragen keine Kopfzeile — das Cookie aus dem Speicher
  // wiederherstellen, bevor die erste Anfrage rausgeht.
  (function cookieWiederherstellen() {
    var schluessel = sitzungLesen();
    if (schluessel && !cookieGesetzt()) {
      document.cookie = SPEICHER + "=" + schluessel +
        "; path=/; max-age=" + (30 * 24 * 3600) + "; samesite=lax";
    }
  })();

  async function api(pfad, optionen) {
    optionen = optionen || {};
    var schluessel = sitzungLesen();
    if (schluessel && !cookieGesetzt()) {
      optionen.headers = Object.assign({}, optionen.headers,
        { "X-Rb-Sitzung": schluessel });
    }
    var antwort = await fetch(pfad, optionen);
    var daten = null;
    var typ = antwort.headers.get("content-type") || "";
    if (typ.indexOf("application/json") >= 0) daten = await antwort.json();
    // Beim Anmelden liefert der Server den Schlüssel mit; beim Abmelden
    // verschwindet er wieder.
    if (daten && daten.sitzung) sitzungMerken(daten.sitzung);
    if (daten && daten.abgemeldet) sitzungMerken(null);
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

  /* Ergänzt die Reiterleiste um Verwaltung (nur Admins) und Abmelden.
     Liefert den angemeldeten Nutzer, damit Seiten damit weiterarbeiten können. */
  async function kopfKonto() {
    var leiste = document.querySelector("nav.reiter");
    var antwort = await api("/api/ich");
    if (!antwort.ok || !leiste) return antwort.ok ? antwort.daten : null;
    var person = antwort.daten;
    var neuAufbauen = false;
    if (person.rolle === "admin" && !leiste.querySelector('a[href="/app/verwaltung"]')) {
      var verweis = document.createElement("a");
      verweis.href = "/app/verwaltung";
      verweis.setAttribute("data-i18n", "navVerwaltung");
      verweis.textContent = t("navVerwaltung");
      leiste.appendChild(verweis);
      neuAufbauen = true;
    }
    if (!leiste.querySelector("[data-abmelden]")) {
      var knopf = document.createElement("a");
      knopf.href = "#";
      knopf.setAttribute("data-abmelden", "");
      knopf.setAttribute("data-i18n", "abmelden");
      knopf.textContent = t("abmelden");
      knopf.addEventListener("click", async function (ereignis) {
        ereignis.preventDefault();
        await api("/api/abmelden", { method: "POST" });
        window.location.href = "/";
      });
      leiste.appendChild(knopf);
      neuAufbauen = true;
    }
    // Erst jetzt stehen alle Reiter fest -- Ueberblende und Tableiste
    // muessen sie uebernehmen, sonst fehlt in der App der Weg in die
    // Verwaltung und zum Abmelden.
    if (neuAufbauen) baueNavigation();
    return person;
  }

  // Zwei Handgriffe, die jede Seite braucht. `el` stand sechsmal
  // wortgleich in den Seiten, `euro` dreimal — Kopien, die beim naechsten
  // Waehrungsformat alle einzeln gefunden werden muessten.
  function el(kennung) { return document.getElementById(kennung); }

  function euro(cent) {
    return (cent / 100).toLocaleString(sprache === "en" ? "en-GB" : "de-DE", {
      style: "currency", currency: "EUR"
    });
  }

  return {
    t: t,
    el: el,
    euro: euro,
    starte: starte,
    api: api,
    kopfKonto: kopfKonto,
    befundText: befundText,
    zeigeBefunde: zeigeBefunde,
    sprache: function () { return sprache; },
    beiSprachwechsel: function (fn) { beiWechsel.push(fn); }
  };
})();
