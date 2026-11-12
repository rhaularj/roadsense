/* RoadSense web app. Vanilla JS, hash routing, no build step. All server text is escaped before it touches the DOM:
   agent-written text (rationales, drafts) is untrusted. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const main = $("#view");
let current = null;
/* Each route renders into its own container: a slow, stale render writes into a detached node, never over the page. */
const stage = () => current;
let maps = [];
let timers = [];

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
  const body = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body?.detail || body || r.statusText);
  return body;
}

function toast(msg, ok = true) {
  const t = $("#toast");
  t.innerHTML = `${icon(ok ? "check" : "alert")}<span>${esc(msg)}</span>`;
  t.classList.toggle("err", !ok);
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), 3800);
}

/* ---------- icons (Lucide-style paths) ---------- */
const ICONS = {
  check: '<path d="M20 6L9 17l-5-5"/>', alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/>',
  merge: '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 009 9"/>',
  route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 000-7h-11a3.5 3.5 0 010-7H15"/><circle cx="18" cy="5" r="3"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>', inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 00-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 005.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  pin: '<path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/>',
  layers: '<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>', send: '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>',
  user: '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>', cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  sparkle: '<path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/>', shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  upload: '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/>', video: '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>', building: '<path d="M3 21h18M5 21V10M19 21V10M9 21v-6h6v6M2 10l10-7 10 7"/>',
  arrow: '<path d="M9 18l6-6-6-6"/>', lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>',
  refresh: '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.5 9a9 9 0 0114.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0020.5 15"/>',
  ext: '<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  grid: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  file: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
  map: '<path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4z"/><path d="M8 2v16M16 6v16"/>', activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  moon: '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>',
};
const icon = (n, cls = "") => `<svg class="${cls}" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[n] || ""}</svg>`;

/* ---------- vocabulary ---------- */
const STATUS = {
  pending_approval: ["Awaiting review", "amber"], approved: ["Approved", "blue"], submitted: ["Sent", "violet"],
  fixed: ["Fixed", "green"], rejected: ["Rejected", ""],
};
const statusPill = (s) => { const [t, c] = STATUS[s] || [s, ""]; return `<span class="pill ${c}"><span class="dot"></span>${esc(t)}</span>`; };
const SEVERITY = { high: "red", medium: "amber", low: "" };
const sevPill = (s) => `<span class="pill ${SEVERITY[s] || ""}">${esc(s ? s[0].toUpperCase() + s.slice(1) : "")}</span>`;
const ACTORS = {
  "agent:orchestrator": ["Orchestrator", "violet", "sparkle"], "agent:vision": ["Vision agent", "blue", "eye"],
  "agent:location": ["Location agent", "cyan", "pin"], "agent:triage": ["Triage agent", "amber", "merge"],
  "agent:filing": ["Filing agent", "green", "send"], "agent:follow_up": ["Follow-up agent", "green", "wrench"],
  driver: ["Driver", "", "user"], edge: ["Edge device", "", "video"], fallback: ["Rule engine", "", "cpu"],
};
const actor = (a) => ACTORS[a] || (a?.startsWith("mcp:") ? [`${a.slice(4)} tool`, "", "layers"] : [a, "", "cpu"]);
const avatar = (a) => { const [, c, i] = actor(a); return `<span class="avatar pill ${c}">${icon(i)}</span>`; };
const AUTH_SHORT = { "Halifax Regional Municipality": "Halifax 311", "Nova Scotia Public Works": "NS Public Works" };
const authority = (j) => AUTH_SHORT[j] || j || "Unassigned";
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
const num = (x) => new Intl.NumberFormat().format(x || 0);

