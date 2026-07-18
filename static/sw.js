/* Humiley Portal service worker — installability + fast repeat loads + offline shell.
   Strategy: never cache /api/ (live data); HTML is STALE-WHILE-REVALIDATE (the cached shell
   paints instantly — the single biggest "app feels slow to open on 4G" fix — while the network
   copy refreshes the cache in the background; the in-app appVersion check reloads to a new
   deploy within seconds of focus); static assets + CDN libs are cache-first. */
const CACHE = 'hml-pwa-v61';
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
  // The Procurement app is a SEPARATE app served under /procurement (Next.js, its own routing + assets).
  // This SW's scope is '/', so WITHOUT this it intercepts every /procurement navigation — INCLUDING the
  // embed iframe's load — and (via the navigate branch below) serves the PORTAL shell instead of letting
  // the request reach the Procurement container. That renders the portal-inside-the-portal and trips the
  // "Procurement service isn't running" message even though the container is perfectly healthy. Never
  // touch anything under /procurement — let it go straight to the network (Caddy routes it to the app).
  if (url.origin === self.location.origin && (url.pathname === '/procurement' || url.pathname.startsWith('/procurement/'))) return;

  if (req.mode === 'navigate') {                          // HTML: stale-while-revalidate
    e.respondWith(
      caches.match('/').then(cached => {
        const net = fetch(req).then(r => {
          // Only cache a HEALTHY same-origin shell — a deploy-window 502 or a captive-portal page
          // must never become the offline fallback ("blank/stuck app when coming back on mobile").
          if (r.ok && r.type === 'basic') { const rc = r.clone(); caches.open(CACHE).then(c => c.put('/', rc)).catch(() => {}); }
          return r;
        }).catch(() => cached);
        return cached || net;                             // cached shell paints instantly; network refreshes for next open
      })
    );
    return;
  }

  e.respondWith(                                          // assets + CDN libs: cache-first, then network
    caches.match(req).then(hit => hit || fetch(req).then(r => {
      if (r.ok || r.type === 'opaque') { const rc = r.clone(); caches.open(CACHE).then(c => c.put(req, rc)).catch(() => {}); }   // opaque = no-cors CDN libs
      return r;
    }).catch(() => hit))
  );
});

/* ── Web Push: show the OS notification, and focus/open the app when tapped ── */
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; }
  catch (_) { d = { body: (e.data && e.data.text && e.data.text()) || '' }; }
  const title = d.title || 'Humiley Portal';
  const opts = {
    body: d.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    data: { url: d.url || '/' },
    tag: d.tag || undefined,
    renotify: !!d.tag,
    vibrate: [80, 40, 80]
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  let url = (e.notification.data && e.notification.data.url) || '/';
  // Defence in depth: only ever open a SAME-ORIGIN path (the server already enforces this).
  if (typeof url !== 'string' || !url.startsWith('/') || url.startsWith('//')) url = '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const match = list.find(c => { try { return new URL(c.url).pathname === url; } catch (_) { return false; } });
      if (match && 'focus' in match) return match.focus();
      for (const c of list) {
        if ('focus' in c) { try { if (c.navigate) c.navigate(url).catch(() => {}); } catch (_) {} return c.focus(); }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
