/* Service worker — Prompts/39 §39.6 pwa_service / §39.9 (portals.pwa_push).
 * App-shell precache (versioned by the build hash from /api/v1/public/pwa-config), stale-while-revalidate for the
 * read APIs listed in `swr_routes` (TTL per data class), cache-first images, network-only writes, offline fallback
 * `/offline`, a background-sync queue for mark-read / acknowledge / feedback POSTs, navigation preload, web push
 * display + notification-click routing, and "update available" (the page posts `skip-waiting`).
 * Hand-written instead of vite-plugin-pwa (no extra dependency); Workbox strategies are mirrored one to one. */
const SHELL = 'shell-v1';
const API = 'api-v1';
const IMG = 'img-v1';
const QUEUE_DB = 'portal-sync';
let config = { version: 'dev', cache_ttl: {}, swr_routes: {}, precache: ['/', '/offline'], offline_route: '/offline' };

async function loadConfig() {
  try {
    const r = await fetch('/api/v1/public/pwa-config', { credentials: 'omit' });
    if (r.ok) config = { ...config, ...(await r.json()).data };
  } catch (e) { /* offline install: defaults */ }
  return config;
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    loadConfig().then((c) => caches.open(`${SHELL}-${c.version}`).then((cache) => cache.addAll(c.precache).catch(() => undefined))),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      await loadConfig();
      const keep = [`${SHELL}-${config.version}`, API, IMG];
      for (const k of await caches.keys()) if (!keep.includes(k)) await caches.delete(k);
      if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'skip-waiting') self.skipWaiting();
});

function ttlFor(pathname) {
  const hit = Object.keys(config.swr_routes || {}).find((p) => pathname.startsWith(p));
  return hit ? (config.cache_ttl || {})[config.swr_routes[hit]] || 3600 : null;
}

async function staleWhileRevalidate(event, ttl) {
  const cache = await caches.open(API);
  const cached = await cache.match(event.request);
  const fresh = fetch(event.request)
    .then(async (res) => {
      if (res.ok) {
        const copy = new Response(await res.clone().blob(), { status: res.status, headers: res.headers });
        copy.headers.set('sw-cached-at', String(Date.now()));
        await cache.put(event.request, copy);
      }
      return res;
    })
    .catch(() => cached);
  if (cached) {
    const at = Number(cached.headers.get('sw-cached-at') || 0);
    if (Date.now() - at < ttl * 1000) {
      event.waitUntil(fresh);
      return cached;
    }
  }
  return (await fresh) || new Response(JSON.stringify({ success: false, error: { code: 'OFFLINE', message: 'Offline' } }), { status: 503, headers: { 'Content-Type': 'application/json' } });
}

// ---- background sync (IndexedDB queue) ----
function db() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(QUEUE_DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('q', { autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function enqueue(request) {
  const body = await request.clone().text();
  const headers = {};
  request.headers.forEach((v, k) => { headers[k] = v; });
  const d = await db();
  await new Promise((res) => { const tx = d.transaction('q', 'readwrite'); tx.objectStore('q').add({ url: request.url, method: request.method, headers, body }); tx.oncomplete = res; });
  if (self.registration.sync) await self.registration.sync.register('portal-sync').catch(() => undefined);
}
async function flush() {
  const d = await db();
  const items = await new Promise((res) => {
    const out = [];
    const tx = d.transaction('q', 'readonly');
    tx.objectStore('q').openCursor().onsuccess = (e) => { const c = e.target.result; if (c) { out.push([c.key, c.value]); c.continue(); } else res(out); };
  });
  for (const [key, it] of items) {
    try {
      const r = await fetch(it.url, { method: it.method, headers: it.headers, body: it.body, credentials: 'include' });
      if (r.ok || r.status < 500) await new Promise((res) => { const tx = d.transaction('q', 'readwrite'); tx.objectStore('q').delete(key); tx.oncomplete = res; });
    } catch (e) { return; }
  }
}
self.addEventListener('sync', (event) => { if (event.tag === 'portal-sync') event.waitUntil(flush()); });
const SYNCABLE = [/\/api\/v1\/notifications\/mark-read$/, /\/api\/v1\/announcements\/[^/]+\/acknowledge$/, /\/api\/v1\/feedback$/];

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method !== 'GET') {
    if (SYNCABLE.some((rx) => rx.test(url.pathname))) {
      event.respondWith(
        fetch(req.clone()).catch(async () => {
          await enqueue(req);
          return new Response(JSON.stringify({ success: true, data: { queued: true }, message: 'Saved offline — will sync' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
        }),
      );
    }
    return; // other writes: network only
  }
  if (req.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const preload = await event.preloadResponse;
          if (preload) return preload;
          return await fetch(req);
        } catch (e) {
          const shell = await caches.match('/', { ignoreSearch: true });
          return shell || (await caches.match(config.offline_route)) || Response.error();
        }
      })(),
    );
    return;
  }
  if (url.pathname.startsWith('/api/')) {
    const ttl = ttlFor(url.pathname);
    if (ttl) event.respondWith(staleWhileRevalidate(event, ttl));
    return;
  }
  if (req.destination === 'image') {
    event.respondWith(
      caches.open(IMG).then(async (cache) => (await cache.match(req)) || fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; })),
    );
    return;
  }
  if (['script', 'style', 'font'].includes(req.destination)) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then(async (res) => { if (res.ok) (await caches.open(`${SHELL}-${config.version}`)).put(req, res.clone()); return res; })));
  }
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'SeptronUniverse', body: event.data && event.data.text() }; }
  const title = data.title || 'SeptronUniverse';
  const options = { body: data.body || '', icon: '/icons/icon.svg', badge: '/icons/icon.svg', tag: data.tag, renotify: Boolean(data.tag), data: { route: data.route || '/', category: data.category } };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const route = (event.notification.data && event.notification.data.route) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const client = clients.find((c) => 'focus' in c);
      if (client) { client.navigate(route); return client.focus(); }
      return self.clients.openWindow(route);
    }),
  );
});
