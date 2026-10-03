/* Tenant Systems - Service Worker
 * Enables installability (PWA) and offline caching.
 */

const CACHE_NAME = "tenant-systems-v2";
const STATIC_CACHE = `${CACHE_NAME}-static`;
const RUNTIME_CACHE = `${CACHE_NAME}-runtime`;

// Core app shell (cached on install). Only public/static assets are included;
// authenticated pages redirect to login, and pre-caching a redirect would make
// the install step fail. Pages are cached at runtime instead (see fetch below).
const APP_SHELL = [
  "/static/manifest.webmanifest",
  "/static/css/app.css",
  "/static/js/pwa.js",
  "/static/img/logo.png",
  "/static/img/icons/icon-192x192.png",
  "/static/img/icons/icon-512x512.png",
];

// Install: Pre-cache the app shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// Activate: Clean up old caches and take control
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_NAME) && key !== STATIC_CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// Fetch: Network-first for navigations & pages, cache-first for static assets
self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Only handle GET requests
  if (request.method !== "GET") return;

  // Skip cross-origin requests (e.g., CDN for Bootstrap) 
  // unless we want to cache them; keep it simple and only cache same-origin.
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Navigation requests (pages): network-first, fallback to cache
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Cache a copy of successful pages only
          if (response.ok) {
            const copy = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches
            .match(request)
            .then((cached) => cached || offlineResponse())
        )
    );
    return;
  }

  // Static assets (images, CSS): cache-first with runtime caching
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        // Refresh the cache for static assets in the background
        if (url.pathname.startsWith("/static/")) {
          fetch(request)
            .then((response) => {
              if (response.ok) {
                caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, response));
              }
            })
            .catch(() => {});
        }
        return cached;
      }
      return fetch(request)
        .then((response) => {
          // Cache successful responses to static assets
          if (response.ok && (url.pathname.startsWith("/static/") || response.type === "basic")) {
            const copy = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => {
          // Fallback for images
          if (request.destination === "image") {
            return caches.match("/static/img/logo.png");
          }
          return new Response("Offline", { status: 503, statusText: "Offline" });
        });
    })
  );
});

// Message handling for skipWaiting (when new version is available)
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// Simple offline fallback page for navigation requests we have no cache for.
function offlineResponse() {
  return new Response(
    `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offline | Tenant Systems</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;
margin:0;background:#f8f9fa;color:#212529;text-align:center;padding:24px}
.wrap{max-width:420px}h1{font-size:1.4rem;margin-bottom:.5rem}
p{color:#6c757d}button{margin-top:1rem;padding:.5rem 1rem;border:0;border-radius:.375rem;
background:#0d6efd;color:#fff;font-size:1rem;cursor:pointer}</style></head>
<body><div class="wrap"><h1>You're offline</h1>
<p>Tenant Systems can't reach the network right now. Check your connection and try again.</p>
<button onclick="location.reload()">Retry</button></div></body></html>`,
    {
      status: 503,
      statusText: "Offline",
      headers: { "Content-Type": "text/html; charset=utf-8" },
    }
  );
}
