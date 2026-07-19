/* Humiley Portal service worker — installability + fast repeat loads + offline shell.
   Strategy: never cache /api/ (live data); HTML is NETWORK-FIRST WITH A TIMEOUT — a fresh deploy is
   served immediately when the network responds in time (fixes the recurring "stale code after deploy"
   where the old shell painted first and only the SECOND open was current), and the cached shell is the
   fallback when the network is offline OR slower than the timeout (keeps the "fast to open on 4G"
   behaviour + offline use). Every successful load refreshes the cached shell, so the fallback is always
   the last-known-good version; static assets + CDN libs stay cache-first. */
const CACHE = 'hml-pwa-v71';
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

  if (req.mode === 'navigate') {                          // HTML: network-first with a timeout fallback
    e.respondWith((async () => {
      // Always kick off the network fetch AND always let it refresh the cache on success — even if the
      // race below returns the cached shell first, this keeps the offline fallback current. Only a
      // HEALTHY same-origin shell is cached: a deploy-window 502 or a captive-portal page must never
      // become the offline fallback ("blank/stuck app when coming back on mobile").
      const netP = fetch(req).then(r => {
        if (r && r.ok && r.type === 'basic') { const rc = r.clone(); caches.open(CACHE).then(c => c.put('/', rc)).catch(() => {}); return r; }
        // A non-ok / non-basic navigation (a deploy-window 502, a captive-portal page) must NOT be
        // shown — throw so the catch below serves the last-known-good cached shell instead.
        throw new Error('sw-bad-nav');
      });
      try {
        // Fresh shell if the network answers within the budget (a 304 revalidation is tiny, so this
        // wins on any healthy connection); otherwise fall through to the cached shell.
        return await Promise.race([
          netP,
          new Promise((_, reject) => setTimeout(() => reject(new Error('sw-nav-timeout')), 2500)),
        ]);
      } catch (_) {
        return (await caches.match('/')) || netP;         // slow/offline -> last-known-good shell
      }
    })());
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
