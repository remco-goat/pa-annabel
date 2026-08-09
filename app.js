// supabase-js wordt lokaal meegeleverd (vendor/supabase.js) in plaats van via
// een CDN geladen: geen derde partij die code in de app kan wijzigen, en de
// CSP kan alle externe scripts blokkeren.
const { createClient } = window.supabase;

const cfg = window.ASSISTANT_CONFIG || {};
const $ = (id) => document.getElementById(id);

const URGENCY = [
  ["now", "Nu"],
  ["today", "Vandaag"],
  ["week", "Deze week"],
  ["someday", "Ooit"],
];

const KIND_LABEL = {
  create_task: "Taak",
  draft_reply: "Concept-antwoord",
  buy: "Kopen",
  reminder: "Herinnering",
  fyi: "Ter info",
};

const SOURCE_LABEL = {
  gmail: "Open de mail",
  calendar: "Open in agenda",
  todo: "Open in Todoist",
  notulen: "Open de mail",
};

let sb;
let undoTimer;

// --- basis ---------------------------------------------------------------

function fail(msg) {
  $("loading").hidden = true;
  $("error").textContent = msg;
  $("error").hidden = false;
}

function show(view) {
  $("loading").hidden = true;
  $("error").hidden = true;
  $("login").hidden = view !== "login";
  $("app").hidden = view !== "app";
  $("refresh").hidden = view !== "app";
}

function toast(message, undo) {
  clearTimeout(undoTimer);
  $("toast-msg").textContent = message;
  const btn = $("toast-undo");
  btn.hidden = !undo;
  btn.onclick = undo
    ? () => {
        $("toast").hidden = true;
        undo();
      }
    : null;
  $("toast").hidden = false;
  undoTimer = setTimeout(() => ($("toast").hidden = true), 6000);
}

function tap() {
  // Korte trilling als bevestiging. Alleen Android/desktop; iOS negeert dit stil.
  if (navigator.vibrate) navigator.vibrate(8);
}

// --- auth -----------------------------------------------------------------

async function initAuth() {
  if (!cfg.supabaseUrl || !cfg.supabaseAnonKey) {
    return fail("config.js is nog niet ingevuld (supabaseUrl / supabaseAnonKey).");
  }
  sb = createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);

  const { data } = await sb.auth.getSession();
  if (data.session) onSignedIn(data.session);
  else show("login");

  sb.auth.onAuthStateChange((_event, session) => {
    if (session) onSignedIn(session);
    else show("login");
  });
}

function onSignedIn(session) {
  $("who").textContent = session.user.email;
  show("app");
  load();
}

// Inloggen met een 6-cijferige code i.p.v. een magic link: op iOS opent een
// mail-link altijd Safari en nooit de geïnstalleerde app, dus de sessie zou
// op de verkeerde plek belanden. Een code typ je in de app zelf.
let pendingEmail = "";

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  $("login-msg").textContent = "Versturen…";
  pendingEmail = $("email").value.trim();
  const { error } = await sb.auth.signInWithOtp({
    email: pendingEmail,
    // Registratie staat uit in Supabase; dit voorkomt dat de aanvraag het
    // alsnog probeert en geeft een duidelijke fout bij een onbekend adres.
    options: { shouldCreateUser: false },
  });
  btn.disabled = false;
  if (error) {
    $("login-msg").textContent = `Mislukt: ${error.message}`;
    return;
  }
  $("login-step-email").hidden = true;
  $("login-step-code").hidden = false;
  $("login-msg").textContent = "Code verstuurd. Kijk in je mail.";
  $("code").focus();
});

$("code-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  $("login-msg").textContent = "Controleren…";
  const { error } = await sb.auth.verifyOtp({
    email: pendingEmail,
    token: $("code").value.trim(),
    type: "email",
  });
  btn.disabled = false;
  if (error) {
    $("login-msg").textContent = `Code klopt niet of is verlopen: ${error.message}`;
  }
  // Bij succes vuurt onAuthStateChange en schakelt de app zelf om.
});