function ago(ts) {
  if (!ts) return "";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function parse(detail) { try { return JSON.parse(detail); } catch { return detail; } }

/* What an audit entry means, in plain language */
function describe(a) {
  const d = parse(a.detail);
  const subj = esc((a.subject || "").replace(/^(report|event|trip):/, ""));
  const rationale = typeof d === "string" ? d : d?.rationale || "";
  switch (true) {
    case a.action === "verdict_confirmed": return ["Confirmed real damage", rationale];
    case a.action === "verdict_disputed": return ["Flagged: models disagree on the damage type", rationale];
    case a.action === "verdict_rejected": return ["Rejected as a false alarm", rationale];
    case a.action === "report_created": return [`Opened report #${subj}`, d?.rationale || ""];
    case a.action === "report_merged": return [`Merged into report #${subj}`, d?.distance_m != null ? `Another sighting ${d.distance_m} m from an open report, so no new ticket. ${d?.rationale || ""}` : ""];
    case a.action === "status_approved": return ["Approved the exact payload", "Locked by hash"];
    case a.action === "status_submitted": return [`Sent to the authority`, d?.service_request_id ? `Request ${d.service_request_id} via ${d.channel}` : ""];
    case a.action === "status_fixed": return ["Repair confirmed by the authority", ""];
    case a.action === "status_rejected": return ["Rejected by the driver", ""];
    case a.action === "trip_done": return [`Finished trip ${subj}`, d?.summary || ""];
    case a.action === "plan": return ["Plan", typeof d === "string" ? d : ""];
    case a.action === "answer": return ["Answer", d?.content || ""];
    case a.action === "task": return ["Received task", typeof d === "string" ? d : ""];
    case a.action === "verify": return ["Verifier check (RT-DETR-L)", d?.reason || ""];
    case a.action === "recheck": return ["Close-up re-check", d?.reason || ""];
    case a.action === "event_received": return ["Detection uploaded", d?.class ? `${d.class} on trip ${d.trip}` : ""];
    case a.action === "completed_event": return ["Completed a step the agents skipped", ""];
    case a.action === "llm_unavailable": return ["LLM unavailable, rule engine took over", typeof d === "string" ? d : ""];
    case a.action.startsWith("tool:"): return [`Called ${a.action.slice(5)}`, ""];
    default: return [a.action.replace(/_/g, " "), typeof d === "string" ? d : ""];
  }
}

/* ---------- shell ---------- */
const ROUTES = {
  overview: ["Overview", "What the agents found and what reached the road authorities", renderOverview],
  trips: ["Trips", "Upload a dashcam drive; the edge device and agents take it from there", renderTrips],
  review: ["Review", "Nothing is sent until you approve the exact payload", renderReview],
  reports: ["Reports", "Every defect, merged across drivers", renderReports],
  map: ["Map", "Reports on the road network", renderMap],
  activity: ["Agent activity", "Every plan, decision and tool call, from the append-only audit log", renderActivity],
  authorities: ["Authorities", "Requests delivered to Halifax 311 and Nova Scotia Public Works", renderAuthorities],
  system: ["Trust & system", "Guardrails, privacy and the agent stack", renderSystem],
};

async function router() {
  const [path, qs] = location.hash.replace(/^#\/?/, "").split("?");
  const route = ROUTES[path] ? path : "overview";
  const params = new URLSearchParams(qs || "");
  maps.forEach((m) => m.remove()); maps = [];
  timers.forEach(clearInterval); timers = [];
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  const [title, sub, render] = ROUTES[route];
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  $("#crumb-current").textContent = title;
  document.title = `${title} · RoadSense`;
  $("#sidebar").classList.remove("open");
  current = document.createElement("div");
  current.innerHTML = `<div class="grid kpis">${'<div class="card kpi"><div class="skeleton" style="width:45%"></div><div class="skeleton" style="width:30%;height:24px;margin-top:14px"></div></div>'.repeat(3)}</div>
    <div class="card card-body section"><div class="skeleton" style="width:40%"></div><div class="skeleton" style="width:70%;margin-top:12px"></div><div class="skeleton" style="width:55%;margin-top:12px"></div></div>`;
  main.replaceChildren(current);
  const mine = current;
  try { await render(params); } catch (e) { mine.innerHTML = errorState(e); }
  refreshChrome();
}

const errorState = (e) => `<div class="card empty"><span class="empty-ic" style="color:var(--red-text)">${icon("alert")}</span><b>Couldn't load this page</b><div class="small">${esc(e.message)}</div><div class="small" style="margin-top:8px">Is the agent service running? Start everything with <code>python scripts/run_all.py</code>.</div><button class="btn btn-sm" style="margin-top:12px" onclick="router()">${icon("refresh")}Retry</button></div>`;
const emptyState = (ic, title, text, action = "") => `<div class="empty"><span class="empty-ic">${icon(ic)}</span><b>${esc(title)}</b><div class="small">${text}</div>${action}</div>`;
const more = (href, label) => `<a href="${href}" class="link-more">${label}${icon("arrow")}</a>`;

async function refreshChrome() {
  try {
    const [pending, sys] = await Promise.all([api("/api/reports?status=pending_approval"), api("/api/system")]);
    $("#review-count").textContent = pending.length || "";
    const llm = sys.health.llm;
    const live = llm.enabled;
    $("#agent-status").innerHTML = `
      <div class="status-line"><span class="live-dot ${live ? "" : "amber"}"></span>${live ? "Agents live" : "Rule engine"}<a href="#/system" class="link-more" style="margin-left:auto" aria-label="System status">${icon("arrow")}</a></div>
      <div class="muted small" style="margin-top:6px">${live ? esc(llm.models[0].split("/").pop().replace(":free", "")) + " · " + esc(llm.mode) : "No LLM key: deterministic pipeline"}</div>
      <div class="faint small">${sys.health.mcp_tools.length} MCP tools · 4 servers</div>`;
    palette.pending = pending;
  } catch { $("#agent-status").innerHTML = `<div class="status-line"><span class="live-dot red"></span>Agent service offline</div><div class="muted small" style="margin-top:4px">Retrying every 15 s</div>`; }
}

/* ---------- Overview ---------- */
async function renderOverview() {
  const view = stage();
  const { stats: s, reports, trips, activity } = await api("/api/overview");
  const reportsN = Object.values(s.reports).reduce((a, b) => a + b, 0);
  const sent = (s.reports.submitted || 0) + (s.reports.fixed || 0);
  const confirmed = (s.events.processed || 0) + (s.events.verified || 0);
  const funnelStage = (n, t, of, prev, d = true) => `<div class="stage"><div class="t">${t}</div><div class="n">${num(n)}${prev != null ? `<span class="rate">${prev ? pct(n / prev) : "–"} of previous</span>` : ""}</div><div class="bar"><i style="width:${of ? Math.max(3, (n / of) * 100) : 0}%"></i></div>${d ? `<span class="delta">${icon("arrow")}</span>` : ""}</div>`;
  const kpi = (ic, label, value, hint, tone = "") => `<div class="card kpi"><div class="label">${label}<span class="ic ${tone}">${icon(ic)}</span></div><div class="value">${value}</div><div class="hint">${hint}</div></div>`;
  view.innerHTML = `
    <div class="card"><div class="card-head"><h2>Pipeline</h2><span class="desc">From detection to the right desk</span><span class="spacer"></span><span class="pill">${icon("video")}${num(s.trips)} trips</span><span class="pill violet">${icon("sparkle")}${s.agent_trips} by LLM agents</span></div>
      <div class="funnel">${funnelStage(s.detections, "Detections", s.detections)}${funnelStage(confirmed, "Confirmed by Vision agent", s.detections, s.detections)}${funnelStage(reportsN, "Unique reports", s.detections, confirmed)}${funnelStage(sent, "Sent to an authority", s.detections, reportsN, false)}</div></div>
    <div class="grid kpis section">
      ${kpi("inbox", "Awaiting your review", num(s.reports.pending_approval), "Nothing leaves without approval", "amber")}
      ${kpi("merge", "Duplicates merged", num(s.duplicates_merged), `${num(s.multi_driver_reports)} reports confirmed by 2+ drivers`, "blue")}
      ${kpi("x", "False alarms removed", num(s.false_alarms_removed), "Rejected by verification", "")}
      ${kpi("route", "Routed to the province", num(s.authorities["Nova Scotia Public Works"]), "Not dumped on city 311", "cyan")}
      ${kpi("alert", "Priority 1 candidates", num(s.priority1_candidates), "Width ≥ 25 cm (HRM standard)", "red")}
      ${kpi("wrench", "Repairs confirmed", num(s.reports.fixed), "Drivers notified", "green")}
    </div>
    <div class="grid two section">
      <div class="card"><div class="card-head"><h2>Latest agent decisions</h2><span class="spacer"></span>${more("#/activity", "View all")}</div>
        ${activity.length ? `<ul class="feed">${activity.map(feedItem).join("")}</ul>` : emptyState("sparkle", "No decisions yet", "Upload a trip to see the agents work.")}</div>
      <div class="grid" style="align-content:start">
        <div class="card"><div class="card-head"><h2>Reports map</h2><span class="spacer"></span>${more("#/map", "Open map")}</div><div id="mini-map" class="map-mini"></div></div>
        <div class="card"><div class="card-head"><h2>Agent usage</h2><span class="spacer"></span><span class="desc">All trips</span></div><div class="card-body facts">
          <div class="fact"><div class="k">LLM calls</div><div class="v">${num(s.llm_calls)}</div></div>
          <div class="fact"><div class="k">Tokens</div><div class="v">${num(s.llm_tokens)}</div></div>
          <div class="fact"><div class="k">Fallback rate</div><div class="v">${pct(s.fallback_rate)}</div></div>
          <div class="fact"><div class="k">Disputed classes</div><div class="v">${num(s.class_disputed)}</div></div></div></div>
      </div>
    </div>
    <div class="card section"><div class="card-head"><h2>Recent trips</h2><span class="spacer"></span>${more("#/trips", "All trips")}</div>
      ${tripsTable(trips)}</div>`;
  drawMap("mini-map", reports, { zoom: 14, interactive: false });
}

function feedItem(a) {
  const [who] = actor(a.actor);
  const [what, why] = describe(a);
  const link = a.subject?.startsWith("report:") ? `#/reports?id=${a.subject.slice(7)}` : "";
  return `<li>${avatar(a.actor)}<div style="min-width:0;flex:1"><div><span class="what">${esc(what)}</span> <span class="who">· ${esc(who)}</span></div>${why ? `<div class="why">${esc(why).slice(0, 360)}</div>` : ""}${link ? `<a class="link-more" style="margin-top:4px" href="${link}">Open report${icon("arrow")}</a>` : ""}</div><span class="when">${ago(a.ts)}</span></li>`;
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-process]");
  if (!b) return;
  b.disabled = true;
  try { await api(`/api/trips/${encodeURIComponent(b.dataset.process)}/process`, { method: "POST" }); toast("Agents started on this trip"); }
  catch (e) { toast(e.message, false); }
});

