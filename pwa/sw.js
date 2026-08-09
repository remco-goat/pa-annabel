// Minimale service worker: app-shell cachen zodat de app installeerbaar is en
// offline nog opent. Data komt altijd vers van Supabase — die cachen we niet.
const CACHE = "annabel-v3";
const SHELL = ["./", "index.html", "styles.css", "app.js", "config.js", "manifest.json", "icon.svg", "vendor/supabase.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { data = { body: e.data?.text() }; }
  e.waitUntil(
    self.registration.showNotification(data.title || "Annabel", {
      body: data.body || "",
      icon: "icon.svg",
      badge: "icon.svg",
      tag: "annabel",           // nieuwe melding vervangt de vorige
    }),
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) if ("focus" in c) return c.focus();
      return clients.openWindow(self.registration.scope);
    }),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;

  // Netwerk eerst, cache als vangnet — anders zie je na een deploy oude code.
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("index.html"))),
  );
});
