// clawd-web service worker — installability + offline app shell.
// Bump CACHE to invalidate old caches on deploy.
const CACHE = "clawd-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Never cache live endpoints — always hit the network (and let it fail loudly).
  if (url.pathname.startsWith("/api/") || url.pathname === "/config" || url.pathname === "/events") {
    return;
  }

  // Navigations: network-first so index.html updates; fall back to cached shell offline.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => { caches.open(CACHE).then((c) => c.put("/", res.clone())); return res; })
        .catch(() => caches.match("/"))
    );
    return;
  }

  // Static assets (avatar clips, icons, manifest): stale-while-revalidate.
  if (url.pathname.startsWith("/clawdassets/") || url.pathname.endsWith(".webmanifest")) {
    e.respondWith(
      caches.open(CACHE).then(async (c) => {
        const cached = await c.match(req);
        const network = fetch(req).then((res) => { c.put(req, res.clone()); return res; }).catch(() => cached);
        return cached || network;
      })
    );
  }
});
