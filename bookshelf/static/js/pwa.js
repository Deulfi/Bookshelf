// Registers the service worker so Bookshelf can be installed as a PWA (standalone,
// no browser URL bar). The worker itself only caches static assets; see sw.js.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