function tripsTable(trips) {
  if (!trips.length) return emptyState("video", "No trips yet", "Upload a dashcam video with its GPS track.", `<a class="btn btn-primary" style="margin-top:12px" href="#/trips?new=1">${icon("upload")}New trip</a>`);
  return `<div class="table-wrap"><table class="table"><thead><tr><th>Trip</th><th>Detections</th><th>Confirmed</th><th>False alarms</th><th>Run</th><th>When</th></tr></thead><tbody>
    ${trips.map((t) => { const run = t.run || {}; const llm = run.llm || {};
      return `<tr><td><span class="row" style="gap:10px"><span class="avatar pill">${icon("video")}</span><span class="strong mono">${esc(t.trip_id)}</span></span></td><td>${num(t.events)}</td><td>${num(t.processed)}</td><td>${num(t.rejected)}</td>
      <td>${run.mode?.startsWith("agents") ? `<span class="pill violet">${icon("sparkle")}Agents</span> <span class="muted small">${llm.calls || 0} calls · ${run.seconds || "?"} s</span>` : run.mode ? `<span class="pill">${icon("cpu")}Rule engine</span>` : t.processed + t.rejected < t.events ? `<button class="btn btn-sm" data-process="${esc(t.trip_id)}">${icon("refresh")}Process now</button>` : `<span class="pill green">${icon("check")}Done</span>`}</td>
      <td class="muted nowrap">${ago(t.started)}</td></tr>`; }).join("")}</tbody></table></div>`;
}

/* ---------- Map ---------- */
const MAP_COLORS = { pending_approval: "#f59e0b", approved: "#4f46e5", submitted: "#8b5cf6", fixed: "#10b981", rejected: "#9aa3b2" };
function drawMap(id, reports, { zoom = 15, interactive = true } = {}) {
  const el = document.getElementById(id);
  if (!el || !window.L) return;
  const center = reports.length ? [reports[0].lat, reports[0].lon] : [44.6425, -63.578];
  const m = L.map(el, { zoomControl: interactive, scrollWheelZoom: interactive, attributionControl: true }).setView(center, zoom);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
  const pts = [];
  for (const r of reports) {
    const c = MAP_COLORS[r.status] || "#667085";
    L.circleMarker([r.lat, r.lon], { radius: 6 + Math.min(r.confirmations, 4) * 2, color: "#fff", weight: 2, fillColor: c, fillOpacity: .9 })
      .bindPopup(`<b>#${r.id} ${esc(r.class_name)}</b><br>${esc(r.address || "")}<br>${esc(authority(r.jurisdiction))} · ${esc(STATUS[r.status]?.[0] || r.status)}<br>${r.confirmations} driver(s)<br><a href="#/reports?id=${r.id}">Open report</a>`)
      .addTo(m);
    pts.push([r.lat, r.lon]);
  }
  if (pts.length > 1) m.fitBounds(pts, { padding: [30, 30], maxZoom: 16 });
  maps.push(m);
  setTimeout(() => m.invalidateSize(), 50);
}

async function renderMap(params) {
  const view = stage();
  const all = await api("/api/reports");
  const filter = params.get("status") || "all";
  const list = filter === "all" ? all : all.filter((r) => r.status === filter);
  const count = (s) => s === "all" ? all.length : all.filter((r) => r.status === s).length;
  view.innerHTML = `
    <div class="toolbar">
      <div class="tabs" role="tablist">${["all", "pending_approval", "submitted", "fixed"].map((s) => `<button role="tab" aria-selected="${s === filter}" class="${s === filter ? "on" : ""}" data-s="${s}">${s === "all" ? "All" : STATUS[s][0]}<span class="n">${count(s)}</span></button>`).join("")}</div>
    </div>
    <div class="card"><div class="card-head"><div class="legend">${Object.entries(MAP_COLORS).map(([k, c]) => `<span><i style="background:${c}"></i>${STATUS[k][0]}</span>`).join("")}</div><span class="spacer"></span><span class="desc">Marker size = number of drivers</span></div><div id="big-map" class="map"></div></div>`;
  $$(".tabs button").forEach((b) => b.onclick = () => location.hash = `#/map?status=${b.dataset.s}`);
  drawMap("big-map", list);
}