$("have-code").addEventListener("click", () => {
  const email = $("email").value.trim();
  if (!email) {
    $("login-msg").textContent = "Vul eerst je e-mailadres in.";
    return;
  }
  pendingEmail = email;
  $("login-step-email").hidden = true;
  $("login-step-code").hidden = false;
  $("login-msg").textContent = "";
  $("code").focus();
});

$("code-back").addEventListener("click", () => {
  $("login-step-code").hidden = true;
  $("login-step-email").hidden = false;
  $("login-msg").textContent = "";
});

$("logout").addEventListener("click", () => sb.auth.signOut());
$("refresh").addEventListener("click", () => load());

// --- opdrachten -------------------------------------------------------------

$("cmd-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("cmd").value.trim();
  if (!text) return;
  $("cmd").value = "";
  tap();
  const { error } = await sb.from("signals").insert({
    source: "command",
    external_id: crypto.randomUUID(),
    kind: "command",
    title: text,
    occurred_at: new Date().toISOString(),
    payload: {},
  });
  if (error) return fail(error.message);
  toast("Klaargezet voor Annabel");
  loadCommands();
});

// Inspreken. Op een iOS-beginscherm-app is het Web Speech API onbetrouwbaar,
// maar daar heeft het toetsenbord zelf een prima dicteerknop — dus daar
// verbergen we onze eigen microfoon en wijzen we naar het toetsenbord.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
// Op iOS (ook in Safari zelf) is browser-spraakherkenning onbetrouwbaar; daar
// is de dicteerknop op het toetsenbord de betrouwbare route.
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
if (SR && !isIOS) {
  const mic = $("mic");
  mic.hidden = false;
  mic.addEventListener("click", () => {
    const rec = new SR();
    rec.lang = "nl-NL";
    rec.interimResults = false;
    let gotResult = false;
    mic.classList.add("listening");
    rec.onresult = (e) => {
      gotResult = true;
      $("cmd").value = e.results[0][0].transcript;
      $("cmd").focus();
    };
    rec.onend = () => {
      mic.classList.remove("listening");
      if (!gotResult) {
        // Browser zegt spraak te kunnen maar levert niets: knop weg en
        // doorverwijzen naar de dicteerknop van het toetsenbord.
        mic.hidden = true;
        toast("Gebruik de microfoontoets op je toetsenbord om in te spreken");
      }
    };
    rec.onerror = () => mic.classList.remove("listening");
    rec.start();
  });
}

async function loadCommands() {
  const { data, error } = await sb.from("signals").select("id,title,first_seen_at")
    .eq("source", "command").eq("status", "new")
    .order("first_seen_at", { ascending: true });
  if (error) return fail(error.message);

  const wrap = $("cmd-open");
  wrap.textContent = "";
  for (const c of data) {
    const row = document.createElement("div");
    row.className = "cmd-row";
    const text = document.createElement("span");
    text.textContent = c.title;
    const cancel = document.createElement("button");
    cancel.className = "link-btn";
    cancel.textContent = "✕";
    cancel.setAttribute("aria-label", "Opdracht intrekken");
    cancel.addEventListener("click", async () => {
      await sb.from("signals").update({ status: "ignored" }).eq("id", c.id);
      loadCommands();
    });
    row.append(text, cancel);
    wrap.append(row);
  }
}

// --- data -----------------------------------------------------------------

const SELECT = "*,signal:signals(payload,title,source,external_id)";

