/* Service worker: web push display + notification click routing (portals.pwa_push). Offline caching arrives in Phase 39. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'SeptronUniverse', body: event.data && event.data.text() }; }
  const title = data.title || 'SeptronUniverse';
  const options = { body: data.body || '', icon: '/icons/icon.svg', badge: '/icons/icon.svg', data: { route: data.route || '/' } };
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
