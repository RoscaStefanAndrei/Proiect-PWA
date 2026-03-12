const CACHE_NAME = 'smartvest-v2';
const OFFLINE_URL = '/offline/';

// Only pre-cache the offline fallback page
const PRECACHE_URLS = [OFFLINE_URL];

// Install: cache offline page, then skip waiting
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// Activate: wipe old caches, claim clients
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

// Fetch: network-first for everything, cache as offline fallback only
self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Cache successful responses so they're available offline
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => {
        // Offline: try cache, fall back to offline page for navigations
        return caches.match(request).then(
          (cached) => cached || (request.mode === 'navigate' ? caches.match(OFFLINE_URL) : Response.error())
        );
      })
  );
});