/* ---------- Reports ---------- */
async function renderReports(params) {
  const view = stage();
  const id = params.get("id");
  if (id) return renderReportPage(id);
  const filter = params.get("status") || "all";
  const all = await api("/api/reports");
  const list = filter === "all" ? all : all.filter((r) => r.status === filter);
  const count = (s) => all.filter((r) => r.status === s).length;
  view.innerHTML = `
    <div class="toolbar">
      <div class="tabs" role="tablist">${["all", "pending_approval", "submitted", "fixed", "rejected"].map((s) => `<button role="tab" aria-selected="${s === filter}" class="${s === filter ? "on" : ""}" data-s="${s}">${s === "all" ? "All" : STATUS[s][0]}<span class="n">${s === "all" ? all.length : count(s)}</span></button>`).join("")}</div>
      <span class="spacer"></span>
      <label class="input-icon">${icon("search")}<span class="sr-only">Filter reports</span><input class="input" id="report-q" type="search" placeholder="Filter by damage, street or #id"></label>
    </div>
    <div class="card card-body flush">${list.length ? `<div class="table-wrap"><table class="table"><thead><tr><th></th><th>Damage</th><th>Location</th><th>Authority</th><th>Severity</th><th>Drivers</th><th>Priority</th><th>Status</th><th></th></tr></thead><tbody>
      ${list.map((r) => `<tr class="click" tabindex="0" data-id="${r.id}" data-q="${esc(`${r.class_name} ${r.address || ""} #${r.id} ${authority(r.jurisdiction)}`.toLowerCase())}"><td><img class="thumb" loading="lazy" src="/api/media/${encodeURIComponent(r.best_event_id)}.jpg?crop=1" alt=""></td>
        <td><span class="nowrap"><span class="strong">${esc(r.class_name)}</span> <span class="faint small mono">#${r.id}</span></span><div class="chip-row" style="margin-top:4px">${flags(r)}</div></td>
        <td>${esc(r.address || "")}</td><td class="nowrap">${esc(authority(r.jurisdiction))}</td><td>${sevPill(r.severity)}</td>
        <td>${r.confirmations}</td><td class="mono">${r.priority}</td><td>${statusPill(r.status)}</td><td>${icon("arrow", "row-arrow")}</td></tr>`).join("")}</tbody></table></div>
        <div class="card-foot" id="report-foot">${list.length} report${list.length === 1 ? "" : "s"}</div>`
      : emptyState("inbox", "No reports here", "Reports appear after a trip is processed.")}</div>`;
  $$(".tabs button").forEach((b) => b.onclick = () => location.hash = `#/reports?status=${b.dataset.s}`);
  $$("tr.click").forEach((tr) => {
    tr.onclick = () => location.hash = `#/reports?id=${tr.dataset.id}`;
    tr.onkeydown = (e) => { if (e.key === "Enter") tr.onclick(); };
  });
  const q = $("#report-q");
  q.oninput = () => {
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    $$("tr.click").forEach((tr) => { const hit = !term || tr.dataset.q.includes(term); tr.hidden = !hit; shown += hit; });
    if ($("#report-foot")) $("#report-foot").textContent = `${shown} of ${list.length} reports`;
  };
}

const flags = (r) => [
  r.p1_candidate ? `<span class="pill red">P1 candidate</span>` : "",
  r.class_disputed ? `<span class="pill amber">Class disputed</span>` : "",
  r.confirmations > 1 ? `<span class="pill blue">${icon("merge")}${r.confirmations} drivers</span>` : "",
].join("");

async function renderReportPage(id) {
  const view = stage();
  const d = await api(`/api/reports/${id}`);
  $("#crumb-current").textContent = `Reports / #${d.report.id}`;
  view.innerHTML = `<a href="#/reports" class="btn btn-ghost btn-sm" style="margin-left:-10px"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg>All reports</a><div class="card section">${reportDetail(d)}</div>`;
  bindDetail(d, () => renderReportPage(id));
}

/* ---------- Report detail (shared by Review and Reports) ---------- */
function reportDetail(d) {
  const r = d.report, e = d.events.find((x) => x.id === r.best_event_id) || d.events[0] || {};
  const p = d.payload;
  const trail = d.trail.filter((a) => /^(verdict_|report_|status_|verify|recheck|payload)/.test(a.action));
  const pending = r.status === "pending_approval";
  return `
    <div class="card-head"><h2>${esc(r.class_name)} <span class="muted">#${r.id}</span></h2>${statusPill(r.status)}<span class="spacer"></span><span class="muted small">${esc(r.address || "")}</span></div>
    <div class="card-body grid" style="gap:18px">
      <div class="grid two" style="gap:18px">
        <div><img class="detail-photo" src="/api/media/${encodeURIComponent(r.best_event_id)}.jpg" alt="Privacy-blurred frame of the damage">
          <div class="small muted" style="margin-top:6px">${icon("shield", "")} Everything except the damage was blurred on the device before upload.</div></div>
        <div class="grid" style="align-content:start;gap:12px">
          ${r.class_disputed ? `<div class="callout amber">${icon("alert")}<div><b>The two models disagree on the damage type.</b> YOLOv8m's label is kept; please check the photo.</div></div>` : ""}
          ${r.p1_candidate ? `<div class="callout red">${icon("alert")}<div><b>HRM Priority 1 candidate</b>: estimated width ≥ 25 cm. Depth can't be measured from video.</div></div>` : ""}
          ${r.confirmations > 1 ? `<div class="callout blue">${icon("merge")}<div><b>Seen by ${r.confirmations} independent drivers.</b> Repeat sightings were merged instead of filed again.</div></div>` : ""}
          <div class="facts">
            <div class="fact"><div class="k">Severity</div><div class="v">${sevPill(r.severity)}</div></div>
            <div class="fact"><div class="k">Est. width</div><div class="v">${r.class_code === "D40" && r.width_m ? Math.round(r.width_m * 100) + " cm" : r.class_code === "D40" ? "–" : "n/a for cracks"}</div></div>
            <div class="fact"><div class="k">Edge confidence</div><div class="v">${e.confidence != null ? e.confidence.toFixed(2) : "–"}</div></div>
            <div class="fact"><div class="k">Verifier confidence</div><div class="v">${e.verified_confidence != null ? e.verified_confidence.toFixed(2) : e.recheck_confidence != null ? e.recheck_confidence.toFixed(2) + " (close-up)" : "–"}</div></div>
            <div class="fact"><div class="k">Position</div><div class="v">${e.position_uncertainty_m ? "± " + e.position_uncertainty_m + " m" : "car position"}</div></div>
            <div class="fact"><div class="k">Goes to</div><div class="v">${esc(authority(r.jurisdiction))}</div></div>
          </div>
        </div>
      </div>
      <div class="grid two" style="gap:18px">
        <div><h3 class="h3">Why the agents decided this</h3>
          ${trail.length ? `<ul class="timeline">${trail.map((a) => { const [what, why] = describe(a); return `<li>${avatar(a.actor)}<div class="who">${esc(what)} <span class="muted small">· ${esc(actor(a.actor)[0])} · ${ago(a.ts)}</span></div>${why ? `<div class="say">${esc(why).slice(0, 400)}</div>` : ""}</li>`; }).join("")}</ul>` : `<div class="muted">No decisions recorded.</div>`}
          ${r.rationale ? `<div class="callout blue" style="margin-top:4px">${icon("route")}<div><b>Routing:</b> ${esc(r.rationale)}</div></div>` : ""}
        </div>
        <div><h3 class="h3">${pending ? "What you are approving" : "What the authority received"}</h3>
          <div class="payload"><dl>
            <dt>To</dt><dd><b>${esc(p.authority)}</b> <span class="pill">${esc(p.channel === "open311" ? "Open311 API" : "Referral package")}</span></dd>
            <dt>Service</dt><dd class="mono">${esc(p.service_code)}</dd>
            <dt>Location</dt><dd>${esc(p.address_string)}<div class="muted mono">${p.lat}, ${p.long}</div></dd>
            <dt>Description</dt><dd>${esc(p.description)}</dd>
            <dt>Photo</dt><dd><span class="muted">Privacy-blurred frame</span></dd>
            <dt>Attributes</dt><dd>${esc(p.attributes.severity)} severity · ${p.attributes.confirmations} confirmation(s)${p.attributes.p1_candidate ? " · P1 candidate" : ""}</dd>
          </dl><div class="hash">${icon("lock")}<span>SHA-256 <code>${esc(d.payload_hash.slice(0, 16))}…</code> ${pending ? "is locked when you approve: any later change blocks sending." : r.service_request_id ? `· request <b>${esc(r.service_request_id)}</b>` : ""}</span></div></div>
        </div>
      </div>
    </div>
    ${pending ? `<div class="actionbar"><span class="muted small"><span class="kbd">J</span>/<span class="kbd">K</span> next/previous. Sending always needs a click.</span><span class="spacer"></span>
      <button class="btn btn-danger" id="reject">${icon("x")}Reject</button><button class="btn btn-primary btn-lg" id="approve">${icon("send")}Approve &amp; send to ${esc(authority(r.jurisdiction))}</button></div>` : ""}`;
}

function bindDetail(d, after) {
  const id = d.report.id;
  const approve = $("#approve"), reject = $("#reject");
  if (approve) approve.onclick = async () => {
    approve.disabled = true; approve.innerHTML = `${icon("refresh", "spin")}Sending…`;
    try {
      const job = await api(`/api/reports/${id}/approve`, { method: "POST", body: JSON.stringify({ payload_hash: d.payload_hash }) });
      const res = job.result || {};
      if (res.service_request_id) toast(`Sent to ${authority(res.authority)}: request ${res.service_request_id}`);
      else toast(`Not sent: ${res.error || job.error || "unknown error"}`, false);
    } catch (e) { toast(e.message, false); }
    after();
  };
  if (reject) reject.onclick = async () => {
    try { await api(`/api/reports/${id}/reject`, { method: "POST" }); toast("Rejected: it will not be sent."); } catch (e) { toast(e.message, false); }
    after();
  };
}

/* ---------- Review inbox ---------- */
async function renderReview(params) {
  const view = stage();
  const pending = await api("/api/reports?status=pending_approval");
  if (!pending.length) {
    view.innerHTML = `<div class="card">${emptyState("check", "You're all caught up", "New reports appear here after each trip. Nothing is sent to a road authority until you approve it.", `<a class="btn" style="margin-top:12px" href="#/reports">See all reports</a>`)}</div>`;
    return;
  }
  const current = Number(params.get("id")) || pending[0].id;
  view.innerHTML = `<div class="inbox">
      <div class="card"><div class="card-head"><h2>Awaiting review</h2><span class="pill amber">${pending.length}</span></div>
        <div class="inbox-list">${pending.map((r) => `<div class="inbox-item ${r.id === current ? "on" : ""}" data-id="${r.id}">
          <img class="thumb" loading="lazy" src="/api/media/${encodeURIComponent(r.best_event_id)}.jpg?crop=1" alt="">
          <div style="min-width:0"><div class="title">${esc(r.class_name)} <span class="muted small">#${r.id}</span></div>
          <div class="muted small">${esc(r.address || "")} · ${esc(authority(r.jurisdiction))}</div>
          <div class="meta">${sevPill(r.severity)}${flags(r)}</div></div></div>`).join("")}</div></div>
      <div class="card" id="detail"><div class="card-body"><div class="skeleton" style="width:50%"></div></div></div></div>`;
  const ids = pending.map((r) => r.id);
  const open = async (id) => {
    $$(".inbox-item").forEach((x) => x.classList.toggle("on", Number(x.dataset.id) === id));
    history.replaceState(null, "", `#/review?id=${id}`);
    const d = await api(`/api/reports/${id}`);
    $("#detail").innerHTML = reportDetail(d);
    bindDetail(d, () => renderReview(new URLSearchParams(`id=${ids[ids.indexOf(id) + 1] || ""}`)));
    reviewKeys.current = id;
  };
  $$(".inbox-item").forEach((x) => x.onclick = () => open(Number(x.dataset.id)));
  reviewKeys.ids = ids;
  reviewKeys.open = open;
  open(current);
}
const reviewKeys = { ids: [], current: null, open: null };
document.addEventListener("keydown", (ev) => {
  if (!location.hash.startsWith("#/review") || ev.target.matches("input, textarea") || ev.ctrlKey || ev.metaKey) return;
  const k = ev.key.toLowerCase(), i = reviewKeys.ids.indexOf(reviewKeys.current);
  // navigation only: approving or rejecting is never bound to a single key (it sends a report to a road authority)
  if (k === "j" && i < reviewKeys.ids.length - 1) reviewKeys.open(reviewKeys.ids[i + 1]);
  else if (k === "k" && i > 0) reviewKeys.open(reviewKeys.ids[i - 1]);
});

