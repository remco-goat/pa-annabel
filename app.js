import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

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

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  $("login-msg").textContent = "Versturen…";
  const { error } = await sb.auth.signInWithOtp({
    email: $("email").value.trim(),
    options: { emailRedirectTo: window.location.href },
  });
  btn.disabled = false;
  $("login-msg").textContent = error
    ? `Mislukt: ${error.message}`
    : "Check je mail. De link opent deze app.";
});

$("logout").addEventListener("click", () => sb.auth.signOut());
$("refresh").addEventListener("click", () => load());

// --- data -----------------------------------------------------------------

const SELECT = "*,signal:signals(payload,title,source)";

async function load() {
  const since = new Date();
  since.setHours(0, 0, 0, 0);

  const [briefRes, openRes, doneRes] = await Promise.all([
    sb.from("briefs").select("*").order("created_at", { ascending: false }).limit(1),
    sb.from("proposals").select(SELECT)
      .in("status", ["pending", "snoozed", "failed"])
      .order("created_at", { ascending: false }),
    sb.from("proposals").select(SELECT)
      .in("status", ["done", "rejected"])
      .gte("decided_at", since.toISOString())
      .order("decided_at", { ascending: false }),
  ]);

  for (const r of [briefRes, openRes, doneRes]) if (r.error) return fail(r.error.message);

  renderBrief(briefRes.data[0]);
  renderOpen(openRes.data.filter(visibleNow));
  renderHistory(doneRes.data);
}

function visibleNow(p) {
  if (p.status !== "snoozed") return true;
  return !p.snooze_until || new Date(p.snooze_until) <= new Date();
}

function renderBrief(brief) {
  const el = $("brief");
  if (!brief) return void (el.hidden = true);
  $("brief-headline").textContent = brief.headline;
  $("brief-body").textContent = brief.body;
  $("brief-time").textContent = relativeDay(brief.created_at);
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
  if (failed) {
    actions.append(
      button("Opnieuw proberen", "primary", () => decide(p, "approved", "Staat weer klaar")),
      button("Laat maar", "", () => decide(p, "rejected", "Afgewezen")),
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

async function decide(proposal, status, message) {
  const previous = proposal.status;
  const patch = { status, decided_at: new Date().toISOString() };
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
      .update({ status: previous, decided_at: null, snooze_until: null })
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

initAuth();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
