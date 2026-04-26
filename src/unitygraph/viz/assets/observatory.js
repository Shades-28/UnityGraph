/* =========================================================================
   UnityGraph Observatory -- live force-directed galaxy
   ========================================================================= */

const TYPE_COLORS = {
  Script:             "#FF8C42",
  GameObject:         "#58B4FF",
  Component:          "#C4C9D4",
  Scene:              "#8B6AFF",
  Prefab:             "#45CBA0",
  AnimatorController: "#E4A57A",
  AnimState:          "#BFA8FF",
  ShaderGraph:        "#FF7A92",
};

const TYPE_ORDER = [
  "Script", "GameObject", "Component", "Scene", "Prefab",
  "AnimatorController", "AnimState", "ShaderGraph",
];

const EDGE_STYLES = {
  attached_to:     { color: "rgba(196, 201, 212, 0.35)", dashed: false, width: 0.6 },
  co_exists_with:  { color: "rgba(196, 201, 212, 0.14)", dashed: false, width: 0.3 },
  depends_on:      { color: "rgba(255, 140, 66, 0.45)", dashed: false, width: 0.7 },
  subscribes_to:   { color: "rgba(255, 122, 146, 0.55)", dashed: true,  width: 0.8 },
  inherits:        { color: "rgba(69, 203, 160, 0.45)", dashed: false, width: 0.7 },
  calls:           { color: "rgba(88, 180, 255, 0.4)",  dashed: false, width: 0.6 },
  instantiates:    { color: "rgba(191, 168, 255, 0.45)", dashed: false, width: 0.6 },
  is_variant_of:   { color: "rgba(139, 106, 255, 0.6)", dashed: false, width: 0.9 },
  overrides:       { color: "rgba(255, 140, 66, 0.3)",  dashed: true,  width: 0.5 },
  transitions_to:  { color: "rgba(228, 165, 122, 0.5)", dashed: false, width: 0.7 },
  loads_scene:     { color: "rgba(139, 106, 255, 0.4)", dashed: true,  width: 0.6 },
  contains_state:  { color: "rgba(228, 165, 122, 0.35)", dashed: false, width: 0.5 },
  has_animator:    { color: "rgba(228, 165, 122, 0.45)", dashed: false, width: 0.6 },
  uses_subgraph:   { color: "rgba(255, 122, 146, 0.5)", dashed: true,  width: 0.7 },
};

const state = {
  graph: null,            // raw from server
  forceData: null,        // { nodes, links } passed to ForceGraph
  hoverNodeId: null,
  selectedNodeId: null,
  mutedTypes: new Set(),
  search: "",
  filterOrphans: false,
  filterExternal: false,
  newIds: new Set(),      // nodes that arrived in the last update (for animation)
  nodeTimestamps: new Map(),
  graphInstance: null,
  sse: null,
  scope: "user",          // "user" (default -- usable on huge projects) or "all"
};

/* -------------------------------------------------------------------------
   Starfield backdrop
   ------------------------------------------------------------------------- */