/* ---------- Trips (upload + live progress) ---------- */
async function renderTrips(params) {
  const view = stage();
  const [trips, jobs] = await Promise.all([api("/api/trips"), api("/api/jobs")]);
  const running = jobs.find((j) => j.status === "running");
  view.innerHTML = `
    <div class="grid two">
      <div class="card"><div class="card-head"><h2>New trip</h2><span class="spacer"></span><span class="desc">The laptop plays the in-car device</span></div>
        <form class="card-body grid" id="trip-form" style="gap:18px">
          <label class="dropzone" id="drop"><span class="dz-icon">${icon("upload")}</span><b id="drop-title">Drop a dashcam video here, or click to choose</b><span class="muted small">MP4, MOV, AVI or MKV · up to 500 MB</span>
            <input type="file" id="video" accept=".mp4,.mov,.avi,.mkv,video/*" class="sr-only" required></label>
          <div class="field"><label for="gps">GPS track</label><input type="file" id="gps" accept=".gpx,.csv">
            <span class="muted small">GPX, or CSV with <code>time,lat,lon</code>. Phone GPS logger apps export GPX.</span></div>
          <label class="switch"><input type="checkbox" id="simulate" checked><span>No GPS file: simulate a drive along Spring Garden Rd, Halifax</span></label>
          <div style="display:flex;gap:10px;align-items:center"><button class="btn btn-primary btn-lg" id="start">${icon("upload")}Analyse trip</button>
            <span class="muted small">Only blurred frames of damage leave the device.</span></div>
        </form></div>
      <div class="card"><div class="card-head"><h2>How a trip is processed</h2></div><div class="card-body"><ul class="pipeline">
        <li>${avatar("edge")}<div><b>Edge device</b><div class="muted small">YOLOv8m at 5 frames/s, BoT-SORT tracking, best frame per defect, blur everything but the damage, place it on the road.</div></div></li>
        <li>${avatar("agent:vision")}<div><b>Vision agent</b><div class="muted small">RT-DETR-L second opinion; close-up re-check; real, disputed or false alarm.</div></div></li>
        <li>${avatar("agent:location")}<div><b>Location agent</b><div class="muted small">Road class and route number decide Halifax 311 or Nova Scotia Public Works.</div></div></li>
        <li>${avatar("agent:triage")}<div><b>Triage agent</b><div class="muted small">Merges repeat sightings within 15 m; independent drivers raise priority.</div></div></li>
        <li>${avatar("agent:filing")}<div><b>Filing agent</b><div class="muted small">Drafts the description; sends only what you approve.</div></div></li></ul></div></div>
    </div>
    <div id="job" class="section"></div>
    <div class="card section"><div class="card-head"><h2>All trips</h2><span class="pill">${trips.length}</span></div>${tripsTable(trips)}</div>`;
  const video = $("#video"), drop = $("#drop");
  video.onchange = () => { $("#drop-title").textContent = video.files[0]?.name || "Drop a dashcam video here, or click to choose"; };
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => { video.files = e.dataTransfer.files; video.onchange(); });
  $("#gps").onchange = () => { if ($("#gps").files[0]) $("#simulate").checked = false; };
  $("#trip-form").onsubmit = async (ev) => {
    ev.preventDefault();
    if (!video.files[0]) return toast("Choose a dashcam video first.", false);
    const fd = new FormData();
    fd.append("video", video.files[0]);
    if ($("#gps").files[0]) fd.append("gps", $("#gps").files[0]);
    fd.append("simulate", $("#simulate").checked);
    $("#start").disabled = true;
    try { const job = await api("/api/trips", { method: "POST", body: fd }); watchJob(job.id); }
    catch (e) { toast(e.message, false); $("#start").disabled = false; }
  };
  if (running) watchJob(running.id);
}