async function load() {
  const since = new Date();
  since.setHours(0, 0, 0, 0);

  const [briefRes, openRes, doneRes, queuedRes] = await Promise.all([
    sb.from("briefs").select("*").order("created_at", { ascending: false }).limit(1),
    sb.from("proposals").select(SELECT)
      .in("status", ["pending", "snoozed", "failed"])
      .order("created_at", { ascending: false }),
    sb.from("proposals").select(SELECT)
      .in("status", ["done", "rejected"])
      .gte("decided_at", since.toISOString())
      .order("decided_at", { ascending: false }),
    sb.from("proposals").select("id,title")
      .eq("status", "approved")
      .order("decided_at", { ascending: true }),
  ]);

  for (const r of [briefRes, openRes, doneRes, queuedRes]) if (r.error) return fail(r.error.message);

  renderBrief(briefRes.data[0]);
  renderOpen(openRes.data.filter(visibleNow));
  renderHistory(doneRes.data);
  renderQueue(queuedRes.data);
  loadCommands();
}

// Goedgekeurd maar nog niet uitgevoerd: laat zien dat het onderweg is, zodat
// goedkeuren nooit voelt als iets dat in het niets verdwijnt.
function renderQueue(items) {
  const wrap = $("approved-queue");
  wrap.textContent = "";
  for (const p of items) {
    const row = document.createElement("div");
    row.className = "queue-row";
    const text = document.createElement("span");
    text.textContent = p.title;
    row.append(text);
    wrap.append(row);
  }
}

function visibleNow(p) {
  if (p.status !== "snoozed") return true;
  return !p.snooze_until || new Date(p.snooze_until) <= new Date();
}

function renderBrief(brief) {
  const el = $("brief");
  if (!brief) return void (el.hidden = true);
  $("brief-headline").textContent = brief.headline;
  $("brief-time").textContent = relativeDay(brief.created_at);

  const body = $("brief-body");
  body.textContent = "";

  // Nieuwe briefs zijn een JSON-array van punten; oude zijn platte tekst.
  let points = null;
  try {
    const parsed = JSON.parse(brief.body);
    if (Array.isArray(parsed)) points = parsed;
  } catch { /* platte tekst */ }

  if (!points) {
    body.textContent = brief.body;
    el.hidden = false;
    return;
  }

  // Afstrepen: tik op een punt = doorgestreept. Lokaal onthouden per brief,
  // zodat het na verversen en herstart zo blijft staan.
  const key = `struck-${brief.id}`;
  const struck = new Set(JSON.parse(localStorage.getItem(key) || "[]"));

  points.forEach((text, i) => {
    const row = document.createElement("div");
    row.className = "point" + (struck.has(i) ? " struck" : "");
    row.setAttribute("role", "button");
    row.tabIndex = 0;
    row.textContent = text;
    const toggle = () => {
      tap();
      if (struck.has(i)) struck.delete(i);
      else struck.add(i);
      row.classList.toggle("struck");
      localStorage.setItem(key, JSON.stringify([...struck]));
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
    body.append(row);
  });
  el.hidden = false;
}

function relativeDay(iso) {
  const d = new Date(iso);
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 864e5);
  const time = d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
  if (days === 0) {
    const h = d.getHours();
    return `${h < 12 ? "Vanochtend" : h < 18 ? "Vanmiddag" : "Vanavond"} ${time}`;
  }
  if (days === 1) return `Gisteren ${time}`;
  return d.toLocaleDateString("nl-NL", { weekday: "long", day: "numeric", month: "long" }) + `, ${time}`;
}

function renderOpen(items) {
  const list = $("list");
  list.textContent = "";

  const open = items.filter((p) => p.status !== "failed");
  const failed = items.filter((p) => p.status === "failed");

  $("empty").hidden = items.length > 0;
  $("badge").textContent = open.length;
  $("badge").hidden = open.length === 0;

  // Badge op het app-icoon (iOS 16.4+ voor apps op het beginscherm).
  if ("setAppBadge" in navigator) {
    if (open.length) navigator.setAppBadge(open.length).catch(() => {});
    else navigator.clearAppBadge().catch(() => {});
  }

  if (failed.length) {
    list.append(groupLabel(`Mislukt (${failed.length})`, "failed"));
    for (const p of failed) list.append(card(p, { failed: true }));
  }

  for (const [key, label] of URGENCY) {
    const group = open.filter((p) => p.urgency === key);
    if (!group.length) continue;
    list.append(groupLabel(label, key));
    for (const p of group) list.append(card(p));
  }
}

