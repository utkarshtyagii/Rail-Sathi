const CACHE = 'rail-sathi-public-v2';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add('/static/offline.html')));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([
    caches.keys().then(keys => Promise.all(
      keys
        .filter(key => key.startsWith('rail-sathi-public-') && key !== CACHE)
        .map(key => caches.delete(key))
    )),
    self.clients.claim()
  ]));
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  const privatePaths = ['/auth', '/dashboard', '/bookings', '/payments', '/support'];
  const isPrivatePath = privatePaths.some(path => url.pathname === path || url.pathname.startsWith(`${path}/`));

  if (request.method !== 'GET' || request.mode !== 'navigate' || isPrivatePath) return;

  event.respondWith(
    fetch(request).catch(async () => {
      const offlinePage = await caches.match('/static/offline.html');
      return offlinePage || Response.error();
    })
  );
});