const STEPS = [["edge", "Edge device", "video"], ["upload", "Upload", "upload"], ["agents", "Agents", "sparkle"], ["done", "Ready to review", "check"]];
function watchJob(id) {
  const tick = async () => {
    let j;
    try { j = await api(`/api/jobs/${id}`); } catch { return; }
    const at = STEPS.findIndex(([k]) => k === j.step);
    const edge = j.edge || {}, res = j.result || {}, llm = res.llm || {};
    $("#job").innerHTML = `<div class="card"><div class="card-head"><h2>Trip ${esc(j.trip_id)}</h2>${j.status === "failed" ? `<span class="pill red">Failed</span>` : j.status === "done" ? `<span class="pill green">Done</span>` : `<span class="pill blue">Running</span>`}<span class="spacer"></span><span class="muted small">${esc(j.video)} · GPS: ${esc(j.gps)}</span></div>
      <div class="card-body"><div class="steps">${STEPS.map(([k, t, ic], i) => `<div class="step ${i === at && j.status === "running" ? "on" : ""} ${i < at || j.status === "done" ? "ok" : ""}"><div class="t">${icon(i < at || j.status === "done" ? "check" : ic)}${t}</div><div class="d">${i === at ? esc(j.detail || "") : i < at ? stepDone(k, j) : ""}</div>${i === at && j.status === "running" ? `<div class="progress"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>` : ""}</div>`).join("")}</div>
      ${j.status === "failed" ? `<div class="callout red section">${icon("alert")}<div>${esc(j.error)}</div></div>` : ""}
      ${j.status === "done" ? `<div class="callout green section">${icon("sparkle")}<div><b>${res.mode?.startsWith("agents") ? `Agents (${esc(llm.model || "")}, ${llm.calls || 0} LLM calls, ${res.seconds} s)` : "Rule engine"}</b><div>${esc(res.summary || "")}</div></div></div>
        <div style="display:flex;gap:10px;margin-top:14px"><a class="btn btn-primary" href="#/review">${icon("inbox")}Review reports</a><a class="btn" href="#/activity?trip=${encodeURIComponent(j.trip_id)}">See agent trace</a></div>
        <div id="trip-gallery" class="gallery section"></div>` : ""}</div></div>`;
    if (j.status !== "running") {
      clearInterval(t);
      $("#start") && ($("#start").disabled = false);
      if (j.status === "done") {
        const { events } = await api(`/api/trips/${encodeURIComponent(j.trip_id)}`);
        $("#trip-gallery").innerHTML = events.map((e) => `<figure><img loading="lazy" src="/api/media/${encodeURIComponent(e.id)}.jpg?crop=1" alt=""><figcaption><span>${esc(e.class_name)}</span>${e.status === "rejected" ? `<span class="pill">Rejected</span>` : e.class_disputed ? `<span class="pill amber">Disputed</span>` : `<span class="pill green">Confirmed</span>`}</figcaption></figure>`).join("");
        refreshChrome();
      }
    }
  };
  const t = setInterval(tick, 1500);
  timers.push(t);
  tick();
}
const stepDone = (k, j) => k === "edge" && j.edge ? `${j.edge.events} defects · ${j.edge.detector_fps} FPS` : k === "upload" && j.upload ? `${j.upload.accepted} frames uploaded` : "";

/* ---------- Agent activity ---------- */
async function renderActivity(params) {
  const view = stage();
  const all = await api("/api/activity?limit=600");
  const who = params.get("actor") || "all";
  const trip = params.get("trip");
  const agentsOnly = all.filter((a) => a.actor.startsWith("agent:") || a.actor === "driver" || a.actor === "fallback");
  let list = who === "all" ? agentsOnly : agentsOnly.filter((a) => a.actor === who);
  if (trip) list = list.filter((a) => (a.subject || "").includes(trip) || (a.detail || "").includes(trip));
  const groups = ["all", "agent:orchestrator", "agent:vision", "agent:location", "agent:triage", "agent:filing", "agent:follow_up", "driver"];
  view.innerHTML = `
    <div class="toolbar"><div class="tabs" role="tablist">${groups.map((g) => `<button role="tab" aria-selected="${g === who}" class="${g === who ? "on" : ""}" data-g="${g}">${g === "all" ? "All" : esc(actor(g)[0].replace(" agent", ""))}</button>`).join("")}</div>
    ${trip ? `<span class="pill blue">Trip ${esc(trip)} <a href="#/activity" aria-label="Clear trip filter" style="display:inline-flex;margin-left:2px">${icon("x")}</a></span>` : ""}<span class="spacer"></span><span class="muted small">${list.length > 250 ? `Latest 250 of ${num(list.length)}` : `${num(list.length)} entries`}</span></div>
    <div class="card">${list.length ? `<ul class="feed">${list.slice(0, 250).map(activityItem).join("")}</ul>` : emptyState("sparkle", "No agent activity yet", "Process a trip with an OpenRouter key to see the agents plan and decide.")}</div>`;
  $$(".tabs button").forEach((b) => b.onclick = () => location.hash = `#/activity?actor=${encodeURIComponent(b.dataset.g)}${trip ? "&trip=" + encodeURIComponent(trip) : ""}`);
}

