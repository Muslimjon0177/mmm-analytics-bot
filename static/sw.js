const CACHE_NAME = 'mmm-analytics-v9';
const SHELL_URLS = [
  '/static/css/app.css?v=7',
  '/static/js/app.js?v=9',
  '/static/icon.svg',
  '/manifest.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then((c) => c.addAll(SHELL_URLS))
      .catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }
  // API va HTML sahifalar uchun doim tarmoqdan (Network-First)
  if (url.pathname.startsWith('/api/') || url.pathname === '/' || url.pathname === '/install') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }
  // Statik CSS/JS/ikonkalar uchun Cache-First + fonda yangilash
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
    e.respondWith(
      caches.match(e.request).then((cached) => {
        const net = fetch(e.request).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put(e.request, copy)).catch(() => {});
          }
          return resp;
        }).catch(() => cached);
        return cached || net;
      })
    );
  }
});