(function starfield() {
  const canvas = document.getElementById("starfield");
  const ctx = canvas.getContext("2d");
  let stars = [];
  let w = 0, h = 0;
  let dpr = window.devicePixelRatio || 1;

  function resize() {
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + "px"; canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.floor((w * h) / 7000);
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      r: Math.random() * 0.9 + 0.25,
      a: Math.random() * 0.45 + 0.1,
      twinklePhase: Math.random() * Math.PI * 2,
      twinkleSpeed: 0.25 + Math.random() * 0.5,
      driftX: (Math.random() - 0.5) * 0.02,
      driftY: (Math.random() - 0.5) * 0.02,
    }));
  }

  window.addEventListener("resize", resize);
  resize();

  function frame(ts) {
    ctx.clearRect(0, 0, w, h);
    const t = ts / 1000;
    for (const s of stars) {
      const a = s.a * (0.55 + 0.45 * Math.sin(t * s.twinkleSpeed + s.twinklePhase));
      s.x += s.driftX;
      s.y += s.driftY;
      if (s.x < 0) s.x = w; if (s.x > w) s.x = 0;
      if (s.y < 0) s.y = h; if (s.y > h) s.y = 0;
      ctx.globalAlpha = a;
      ctx.fillStyle = "#E8ECF7";
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();

/* -------------------------------------------------------------------------
   ForceGraph init
   ------------------------------------------------------------------------- */

const container = document.getElementById("graph");
const fg = ForceGraph()(container);
state.graphInstance = fg;

function paintNode(node, ctx, globalScale) {
  if (isHidden(node)) return;

  const x = node.x, y = node.y;
  const color = TYPE_COLORS[node.type] || "#C4C9D4";
  const base = radiusForNode(node);

  const now = performance.now();
  const bornAt = state.nodeTimestamps.get(node.id) || now;
  const age = now - bornAt;
  const entryProgress = Math.min(1, age / 650);
  const easedEntry = 1 - Math.pow(1 - entryProgress, 3);

  const isHover = state.hoverNodeId === node.id;
  const isSelected = state.selectedNodeId === node.id;
  const matchesSearch = state.search && node.name.toLowerCase().includes(state.search);

  const radius = base * easedEntry * (isHover ? 1.4 : isSelected ? 1.25 : 1.0);
  const glowScale = isHover ? 3.8 : isSelected ? 3.2 : matchesSearch ? 2.6 : 1.9;
  const alpha = state.mutedTypes.has(node.type) ? 0.18 : easedEntry;

  // Outer glow
  ctx.save();
  ctx.globalAlpha = alpha * (isHover ? 0.85 : isSelected ? 0.7 : 0.45);
  ctx.shadowBlur = radius * glowScale;
  ctx.shadowColor = color;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, radius * 0.9, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // Solid core
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = "#05070D";
  ctx.beginPath();
  ctx.arc(x, y, radius * 0.55, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.4 / globalScale;
  ctx.beginPath();
  ctx.arc(x, y, radius * 0.55, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();

  // Label
  const showLabel = globalScale > 0.85 || isHover || isSelected || matchesSearch;
  if (showLabel) {
    const fontSize = Math.max(3, Math.min(11, 10 / globalScale));
    ctx.save();
    ctx.globalAlpha = alpha * (isHover ? 1.0 : 0.82);
    ctx.font = `500 ${fontSize}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = "#E8ECF7";
    ctx.shadowBlur = 6;
    ctx.shadowColor = "rgba(5, 7, 13, 0.8)";
    const label = node.name.length > 26 ? node.name.slice(0, 24) + "..." : node.name;
    ctx.fillText(label, x, y + radius + 4 / globalScale);
    ctx.restore();
  }
}

function paintLink(link, ctx, globalScale) {
  const s = link.source, t = link.target;
  if (!s || !t || typeof s.x !== "number" || typeof t.x !== "number") return;
  if (isHidden(s) || isHidden(t)) return;

  const style = EDGE_STYLES[link.type] || { color: "rgba(196, 201, 212, 0.2)", dashed: false, width: 0.4 };
  const isHot =
    state.hoverNodeId === s.id || state.hoverNodeId === t.id ||
    state.selectedNodeId === s.id || state.selectedNodeId === t.id;
  const muted =
    state.mutedTypes.has(s.type) || state.mutedTypes.has(t.type);

  ctx.save();
  ctx.strokeStyle = style.color;
  ctx.lineWidth = (isHot ? style.width * 2.4 : style.width) / Math.sqrt(globalScale);
  ctx.globalAlpha = muted ? 0.12 : isHot ? 1.0 : 0.78;
  if (style.dashed) {
    ctx.setLineDash([4 / globalScale, 3 / globalScale]);
  }
  ctx.beginPath();
  ctx.moveTo(s.x, s.y);
  ctx.lineTo(t.x, t.y);
  ctx.stroke();
  ctx.restore();
}

function radiusForNode(node) {
  const base = 2.4;
  const d = node.degree || 1;
  return base + Math.sqrt(d) * 1.2;
}

function isHidden(node) {
  if (state.filterOrphans && (node.degree || 0) === 0) return true;
  if (state.filterExternal && node.meta && node.meta.external) return true;
  return false;
}

fg
  .backgroundColor("rgba(0,0,0,0)")
  .nodeCanvasObject(paintNode)
  .nodePointerAreaPaint((node, color, ctx) => {
    if (isHidden(node)) return;
    const r = radiusForNode(node) * 1.6;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.fill();
  })
  .linkCanvasObject(paintLink)
  .linkCanvasObjectMode(() => "replace")
  .linkDirectionalParticles(link => {
    if (!state.hoverNodeId && !state.selectedNodeId) return 0;
    const active = state.hoverNodeId || state.selectedNodeId;
    const s = link.source?.id || link.source;
    const t = link.target?.id || link.target;
    return (s === active || t === active) ? 3 : 0;
  })
  .linkDirectionalParticleSpeed(0.006)
  .linkDirectionalParticleWidth(1.5)
  .linkDirectionalParticleColor(link => {
    const style = EDGE_STYLES[link.type];
    return style ? style.color.replace(/[\d.]+\)$/, "0.9)") : "rgba(255,255,255,0.8)";
  })
  .onNodeHover(node => {
    state.hoverNodeId = node ? node.id : null;
    container.style.cursor = node ? "pointer" : "";
  })
  .onNodeClick(node => showDetail(node))
  .onLinkClick(link => showEdgeDetail(link))
  .onLinkHover(link => { container.style.cursor = link ? "pointer" : ""; })
  .onBackgroundClick(() => { hideDetail(); hideEdgeDetail(); })
  .cooldownTicks(180)
  .d3AlphaDecay(0.015)
  .d3VelocityDecay(0.28)
  .warmupTicks(80);

// Tune the forces for a "breathing" galaxy feel
fg.d3Force("charge").strength(-80);
fg.d3Force("link").distance(link => {
  if (link.type === "co_exists_with") return 22;
  if (link.type === "attached_to") return 28;
  if (link.type === "depends_on") return 38;
  return 32;
});

function resize() {
  fg.width(window.innerWidth).height(window.innerHeight);
}
window.addEventListener("resize", resize);
resize();

/* -------------------------------------------------------------------------
   Data fetch + SSE
   ------------------------------------------------------------------------- */

async function fetchGraph() {
  const scope = state.scope || "user";
  const resp = await fetch(`/graph.json?scope=${encodeURIComponent(scope)}`);
  if (!resp.ok) throw new Error("graph fetch failed");
  return await resp.json();
}

function applyGraph(graph) {
  const prevIds = new Set((state.forceData?.nodes || []).map(n => n.id));
  const newIds = new Set();
  const preservedNodes = new Map();
  for (const n of state.forceData?.nodes || []) preservedNodes.set(n.id, n);

  const nodes = graph.nodes.map(n => {
    const existing = preservedNodes.get(n.id);
    if (existing) {
      // Preserve simulation position across reloads so the graph doesn't jump.
      return Object.assign(existing, n);
    }
    newIds.add(n.id);
    state.nodeTimestamps.set(n.id, performance.now());
    return { ...n };
  });

  const removedIds = [...prevIds].filter(id => !graph.nodes.find(n => n.id === id));

  state.forceData = {
    nodes,
    links: graph.links.map(l => ({ ...l })),
  };
  state.graph = graph;
  state.newIds = newIds;

  fg.graphData(state.forceData);
  renderChrome();

  if (prevIds.size > 0 && (newIds.size > 0 || removedIds.length > 0)) {
    const msg = [];
    if (newIds.size) msg.push(`+${newIds.size}`);
    if (removedIds.length) msg.push(`−${removedIds.length}`);
    showToast(`graph updated  ${msg.join("  ")}`);
  }

  updateConnection("live", "live");
}

async function connectSSE() {
  if (state.sse) state.sse.close();
  const es = new EventSource("/events");
  state.sse = es;

  es.addEventListener("open", () => updateConnection("live", "live"));
  es.addEventListener("ready", () => updateConnection("live", "live"));
  es.addEventListener("graph", async () => {
    try {
      const graph = await fetchGraph();
      applyGraph(graph);
    } catch (err) {
      console.warn("reload failed", err);
    }
  });
  es.addEventListener("error", () => {
    updateConnection("reconnecting", "reconnecting");
    // EventSource auto-reconnects; nothing else to do here.
  });
}

function updateConnection(cls, label) {
  const el = document.getElementById("connection");
  el.classList.remove("live");
  if (cls === "live") el.classList.add("live");
  const span = el.querySelector(".connection-label");
  span.textContent = "";
  span.setAttribute("data-label", label);
}

/* -------------------------------------------------------------------------
   Chrome (legend, stats, title)
   ------------------------------------------------------------------------- */

function renderChrome() {
  // Title
  const root = state.graph?.project_root || "";
  const name = root.split(/[\\/]/).filter(Boolean).pop() || "project";
  document.getElementById("project-name").textContent = name;

  // Stats
  const stats = state.graph?.stats || {};
  const totals = state.graph?.totals || {};
  const filter = state.graph?.filter || {};
  const shownNodes = state.graph?.nodes?.length ?? stats.n_nodes;
  const shownLinks = state.graph?.links?.length ?? stats.n_edges;
  const nodeLabel = filter.applied
    ? `${formatNum(shownNodes)} <span class="stat-dim">/ ${formatNum(stats.n_nodes)}</span>`
    : formatNum(stats.n_nodes);
  const edgeLabel = filter.applied
    ? `${formatNum(shownLinks)} <span class="stat-dim">/ ${formatNum(stats.n_edges)}</span>`
    : formatNum(stats.n_edges);
  document.getElementById("stats").innerHTML = `
    <span class="stat-item"><span>nodes</span><span class="stat-value">${nodeLabel}</span></span>
    <span class="stat-item"><span>edges</span><span class="stat-value">${edgeLabel}</span></span>
    <span class="stat-item"><span>build</span><span class="stat-value">${stats.build_ms ?? 0}ms</span></span>
  `;

  // Scope note
  const note = document.getElementById("scope-note");
  if (note) {
    if (filter.scope === "user" && filter.applied) {
      const truncSuffix = filter.truncated
        ? ` <span class="warn">capped at ${formatNum(filter.max_nodes)}</span>`
        : "";
      note.innerHTML = `showing ${formatNum(shownNodes)} of ${formatNum(stats.n_nodes)} nodes${truncSuffix}`;
    } else {
      note.textContent = `showing all ${formatNum(stats.n_nodes)} nodes`;
    }
  }

  // Legend
  const counts = {};
  for (const n of state.graph?.nodes || []) counts[n.type] = (counts[n.type] || 0) + 1;
  const legend = document.getElementById("legend-list");
  legend.innerHTML = "";
  for (const type of TYPE_ORDER) {
    if (!counts[type]) continue;
    const li = document.createElement("li");
    if (state.mutedTypes.has(type)) li.classList.add("muted");
    li.innerHTML = `
      <span class="legend-dot" style="background: ${TYPE_COLORS[type]}; box-shadow: 0 0 8px ${TYPE_COLORS[type]}"></span>
      <span>${type}</span>
      <span class="legend-count">${counts[type]}</span>
    `;
    li.addEventListener("click", () => {
      if (state.mutedTypes.has(type)) state.mutedTypes.delete(type);
      else state.mutedTypes.add(type);
      renderChrome();
      fg.graphData(state.forceData);
    });
    legend.appendChild(li);
  }
}

function formatNum(n) {
  if (n == null) return "--";
  return new Intl.NumberFormat().format(n);
}

/* -------------------------------------------------------------------------
   Detail card
   ------------------------------------------------------------------------- */

function showDetail(node) {
  state.selectedNodeId = node.id;
  const card = document.getElementById("detail");
  card.hidden = false;
  card.style.setProperty("--accent", TYPE_COLORS[node.type] || "#C4C9D4");
  document.getElementById("detail-type").textContent = node.type;
  document.getElementById("detail-name").textContent = node.name;

  const body = document.getElementById("detail-body");
  body.innerHTML = "";

  const rows = describeNode(node);
  for (const [label, value, opts] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    body.appendChild(dt);
    const dd = document.createElement("dd");
    if (opts?.tags && Array.isArray(value)) {
      dd.className = "tags";
      for (const tag of value) {
        const span = document.createElement("span");
        span.className = "tag";
        span.textContent = tag;
        dd.appendChild(span);
      }
    } else if (opts?.kv && value && typeof value === "object") {
      for (const [k, v] of Object.entries(value)) {
        const row = document.createElement("div");
        row.className = "kv-row";
        row.innerHTML = `<span class="kv-key">${escapeHTML(k)}</span><span class="kv-val${opts?.highlight?.includes(k) ? " override" : ""}">${escapeHTML(v)}</span>`;
        dd.appendChild(row);
      }
    } else {
      dd.textContent = value;
    }
    body.appendChild(dd);
  }

  positionDetailCard();
}

function describeNode(node) {
  const rows = [];
  rows.push(["identity", node.id]);
  rows.push(["degree", node.degree]);
  const m = node.meta || {};

  if (node.type === "Script") {
    if (m.namespace) rows.push(["namespace", m.namespace]);
    if (m.file_path) rows.push(["file", m.file_path]);
    if (m.script_type) rows.push(["kind", m.script_type]);
    if (m.execution_order != null) rows.push(["execution order", m.execution_order]);
    if (m.fields && m.fields.length) {
      const field_names = m.fields.map(f => f.name + (f.default != null ? ` = ${f.default}` : ""));
      rows.push(["serialized fields", field_names, { tags: true }]);
    }
    if (m.methods && m.methods.length) rows.push(["methods", m.methods, { tags: true }]);
  } else if (node.type === "GameObject") {
    if (m.scope) rows.push(["scope", m.scope]);
    if (m.tag) rows.push(["tag", m.tag]);
    if (m.layer != null) rows.push(["layer", m.layer]);
    if (m.is_active != null) rows.push(["active", m.is_active ? "yes" : "no"]);
  } else if (node.type === "Component") {
    if (m.component_type) rows.push(["component", m.component_type]);
    if (m.scope) rows.push(["scope", m.scope]);
    if (m.inspector_values && Object.keys(m.inspector_values).length) {
      const simple = {};
      for (const [k, v] of Object.entries(m.inspector_values)) {
        if (typeof v !== "object") simple[k] = v;
      }
      if (Object.keys(simple).length) rows.push(["inspector", simple, { kv: true }]);
    }
  } else if (node.type === "Scene" || node.type === "Prefab") {
    if (m.file_path) rows.push(["file", m.file_path]);
  } else if (node.type === "AnimatorController") {
    if (m.parameters && m.parameters.length) {
      rows.push(["parameters", m.parameters.map(p => `${p.name}: ${p.type}`), { tags: true }]);
    }
    if (m.layers && m.layers.length) {
      rows.push(["layers", m.layers.map(l => l.name), { tags: true }]);
    }
  } else if (node.type === "AnimState") {
    if (m.controller) rows.push(["controller", m.controller]);
  } else if (node.type === "ShaderGraph") {
    if (m.properties && m.properties.length) rows.push(["properties", m.properties, { tags: true }]);
    if (m.output_slots && m.output_slots.length) rows.push(["output slots", m.output_slots, { tags: true }]);
  }
  return rows;
}

function escapeHTML(v) {
  if (v == null) return "";
  const text = typeof v === "string" ? v : JSON.stringify(v);
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function positionDetailCard() {
  const card = document.getElementById("detail");
  const w = window.innerWidth, h = window.innerHeight;
  card.style.right = "28px";
  card.style.bottom = "80px";
  card.style.left = "auto";
  card.style.top = "auto";
  if (w < 768) {
    card.style.left = "16px";
    card.style.right = "16px";
    card.style.bottom = "80px";
  }
}

function hideDetail() {
  state.selectedNodeId = null;
  document.getElementById("detail").hidden = true;
}

document.getElementById("detail-close").addEventListener("click", hideDetail);

/* -------------------------------------------------------------------------
   Evidence popover (v2.0) -- click an edge, see where it lives in source
   ------------------------------------------------------------------------- */

function showEdgeDetail(link) {
  if (!link) return;
  let card = document.getElementById("edge-detail");
  if (!card) {
    card = document.createElement("div");
    card.id = "edge-detail";
    card.className = "detail-card edge-detail";
    card.innerHTML = `
      <header>
        <span id="edge-detail-type" class="detail-type"></span>
        <span id="edge-detail-title" class="detail-name"></span>
        <button id="edge-detail-close" class="close" aria-label="Close">×</button>
      </header>
      <div id="edge-detail-body" class="detail-body"></div>`;
    document.body.appendChild(card);
    card.querySelector("#edge-detail-close").addEventListener("click", hideEdgeDetail);
  }
  card.hidden = false;
  const style = EDGE_STYLES[link.type];
  if (style) card.style.setProperty("--accent", style.color.replace(/[\d.]+\)$/, "0.9)"));

  const srcId = typeof link.source === "object" ? link.source.id : link.source;
  const dstId = typeof link.target === "object" ? link.target.id : link.target;
  const nodesById = new Map((state.forceData?.nodes || []).map(n => [n.id, n]));
  const srcName = nodesById.get(srcId)?.name || srcId;
  const dstName = nodesById.get(dstId)?.name || dstId;

  document.getElementById("edge-detail-type").textContent = link.type;
  document.getElementById("edge-detail-title").textContent = `${srcName} → ${dstName}`;

  const body = document.getElementById("edge-detail-body");
  body.innerHTML = "";

  const sites = link.sites || [];
  if (!sites.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "no evidence sites -- this edge was inferred from structure alone.";
    body.appendChild(empty);
  } else {
    const header = document.createElement("dt");
    header.textContent = `${sites.length} evidence site${sites.length === 1 ? "" : "s"}`;
    body.appendChild(header);
    const list = document.createElement("ul");
    list.className = "sites";
    for (const site of sites) {
      const li = document.createElement("li");
      li.className = `site site-${site.kind || "unknown"}`;
      const kindTag = document.createElement("span");
      kindTag.className = "site-kind";
      kindTag.textContent = site.kind || "";
      const loc = document.createElement("span");
      loc.className = "site-loc";
      loc.textContent = `${site.file}:${site.line}`;
      li.appendChild(kindTag);
      li.appendChild(loc);
      if (site.containing_method) {
        const cm = document.createElement("span");
        cm.className = "site-method";
        cm.textContent = `in ${site.containing_method}()`;
        li.appendChild(cm);
      }
      if (site.snippet) {
        const code = document.createElement("pre");
        code.className = "site-snippet";
        code.textContent = site.snippet;
        li.appendChild(code);
      }
      list.appendChild(li);
    }
    body.appendChild(list);
  }
  // Position mirrors showDetail but to the left edge so both cards can coexist.
  const w = window.innerWidth;
  card.style.left = "28px";
  card.style.bottom = "80px";
  card.style.right = "auto";
  card.style.top = "auto";
  if (w < 768) {
    card.style.left = "16px";
    card.style.right = "16px";
    card.style.bottom = "80px";
  }
}

function hideEdgeDetail() {
  const card = document.getElementById("edge-detail");
  if (card) card.hidden = true;
}

/* -------------------------------------------------------------------------
   Search
   ------------------------------------------------------------------------- */

document.getElementById("search").addEventListener("input", (e) => {
  state.search = e.target.value.trim().toLowerCase();
  if (state.search && state.forceData) {
    const match = state.forceData.nodes.find(n => n.name.toLowerCase().includes(state.search));
    if (match) {
      fg.centerAt(match.x, match.y, 600);
      fg.zoom(2.2, 600);
    }
  }
});

/* -------------------------------------------------------------------------
   Filters
   ------------------------------------------------------------------------- */

document.getElementById("filter-orphans").addEventListener("change", (e) => {
  state.filterOrphans = e.target.checked;
  if (state.forceData) fg.graphData(state.forceData);
});
document.getElementById("filter-external").addEventListener("change", (e) => {
  state.filterExternal = e.target.checked;
  if (state.forceData) fg.graphData(state.forceData);
});

// Scope toggle -- refetches the graph with a different ?scope=... so huge
// projects can start narrow and opt into the full view.
for (const id of ["scope-user", "scope-all"]) {
  document.getElementById(id).addEventListener("change", async (e) => {
    if (!e.target.checked) return;
    state.scope = e.target.value;
    document.getElementById("scope-note").textContent = "loading...";
    try {
      const graph = await fetchGraph();
      applyGraph(graph);
      fg.zoomToFit(900, 80);
    } catch (err) {
      console.error("scope switch failed:", err);
      document.getElementById("scope-note").textContent = "failed to load";
    }
  });
}

/* -------------------------------------------------------------------------
   Control buttons
   ------------------------------------------------------------------------- */

document.getElementById("btn-recenter").addEventListener("click", () => {
  fg.zoomToFit(600, 60);
});

document.getElementById("btn-fullscreen").addEventListener("click", () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
});

/* -------------------------------------------------------------------------
   Toast
   ------------------------------------------------------------------------- */

let toastTimer = null;
function showToast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2800);
}

/* -------------------------------------------------------------------------
   Boot
   ------------------------------------------------------------------------- */

(async function boot() {
  try {
    const graph = await fetchGraph();
    applyGraph(graph);
    fg.zoomToFit(900, 80);
  } catch (err) {
    console.error("initial graph load failed:", err);
    updateConnection("offline", "offline");
  }
  connectSSE();
})();