function activityItem(a) {
  const [who] = actor(a.actor);
  const [what, why] = describe(a);
  const d = parse(a.detail);
  const isTool = a.action.startsWith("tool:");
  const tool = isTool && typeof d === "object" ? `<details class="tool"><summary>Arguments and result</summary><pre>${esc(JSON.stringify(d, null, 2)).slice(0, 4000)}</pre></details>` : "";
  return `<li>${avatar(a.actor)}<div style="min-width:0;flex:1"><div><span class="what">${esc(what)}</span> <span class="who">· ${esc(who)}</span></div>${why && !isTool ? `<div class="why">${esc(why).slice(0, 900)}</div>` : ""}${tool}</div><span class="when">${ago(a.ts)}</span></li>`;
}

/* ---------- Authorities ---------- */
async function renderAuthorities() {
  const view = stage();
  const a = await api("/api/authorities");
  view.innerHTML = `
    <div class="grid kpis">
      <div class="card kpi"><div class="label">Halifax 311 requests<span class="ic violet">${icon("building")}</span></div><div class="value">${a.open311.length}</div><div class="hint">${a.open311.filter((r) => r.status === "closed").length} closed (repaired)</div></div>
      <div class="card kpi"><div class="label">NS Public Works referrals<span class="ic cyan">${icon("route")}</span></div><div class="value">${a.referrals.length}</div><div class="hint">100-series highways and provincial roads</div></div>
      <div class="card kpi"><div class="label">Driver notifications<span class="ic green">${icon("wrench")}</span></div><div class="value">${a.notifications.length}</div><div class="hint">"Your pothole was fixed"</div></div>
    </div>
    <div class="card section"><div class="card-head"><h2>Halifax 311</h2><span class="desc">Open311 GeoReport v2</span><span class="pill">Mock server</span><span class="spacer"></span>
      <a class="btn btn-sm" href="${esc(a.open311_inbox)}" target="_blank" rel="noopener">${icon("ext")}City staff inbox</a><button class="btn btn-primary btn-sm" id="follow">${icon("refresh")}Run Follow-up agent</button></div>
      ${a.open311.length ? `<table class="table"><thead><tr><th>Request</th><th>Service</th><th>Location</th><th>Description</th><th>Status</th><th>Updated</th></tr></thead><tbody>
      ${a.open311.map((r) => `<tr><td class="mono">${esc(r.service_request_id)}</td><td class="mono">${esc(r.service_code)}</td><td>${esc(r.address)}</td><td style="max-width:420px">${esc(r.description)}</td><td>${r.status === "closed" ? `<span class="pill green">Repaired</span>` : `<span class="pill violet">Open</span>`}</td><td class="muted">${ago(r.updated_datetime)}</td></tr>`).join("")}</tbody></table>`
      : emptyState("building", "Nothing sent to Halifax yet", "Approve a report in Review to send it.")}
      <div class="card-foot">Halifax has no public Open311 API today, so the demo files to a local GeoReport v2 server. Mark a request repaired in the city inbox, then run the Follow-up agent.</div></div>
    <div class="card section"><div class="card-head"><h2>Nova Scotia Public Works</h2><span class="desc">Referrals</span><span class="spacer"></span><span class="muted small">No public API: 1-844-696-7737 · dpw-occ@novascotia.ca</span></div>
      ${a.referrals.length ? `<table class="table"><thead><tr><th>Referral</th><th>Location</th><th>Description</th></tr></thead><tbody>${a.referrals.map((r) => `<tr><td class="mono">${esc(r.id)}</td><td>${esc(r.address)}</td><td>${esc(r.description)}</td></tr>`).join("")}</tbody></table>` : emptyState("route", "No provincial referrals yet", "Damage on Highway 102 and other provincial roads is routed here.")}</div>
    <div class="card section"><div class="card-head"><h2>Driver notifications</h2></div>${a.notifications.length ? `<ul class="feed">${a.notifications.map((n) => `<li>${avatar("agent:follow_up")}<div style="flex:1">${esc(n.message)}</div><span class="when">${ago(n.ts)}</span></li>`).join("")}</ul>` : emptyState("wrench", "No repairs confirmed yet", "When a city closes a request, the Follow-up agent tells the drivers who reported it.")}</div>`;
  $("#follow").onclick = async () => {
    $("#follow").disabled = true;
    try { const j = await api("/api/follow-up", { method: "POST" }); const r = j.result || {}; toast(`Checked ${r.checked || 0} request(s); ${(r.fixed || []).length} repaired`); }
    catch (e) { toast(e.message, false); }
    renderAuthorities();
  };
}