function renderHistory(items) {
  const wrap = $("history");
  if (!items.length) return void (wrap.hidden = true);
  wrap.hidden = false;
  $("history-count").textContent = `Vandaag afgehandeld (${items.length})`;

  const list = $("history-list");
  list.textContent = "";
  for (const p of items) {
    const row = document.createElement("div");
    row.className = "hist-row";

    const mark = document.createElement("span");
    mark.className = "hist-mark";
    mark.textContent = p.status === "done" ? "✓" : "—";

    const text = document.createElement("span");
    text.textContent = p.title;

    row.append(mark, text);

    if (p.status === "done" && /^https?:\/\//.test(p.result || "")) {
      row.append(link(p.result, "openen"));
    }
    list.append(row);
  }
}

function groupLabel(text, key) {
  const el = document.createElement("div");
  el.className = `group-label ${key}`;
  el.textContent = text;
  return el;
}

function link(href, text) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.className = "source-link";
  a.textContent = text;
  return a;
}

function card(p, { failed = false } = {}) {
  const el = document.createElement("div");
  el.className = "card" + (failed ? " is-failed" : "");
  el.dataset.id = p.id;

  const head = document.createElement("div");
  head.className = "kind";
  head.textContent = KIND_LABEL[p.kind] || p.kind;
  el.append(head);

  const title = document.createElement("div");
  title.className = "title";
  title.textContent = p.title;
  el.append(title);

  if (p.detail) {
    const detail = document.createElement("p");
    detail.className = "detail";
    detail.textContent = p.detail;
    el.append(detail);
  }

  if (failed && p.result) {
    const err = document.createElement("p");
    err.className = "fail-msg";
    err.textContent = p.result;
    el.append(err);
  }

  const body = p.action?.draft_body;
  if (body) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Concepttekst bekijken";
    const pre = document.createElement("pre");
    pre.textContent = body;
    details.append(summary, pre);
    el.append(details);
  }

  const url = p.signal?.payload?.url;
  if (url) {
    const wrap = document.createElement("div");
    wrap.className = "source";
    wrap.append(link(url, SOURCE_LABEL[p.signal.source] || "Open bron"));
    el.append(wrap);
  }

  const actions = document.createElement("div");
  actions.className = "actions";
  const isTodoTask = p.signal?.source === "todo" && p.signal?.external_id;

  if (failed) {
    actions.append(
      button("Opnieuw proberen", "primary", () => decide(p, "approved", "Staat weer klaar")),
      button("Laat maar", "", () => decide(p, "rejected", "Afgewezen")),
    );
  } else if (isTodoTask) {
    // Kaart over een bestaande Todoist-taak: afvinken sluit de taak echt.
    actions.append(
      button("✓ Afvinken", "primary", () =>
        decide(p, "approved", "Wordt afgevinkt in Todoist", { complete_task_id: p.signal.external_id })),
      button("Morgen", "", () => decide(p, "snoozed", "Morgen weer")),
      button("Nee", "", () => decide(p, "rejected", "Afgewezen")),
    );
  } else if (p.kind === "draft_reply") {
    actions.append(
      button("Verstuur", "primary", () =>
        decide(p, "approved", "Wordt verstuurd", { send: true })),
      button("Alleen concept", "", () => decide(p, "approved", "Concept wordt klaargezet")),
      button("Nee", "", () => decide(p, "rejected", "Afgewezen")),
    );
  } else {
    actions.append(
      button("Goedkeuren", "primary", () => decide(p, "approved", "Goedgekeurd")),
      button("Morgen", "", () => decide(p, "snoozed", "Morgen weer")),
      button("Nee", "", () => decide(p, "rejected", "Afgewezen")),
    );
  }
  el.append(actions);
  return el;
}

