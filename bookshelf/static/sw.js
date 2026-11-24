/* Bookshelf service worker.
 *
 * Minimal and privacy-safe: it caches only versioned static assets under /static/
 * (app.css, app.js, reader + foliate modules, icons), which carry a ?v=<hash> and
 * so never change content under a given URL. It deliberately never caches HTML
 * pages, book files or API/sync responses, so nothing user- or auth-scoped is
 * stored, and offline navigation is not offered (yet). Its only other job is to
 * exist with a fetch handler, which is what makes the app installable.
 *
 * Bump CACHE to retire old entries (e.g. after replacing unversioned icons). */
const CACHE = "bookshelf-static-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/static/")) return; // never HTML, book files or sync endpoints

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      } catch (err) {
        return cached || Response.error();
      }
    })(),
  );
});