/* ---------- Trust & system ---------- */
async function renderSystem() {
  const view = stage();
  const s = await api("/api/system");
  const h = s.health, llm = s.llm || {};
  const servers = {};
  h.mcp_tools.forEach((t) => (servers[t.split("_")[0]] ||= []).push(t));
  const NAMES = { detector: "Vision · detector MCP", geo: "Location · geo MCP", reports: "Triage · reports MCP", city: "Filing · municipality MCP" };
  const guard = (t, d) => `<li>${icon("check")}<div><b>${t}</b><div class="muted small">${d}</div></div></li>`;
  view.innerHTML = `
    <div class="grid two">
      <div class="card"><div class="card-head"><h2>Guardrails enforced in code</h2></div><div class="card-body"><ul class="list-check">
        ${guard("Nothing is sent without driver approval", "The city tool refuses any report that isn't approved, whatever an agent asks.")}
        ${guard("The driver approves the exact payload", "Approval stores a SHA-256 of what was shown; sending is refused if it changed.")}
        ${guard("Agents can only use their own tools", "Per-agent allow-lists, enforced in the client, not the prompt.")}
        ${guard("No confirmation without evidence", "Damage is confirmed only with a second model's support; disagreements go to a human.")}
        ${guard("Append-only audit log", "Every plan, verdict and tool call is recorded; updates and deletes are blocked by the database.")}
        ${guard("Circuit breaker", "If an LLM fails or is rate-limited, a rule engine finishes the job over the same tools.")}
        ${guard("Kill switch", "ROADSENSE_AGENTS_ENABLED=0 turns the LLM agents off instantly.")}
      </ul></div></div>
      <div class="grid" style="align-content:start">
        <div class="card"><div class="card-head"><h2>Privacy by design</h2></div><div class="card-body"><ul class="list-check">
          ${guard("Redaction on the device", "Everything except the damage is blurred before anything leaves the vehicle; no raw video is uploaded.")}
          ${guard("No images to the LLM", "Agents get text metadata only: ids, classes, confidences, positions.")}
          ${guard("Canadian data residency ready", "Built for Nova Scotia's PIIDPA: host in a Canadian region for municipal use.")}
        </ul></div></div>
        <div class="card"><div class="card-head"><h2>Agent stack</h2><span class="spacer"></span>${h.llm.enabled ? `<span class="pill green"><span class="dot"></span>Live</span>` : `<span class="pill amber">Rule engine</span>`}</div><div class="card-body facts">
          <div class="fact"><div class="k">Mode</div><div class="v">${esc(h.llm.mode)}</div></div>
          <div class="fact"><div class="k">Primary model</div><div class="v small">${esc(h.llm.models[0])}</div></div>
          <div class="fact"><div class="k">Fallbacks</div><div class="v small">${h.llm.models.slice(1).map(esc).join("<br>")}</div></div>
          <div class="fact"><div class="k">Quota</div><div class="v small">${llm.configured ? (llm.free_tier ? "Free tier · 50 req/day" : "Paid credits") : "No key"}</div></div>
        </div></div>
      </div>
    </div>
    <div class="card section"><div class="card-head"><h2>MCP servers and tools</h2><span class="spacer"></span><span class="muted small">${h.mcp_tools.length} tools over stdio</span></div>
      <div class="card-body grid kpis">${Object.entries(servers).map(([k, tools]) => `<div class="server-card"><div class="name">${icon("layers")}${esc(NAMES[k] || k)}<span class="spacer"></span><span class="faint small">${tools.length}</span></div><div class="chip-row">${tools.map((t) => `<span class="pill mono">${esc(t)}</span>`).join("")}</div></div>`).join("")}</div></div>`;
}

/* ---------- command palette (Ctrl/⌘ K) ---------- */
const palette = {
  el: $("#palette"), q: $("#palette-q"), list: $("#palette-list"), pending: [], items: [], sel: 0, opener: null,
  commands() {
    const nav = [["overview", "grid"], ["trips", "video"], ["review", "inbox"], ["reports", "file"], ["map", "map"],
      ["activity", "activity"], ["authorities", "building"], ["system", "shield"]]
      .map(([r, ic]) => ({ group: "Go to", label: ROUTES[r][0], hint: ROUTES[r][1], icon: ic, run: () => (location.hash = `#/${r}`) }));
    const acts = [
      { group: "Actions", label: "New trip", hint: "Upload a dashcam video", icon: "plus", run: () => { location.hash = "#/trips"; setTimeout(() => $("#video")?.click(), 300); } },
      { group: "Actions", label: "Toggle theme", hint: "Light / dark", icon: "moon", run: toggleTheme },
    ];
    const reports = this.pending.map((r) => ({ group: "Awaiting review", label: `${r.class_name} #${r.id}`, hint: r.address || "", icon: "inbox", run: () => (location.hash = `#/review?id=${r.id}`) }));
    return [...nav, ...acts, ...reports];
  },
  open() {
    this.opener = document.activeElement;
    this.el.hidden = false; this.q.value = ""; this.sel = 0; this.render(); this.q.focus();
  },
  close() { this.el.hidden = true; this.opener?.focus?.(); },
  render() {
    const term = this.q.value.trim().toLowerCase();
    this.items = this.commands().filter((c) => !term || `${c.label} ${c.hint} ${c.group}`.toLowerCase().includes(term));
    this.sel = Math.min(this.sel, Math.max(this.items.length - 1, 0));
    let group = "";
    this.list.innerHTML = this.items.length ? this.items.map((c, i) => {
      const head = c.group !== group ? `<li class="palette-group" role="presentation">${esc((group = c.group))}</li>` : "";
      return `${head}<li class="palette-item" role="option" id="pal-${i}" data-i="${i}" aria-selected="${i === this.sel}">${icon(c.icon)}<span>${esc(c.label)}</span><span class="hint">${esc(c.hint)}</span></li>`;
    }).join("") : `<li class="palette-empty">No results for “${esc(term)}”</li>`;
    this.q.setAttribute("aria-activedescendant", this.items.length ? `pal-${this.sel}` : "");
    $(`#pal-${this.sel}`)?.scrollIntoView({ block: "nearest" });
  },
  run(i) { const c = this.items[i]; if (!c) return; this.close(); c.run(); },
};
palette.q.oninput = () => { palette.sel = 0; palette.render(); };
palette.q.onkeydown = (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); palette.sel = (palette.sel + 1) % Math.max(palette.items.length, 1); palette.render(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); palette.sel = (palette.sel - 1 + palette.items.length) % Math.max(palette.items.length, 1); palette.render(); }
  else if (e.key === "Enter") { e.preventDefault(); palette.run(palette.sel); }
  else if (e.key === "Escape") palette.close();
};
palette.list.onclick = (e) => { const li = e.target.closest(".palette-item"); if (li) palette.run(Number(li.dataset.i)); };
palette.list.onmousemove = (e) => { const li = e.target.closest(".palette-item"); if (li && Number(li.dataset.i) !== palette.sel) { palette.sel = Number(li.dataset.i); palette.render(); } };
palette.el.onclick = (e) => { if (e.target === palette.el) palette.close(); };
$("#open-palette").onclick = () => palette.open();
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.el.hidden ? palette.open() : palette.close(); }
  else if (e.key === "Escape" && $("#sidebar").classList.contains("open")) $("#sidebar").classList.remove("open");
});
if (/Mac|iPhone|iPad/.test(navigator.platform)) $("#mod-key").textContent = "⌘";

function toggleTheme() {
  const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("rs-theme", document.documentElement.dataset.theme); } catch (e) {}
}

/* ---------- boot ---------- */
$("#menu").onclick = () => $("#sidebar").classList.toggle("open");
$("#scrim").onclick = () => $("#sidebar").classList.remove("open");
$("#theme").onclick = toggleTheme;
window.addEventListener("hashchange", router);
if (location.hash.includes("new=1")) setTimeout(() => $("#video")?.click(), 300);
router();
setInterval(refreshChrome, 15000);
