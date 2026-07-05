/* Humiley Portal service worker — installability + fast repeat loads + offline shell.
   Strategy: never cache /api/ (live data); HTML is network-first (deploys show immediately,
   last shell served offline); static assets + CDN libs are cache-first. */
const CACHE = 'hml-pwa-v2';
const SHELL = ['/', '/static/manifest.webmanifest', '/static/icons/icon-192.png', '/static/icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(SHELL.map(u => new Request(u, { cache: 'reload' }))))
      .catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;                       // POST/PATCH/DELETE go straight to network
  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) return;   // never cache live data

  if (req.mode === 'navigate') {                          // HTML: network-first, fall back to cached shell
    e.respondWith(
      fetch(req)
        .then(r => { const rc = r.clone(); caches.open(CACHE).then(c => c.put('/', rc)); return r; })
        .catch(() => caches.match('/') || caches.match(req))
    );
    return;
  }

  e.respondWith(                                          // assets + CDN libs: cache-first, then network
    caches.match(req).then(hit => hit || fetch(req).then(r => {
      const rc = r.clone();
      caches.open(CACHE).then(c => c.put(req, rc)).catch(() => {});
      return r;
    }).catch(() => hit))
  );
});
