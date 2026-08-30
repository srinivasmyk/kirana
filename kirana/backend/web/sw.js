// Minimal service worker. Its only job is making the app installable to the
// home screen and surviving a brief network blip on the shell.
//
// Deliberately does NOT cache /search responses: a price comparison app that
// shows you yesterday's prices is worse than one that shows you nothing.
const SHELL = "kirana-shell-v1";
const FILES = ["/", "/index.html", "/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Never intercept the API. Always hit the network.
  if (["/search", "/login", "/logout", "/me", "/health"].some(p => url.pathname.startsWith(p))) return;
  if (e.request.method !== "GET") return;

  // Network first so an edit to index.html shows up on reload, cache as backup.
  e.respondWith(
    fetch(e.request)
      .then(r => {
        const copy = r.clone();
        caches.open(SHELL).then(c => c.put(e.request, copy)).catch(() => {});
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
