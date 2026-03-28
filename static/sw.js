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

// Push: show notification from server payload
self.addEventListener('push', (event) => {
  let data = { title: 'SmartVest', message: '', link: '/' };
  try { data = event.data.json(); } catch (e) { /* ignore */ }

  event.waitUntil(
    self.registration.showNotification(data.title || 'SmartVest', {
      body: data.message || '',
      icon: '/static/img/icon-192.png',
      badge: '/static/img/icon-192.png',
      data: { url: data.link || '/' },
      vibrate: [200, 100, 200],
    })
  );
});

// Notification click: focus or open the relevant page
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
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
