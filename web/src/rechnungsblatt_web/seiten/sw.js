/* Rechnungsblatt — Service Worker.

   Grundsatz: Rechnungen entstehen im Kern auf dem Server (Ghostscript,
   Schrifteinbettung, §14-Prüfung). Nichts davon lässt sich im Browser
   nachbauen, also arbeitet diese App NICHT offline.

   Der Service Worker hat deshalb genau zwei Aufgaben:
     1. Oberfläche und Symbole vorhalten, damit die App sofort startet.
     2. Ohne Netz eine klare Auskunft geben statt einer Browser-Fehlerseite.

   Was hier bewusst NICHT passiert: Belege, Vorschauen und alles unter
   /api/ zwischenspeichern. Eine zwischengespeicherte Rechnung wäre ein
   falscher Beleg — schlimmer als gar keiner.
*/

const VERSION = "rb-2026-09-01-1";   // hochziehen, wenn Hülle oder Symbole sich ändern
const HUELLE = `huelle-${VERSION}`;

/* Nur die Hülle: Stilvorlage, Skript, Symbole, Offline-Hinweis. Seiten
   selbst nicht — sie hängen am angemeldeten Konto. */
const VORRAT = [
  "/seiten/basis.css",
  "/seiten/werkzeuge.js",
  /* Die Schriften liegen seit dem 01.09.2026 hier statt bei Google. Nur
     die lateinischen Schnitte in den Vorrat: latin-ext holt der Browser
     über die unicode-range nach, wenn ein Name ihn braucht. */
  "/seiten/schriften/schriften.css",
  "/seiten/schriften/fraunces-latin.woff2",
  "/seiten/schriften/instrument-sans-latin.woff2",
  "/seiten/schriften/spline-sans-mono-latin.woff2",
  "/seiten/ohne-netz.html",
  "/seiten/symbole/symbol-192.png",
  "/seiten/symbole/symbol-512.png",
  "/seiten/symbole/favicon.ico",
  "/manifest.webmanifest",
];

self.addEventListener("install", (ereignis) => {
  ereignis.waitUntil(
    caches.open(HUELLE)
      .then((c) => c.addAll(VORRAT))
      // Ein fehlender Eintrag darf die Installation nicht verhindern.
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (ereignis) => {
  ereignis.waitUntil(
    caches.keys()
      .then((namen) => Promise.all(
        namen.filter((n) => n !== HUELLE).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (ereignis) => {
  const anfrage = ereignis.request;
  if (anfrage.method !== "GET") return;

  const adresse = new URL(anfrage.url);
  if (adresse.origin !== self.location.origin) return;

  /* API, Belege und Vorschauen: immer frisch vom Server, nie aus dem
     Zwischenspeicher. Kein Netz heißt hier: kein Ergebnis. */
  if (adresse.pathname.startsWith("/api/")) return;

  /* Seiten: erst Netz, bei Ausfall der Offline-Hinweis. So sieht man nie
     einen veralteten Stand der Anwendung. */
  if (anfrage.mode === "navigate") {
    ereignis.respondWith(
      fetch(anfrage).catch(() =>
        caches.match("/seiten/ohne-netz.html").then(
          (a) => a || new Response("Keine Verbindung.", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          })
        )
      )
    );
    return;
  }

  /* Hülle (CSS, JS, Symbole): erst Zwischenspeicher für schnellen Start,
     im Hintergrund auffrischen. */
  if (adresse.pathname.startsWith("/seiten/") ||
      adresse.pathname === "/manifest.webmanifest") {
    ereignis.respondWith(
      caches.match(anfrage).then((gespeichert) => {
        const frisch = fetch(anfrage).then((antwort) => {
          if (antwort && antwort.ok) {
            const kopie = antwort.clone();
            caches.open(HUELLE).then((c) => c.put(anfrage, kopie));
          }
          return antwort;
        }).catch(() => gespeichert);
        return gespeichert || frisch;
      })
    );
  }
});
