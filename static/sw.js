/* Tenant Systems - Service Worker
 * Enables installability (PWA) and offline caching.
 */

const CACHE_NAME = "tenant-systems-v1";
const STATIC_CACHE = `${CACHE_NAME}-static`;
const RUNTIME_CACHE = `${CACHE_NAME}-runtime`;

// Core app shell (cached on install)
const APP_SHELL = [
  "/",
  "/static/manifest.webmanifest",
  "/static/img/logo.png",
  "/static/css/app.css",
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
          // Cache a copy of the page
          const copy = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() =>
          caches
            .match(request)
            .then((cached) => cached || caches.match("/"))
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
