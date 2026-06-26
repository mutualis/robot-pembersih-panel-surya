/*
 * Service Worker - Solar Panel Cleaner PWA
 *
 * Strategi cache aman untuk panel kontrol real-time:
 *  - API, stream video, dan WebSocket TIDAK PERNAH di-cache (selalu network).
 *  - Aset statis (CSS/JS/ikon) pakai stale-while-revalidate (cepat + auto-update).
 *  - Navigasi halaman pakai network-first + fallback cache (bisa dibuka offline
 *    sebagai shell; data live mengisi saat kembali online).
 *
 * Naikkan CACHE_VERSION setiap kali ingin memaksa pembaruan aset.
 */
const CACHE_VERSION = "v1";
const STATIC_CACHE = `spc-static-${CACHE_VERSION}`;
const PAGE_CACHE = `spc-pages-${CACHE_VERSION}`;

// Aset inti yang di-precache agar app shell bisa muncul saat offline.
const PRECACHE_URLS = [
  "/",
  "/static/css/main.css",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/favicon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== STATIC_CACHE && k !== PAGE_CACHE)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Hanya tangani GET; biarkan POST/PUT/DELETE lewat apa adanya.
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Lewati request lintas-origin.
  if (url.origin !== self.location.origin) return;

  // JANGAN cache API maupun stream video — harus selalu data terbaru.
  if (url.pathname.startsWith("/api/")) return;

  // Aset statis → stale-while-revalidate.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(req).then((cached) => {
          const network = fetch(req)
            .then((res) => {
              if (res && res.status === 200) cache.put(req, res.clone());
              return res;
            })
            .catch(() => cached);
          return cached || network;
        })
      )
    );
    return;
  }

  // Navigasi halaman → network-first, fallback ke cache (shell offline).
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(PAGE_CACHE).then((cache) => cache.put(req, copy));
          return res;
        })
        .catch(() =>
          caches
            .match(req)
            .then((cached) => cached || caches.match("/"))
        )
    );
    return;
  }
});