function button(label, cls, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  if (cls) b.className = cls;
  b.addEventListener("click", onClick);
  return b;
}

async function decide(proposal, status, message, extraAction = null) {
  const previous = proposal.status;
  const previousAction = proposal.action;
  const patch = { status, decided_at: new Date().toISOString() };
  if (extraAction) patch.action = { ...(proposal.action || {}), ...extraAction };
  if (status === "snoozed") {
    const t = new Date();
    t.setDate(t.getDate() + 1);
    t.setHours(7, 0, 0, 0);
    patch.snooze_until = t.toISOString();
  }

  const el = document.querySelector(`.card[data-id="${proposal.id}"]`);
  if (el) el.classList.add("gone");
  tap();

  const { error } = await sb.from("proposals").update(patch).eq("id", proposal.id);
  if (error) {
    if (el) el.classList.remove("gone");
    return fail(error.message);
  }

  toast(message, async () => {
    await sb.from("proposals")
      .update({ status: previous, decided_at: null, snooze_until: null, action: previousAction })
      .eq("id", proposal.id);
    proposal.status = previous;
    load();
  });

  setTimeout(load, 220);
}

// --- pull to refresh ------------------------------------------------------

let pullStart = 0;
const THRESHOLD = 70;

document.addEventListener("touchstart", (e) => {
  pullStart = window.scrollY === 0 ? e.touches[0].clientY : 0;
}, { passive: true });

document.addEventListener("touchmove", (e) => {
  if (!pullStart) return;
  const delta = e.touches[0].clientY - pullStart;
  if (delta > 0) $("pull").style.transform = `translateY(${Math.min(delta, THRESHOLD)}px)`;
}, { passive: true });

document.addEventListener("touchend", (e) => {
  if (!pullStart) return;
  const delta = e.changedTouches[0].clientY - pullStart;
  $("pull").style.transform = "";
  pullStart = 0;
  if (delta > THRESHOLD && !$("app").hidden) {
    $("pull").classList.add("busy");
    load().finally(() => $("pull").classList.remove("busy"));
  }
}, { passive: true });

// Terug uit de achtergrond: even bijwerken.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && sb && !$("app").hidden) load();
});

// --- pushmeldingen ----------------------------------------------------------
// Publieke helft van het VAPID-sleutelpaar; de agent ondertekent met de
// private helft. Publiek zijn is de bedoeling.
const VAPID_PUBLIC_KEY = "BA7PANCaS_tJKJSjLszBTugVViIcQVmpESPhvPlP5uwiAjnEx5pBpuVnCDmPWX0EXksfv6b2jt5shUY0qs11uVo";

function vapidKeyBytes(base64url) {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function initNotifications() {
  const btn = $("notif");
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return; // niet ondersteund (op iOS: alleen in de beginscherm-app, 16.4+)
  }
  const reg = await navigator.serviceWorker.ready;
  const existing = await reg.pushManager.getSubscription();
  if (existing && Notification.permission === "granted") {
    btn.hidden = true;
    return;
  }
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        toast("Meldingen geweigerd — aan te zetten via Instellingen > Annabel");
        return;
      }
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: vapidKeyBytes(VAPID_PUBLIC_KEY),
      });
      const { error } = await sb.from("signals").upsert(
        {
          source: "push_sub",
          external_id: sub.endpoint,
          kind: "push_sub",
          title: "pushabonnement",
          payload: sub.toJSON(),
          status: "new",
        },
        { onConflict: "source,external_id" },
      );
      if (error) return fail(error.message);
      btn.hidden = true;
      toast("Meldingen staan aan");
    } catch (e) {
      toast(`Meldingen aanzetten mislukt: ${e.message}`);
    }
  });
}

initAuth();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").then(() => initNotifications()).catch(() => {});
}
