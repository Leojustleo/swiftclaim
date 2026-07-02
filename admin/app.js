const API = "http://localhost:8000/api";

function getToken() { return localStorage.getItem("sc_admin_token") || ""; }
function authHeaders() { return { "Authorization": `Bearer ${getToken()}`, "Content-Type": "application/json" }; }

async function apiFetch(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders(), ...opts });
  if (r.status === 401) { localStorage.removeItem("sc_admin_token"); location.href = "login.html"; }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── State ────────────────────────────────────────────
let allCases = [];
let activeFilter = "all";
let activeCaseId = null;
let currentView = "dashboard";

// ── Formatters ───────────────────────────────────────
function fmt(n) {
  if (n == null || n === 0) return "—";
  return new Intl.NumberFormat("sv-SE").format(n) + " kr";
}
function fmtShort(n) {
  if (!n) return "—";
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace(".", ",") + " Mkr";
  if (n >= 1000) return Math.round(n / 1000) + " tkr";
  return n + " kr";
}
function strengthColor(v) {
  if (v >= 70) return "#2ecc71";
  if (v >= 40) return "#f39c12";
  return "#e74c3c";
}

const STATUS_LABELS = {
  intake: "Inkommen", analysis: "Analys", draft: "Utkast",
  negotiation: "Förhandling", appealed: "ARN", closed: "Avslutad"
};
const STATUS_COLORS = {
  intake: "#6b7a99", analysis: "#3498db", draft: "#9b59b6",
  negotiation: "#f39c12", appealed: "#e74c3c", closed: "#2ecc71"
};
const DECISION_LABELS = {
  paid: "Fullt betalt", partial: "Delvis betalt", Underbetalt: "Underbetalt",
  denied: "Nekat", pending: "Avvaktar"
};
const PRIO_CONF = {
  high: { label: "Hög prio", color: "#e74c3c", bg: "#fde8e8" },
  medium: { label: "Medel", color: "#f39c12", bg: "#fef3cd" },
  low: { label: "Låg prio", color: "#2ecc71", bg: "#d4edda" },
  unscored: { label: "Ej poängsatt", color: "#6b7a99", bg: "#eee" },
};

// ── Dashboard rendering ──────────────────────────────
function renderDashboard(s) {
  // Metrics
  document.getElementById("m-total").textContent = s.total_cases;
  document.getElementById("m-active").textContent = s.active_cases;
  document.getElementById("m-gap").textContent = s.total_gap_sek > 0 ? fmtShort(s.total_gap_sek) : "—";
  document.getElementById("m-gap-sub").textContent = s.total_gap_sek > 0
    ? `Yrkat ${fmtShort(s.total_claimed_sek)} · Erbjudet ${fmtShort(s.total_offered_sek)}`
    : "";
  document.getElementById("m-strength").textContent = s.avg_claim_strength != null ? s.avg_claim_strength : "—";

  // Pipeline
  const pipeline = document.getElementById("pipeline");
  const pipeOrder = ["intake", "analysis", "draft", "negotiation", "appealed", "closed"];
  pipeline.innerHTML = pipeOrder.map(k => {
    const n = s.status_counts[k] || 0;
    const color = STATUS_COLORS[k];
    return `<div class="pipe-step${n === 0 ? " pipe-step--empty" : ""}">
      <div class="pipe-dot" style="background:${color}"></div>
      <div class="pipe-label">${STATUS_LABELS[k]}</div>
      <div class="pipe-count" style="color:${n > 0 ? color : "var(--muted)"}">${n}</div>
      ${pipeOrder.indexOf(k) < pipeOrder.length - 1 ? '<div class="pipe-arrow">→</div>' : ""}
    </div>`;
  }).join("");

  // Priority
  const total = s.total_cases || 1;
  document.getElementById("priorityList").innerHTML = Object.entries(PRIO_CONF).map(([k, conf]) => {
    const n = s.priority_counts[k] || 0;
    const pct = Math.round((n / total) * 100);
    return `<div class="bar-row">
      <div class="bar-row-label">
        <span class="bar-dot" style="background:${conf.color}"></span>
        ${conf.label}
      </div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${conf.color}"></div></div>
      <div class="bar-count">${n}</div>
    </div>`;
  }).join("");

  // Decisions
  const allDecisions = Object.entries(s.decision_counts).sort((a, b) => b[1] - a[1]);
  const maxDec = Math.max(...allDecisions.map(x => x[1]), 1);
  document.getElementById("decisionList").innerHTML = allDecisions.map(([k, n]) => `
    <div class="bar-row">
      <div class="bar-row-label">${DECISION_LABELS[k] || k}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(n / maxDec) * 100}%;background:#3498db"></div></div>
      <div class="bar-count">${n}</div>
    </div>`).join("") || '<div class="empty-state">Inga beslut ännu</div>';

  // Categories
  const allCats = Object.entries(s.category_counts).sort((a, b) => b[1] - a[1]);
  const maxCat = Math.max(...allCats.map(x => x[1]), 1);
  document.getElementById("categoryList").innerHTML = allCats.map(([k, n]) => `
    <div class="bar-row">
      <div class="bar-row-label">${k}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(n / maxCat) * 100}%;background:#9b59b6"></div></div>
      <div class="bar-count">${n}</div>
    </div>`).join("") || '<div class="empty-state">Inga ärenden ännu</div>';

  // Recent cases table
  document.getElementById("recentBody").innerHTML = s.recent_cases.map(c => {
    const sc = c.scorecard;
    const prio = sc ? (PRIO_CONF[sc.priority] || PRIO_CONF.unscored) : PRIO_CONF.unscored;
    const status = c.status || "intake";
    return `<tr class="table-row" data-id="${c.id}">
      <td class="td-id">${c.id}</td>
      <td>${c.customer_name || "—"}</td>
      <td>${c.insurance_company || "—"}</td>
      <td>${c.damage_category || "—"}</td>
      <td>${fmt(c.claim_amount)}</td>
      <td>${fmt(c.insurer_amount)}</td>
      <td><span class="status-chip" style="background:${STATUS_COLORS[status]}20;color:${STATUS_COLORS[status]}">${STATUS_LABELS[status] || status}</span></td>
      <td><span class="badge" style="background:${prio.bg};color:${prio.color}">${prio.label}</span></td>
    </tr>`;
  }).join("") || `<tr><td colspan="8" style="color:var(--muted);padding:20px;text-align:center">Inga ärenden ännu</td></tr>`;

  // Clicking recent case row → switch to cases view + open case
  document.querySelectorAll(".table-row").forEach(row => {
    row.addEventListener("click", () => {
      switchView("cases");
      openCase(row.dataset.id);
    });
  });
}

async function loadDashboard() {
  try {
    const s = await apiFetch("/admin/stats");
    renderDashboard(s);
  } catch (e) {
    console.error("Dashboard load failed", e);
  }
}

// ── View switching ───────────────────────────────────
function switchView(view) {
  currentView = view;
  document.querySelectorAll(".view").forEach(el => el.style.display = "none");
  document.getElementById(`view-${view}`).style.display = "";
  document.querySelectorAll(".nav-tab").forEach(t => t.classList.toggle("active", t.dataset.view === view));
  if (view === "cases" && allCases.length === 0) loadCases();
  if (view === "review") loadReview();
}

document.querySelectorAll(".nav-tab").forEach(tab => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

// ── Case list (cases view) ───────────────────────────
function priorityBadge(sc) {
  if (!sc) return '<span class="badge badge-unknown">—</span>';
  const conf = PRIO_CONF[sc.priority] || PRIO_CONF.unscored;
  return `<span class="badge" style="background:${conf.bg};color:${conf.color}">${conf.label}</span>`;
}

function renderCaseRow(c) {
  const sc = c.scorecard;
  const strength = sc ? sc.claim_strength : null;
  const date = c.created_at ? c.created_at.slice(0, 10) : "—";
  return `
    <div class="case-row${c.id === activeCaseId ? " active" : ""}" data-id="${c.id}">
      <div class="row-id">${c.id}</div>
      <div class="row-main">
        <div class="row-name">${c.customer_name || "Okänd"}</div>
        <div class="row-sub">${c.insurance_company || "—"} · ${c.damage_category || "—"} · ${date}</div>
      </div>
      <div class="row-right">
        ${priorityBadge(sc)}
        <div>
          <div class="strength-bar">
            <div class="strength-fill" style="width:${strength ?? 0}%;background:${strengthColor(strength ?? 0)}"></div>
          </div>
          <div class="strength-label">${strength != null ? strength + " / 100" : "—"}</div>
        </div>
      </div>
    </div>`;
}

function renderScorecard(sc, loading = false) {
  if (loading) {
    return `<div class="scorecard">
      <div class="sc-title">AI Scorecard</div>
      <div class="sc-skeleton" style="width:40%;height:40px;margin-bottom:16px"></div>
      <div class="sc-skeleton" style="width:80%"></div>
      <div class="sc-skeleton" style="width:65%"></div>
      <div class="sc-skeleton" style="width:75%;margin-top:8px"></div>
    </div>`;
  }
  if (!sc) return "";
  if (sc.claim_strength == null) {
    return `<div class="scorecard"><div class="sc-title">AI Scorecard</div>
      <div class="sc-error">Scorecard kunde inte genereras automatiskt (degraderat läge).</div></div>`;
  }
  const refs = sc.arn_references && sc.arn_references.length
    ? `<div class="sc-refs">Källor: ${sc.arn_references.map(r => "ARN " + r).join(", ")}</div>`
    : "";
  return `<div class="scorecard">
    <div class="sc-title">AI Scorecard</div>
    <div class="sc-metrics">
      <div class="sc-metric">
        <label>Ärendestyrka</label>
        <div class="val">${sc.claim_strength}</div>
        <div class="sc-bar"><div class="sc-bar-fill" style="width:${sc.claim_strength}%"></div></div>
      </div>
      <div class="sc-metric">
        <label>Vinstchans</label>
        <div class="val">${sc.win_probability}</div>
        <div class="sc-bar"><div class="sc-bar-fill" style="width:${parseInt(sc.win_probability)}%"></div></div>
      </div>
      <div class="sc-metric">
        <label>Prioritet</label>
        <div class="val-text">${{ high: "🔴 Hög", medium: "🟡 Medel", low: "🟢 Låg" }[sc.priority] || "—"}</div>
      </div>
    </div>
    <div class="sc-action">
      <label>Rekommenderad åtgärd</label>
      <p>${sc.recommended_action}</p>
    </div>
    <div class="sc-factors">
      ${(sc.key_factors || []).map(f => `<div class="sc-factor">${f}</div>`).join("")}
    </div>
    ${refs}
  </div>`;
}

function renderDetail(c, scorecardLoading = false) {
  const sc = c.scorecard;
  const date = c.created_at ? c.created_at.slice(0, 10) : "—";
  const diff = (c.claim_amount && c.insurer_amount) ? c.claim_amount - c.insurer_amount : null;
  return `
    <div class="detail-header">
      <div>
        <div class="detail-id">${c.id} · Inkommen ${date}</div>
        <div class="detail-name">${c.customer_name || "Okänd kund"}</div>
        <div class="detail-sub">${c.insurance_company || "—"} · ${c.damage_category || "—"} · ${c.insurer_decision || "—"}</div>
      </div>
      <button class="btn-regen" id="regenBtn">↻ Generera om scorecard</button>
    </div>
    ${renderScorecard(sc, scorecardLoading)}
    <div class="cards-grid">
      <div class="info-card">
        <div class="info-card-title">Kundinformation</div>
        <div class="info-row"><label>Namn</label><span>${c.customer_name || "—"}</span></div>
        <div class="info-row"><label>E-post</label><span>${c.customer_email || "—"}</span></div>
        <div class="info-row"><label>Telefon</label><span>${c.customer_phone || "—"}</span></div>
        <div class="info-row"><label>Ort</label><span>${c.property_address || "—"}</span></div>
        <div class="info-row"><label>Fastighetstyp</label><span>${c.property_type || "—"}</span></div>
      </div>
      <div class="info-card">
        <div class="info-card-title">Skadeinformation</div>
        <div class="info-row"><label>Försäkringsbolag</label><span>${c.insurance_company || "—"}</span></div>
        <div class="info-row"><label>Skadetyp</label><span>${c.damage_category || "—"}</span></div>
        <div class="info-row"><label>Skadedatum</label><span>${c.damage_date || "—"}</span></div>
        <div class="info-row"><label>Beslut</label><span>${c.insurer_decision || "—"}</span></div>
        <div class="amounts">
          <div class="amount-box"><label>Yrkat</label><div class="num">${fmt(c.claim_amount)}</div></div>
          <div class="amount-box"><label>Erbjudet</label><div class="num">${fmt(c.insurer_amount)}</div></div>
          ${diff != null ? `<div class="amount-box diff"><label>Diff</label><div class="num">−${fmt(diff)}</div></div>` : ""}
        </div>
      </div>
      <div class="info-card full">
        <div class="info-card-title">Beskrivning</div>
        <p class="description-text">${c.damage_description || "—"}</p>
      </div>
    </div>`;
}

async function loadCases() {
  const data = await apiFetch("/admin/cases?limit=100");
  allCases = data.cases;
  document.getElementById("caseCount").textContent = allCases.length;
  renderList();
}

function filteredCases() {
  if (activeFilter === "all") return allCases;
  if (["high", "medium", "low"].includes(activeFilter)) return allCases.filter(c => c.scorecard?.priority === activeFilter);
  return allCases.filter(c => c.damage_category === activeFilter);
}

function renderList() {
  const list = document.getElementById("caseList");
  const cases = filteredCases();
  list.innerHTML = cases.length
    ? cases.map(renderCaseRow).join("")
    : '<div style="padding:24px;color:var(--muted);text-align:center">Inga ärenden</div>';
  list.querySelectorAll(".case-row").forEach(row => {
    row.addEventListener("click", () => openCase(row.dataset.id));
  });
}

async function openCase(id) {
  activeCaseId = id;
  if (currentView !== "cases") switchView("cases");
  if (allCases.length === 0) await loadCases();
  renderList();

  const right = document.getElementById("right");
  const caseData = allCases.find(c => c.id === id);
  if (!caseData) return;

  if (!caseData.scorecard) {
    right.innerHTML = renderDetail(caseData, true);
    setupRegenBtn(id);
    try {
      const sc = await apiFetch(`/admin/cases/${id}/score`, { method: "POST" });
      caseData.scorecard = sc;
      const idx = allCases.findIndex(c => c.id === id);
      if (idx !== -1) allCases[idx].scorecard = sc;
      renderList();
    } catch {
      const scEl = right.querySelector(".scorecard");
      if (scEl) scEl.innerHTML = '<div class="sc-title">AI Scorecard</div><div class="sc-error">Kunde inte generera scorecard. <a href="#" id="retryLink">Försök igen</a></div>';
      document.getElementById("retryLink")?.addEventListener("click", e => { e.preventDefault(); openCase(id); });
      return;
    }
  }

  right.innerHTML = renderDetail(caseData);
  setupRegenBtn(id);
}

function setupRegenBtn(id) {
  document.getElementById("regenBtn")?.addEventListener("click", async () => {
    const btn = document.getElementById("regenBtn");
    btn.disabled = true;
    btn.textContent = "Genererar...";
    const caseData = allCases.find(c => c.id === id);
    const right = document.getElementById("right");
    right.innerHTML = renderDetail({ ...caseData, scorecard: null }, true);
    setupRegenBtn(id);
    try {
      const sc = await apiFetch(`/admin/cases/${id}/score`, { method: "POST" });
      caseData.scorecard = sc;
      const idx = allCases.findIndex(c => c.id === id);
      if (idx !== -1) allCases[idx].scorecard = sc;
      renderList();
      right.innerHTML = renderDetail(caseData);
      setupRegenBtn(id);
    } catch {
      right.innerHTML = renderDetail(caseData);
      setupRegenBtn(id);
    }
  });
}

function setupFilters() {
  document.querySelectorAll(".pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      activeFilter = pill.dataset.filter;
      renderList();
    });
  });
}

// ── Review queue ─────────────────────────────────────
const PRIO_ORDER = { high: 0, medium: 1, low: 2 };

async function loadReview() {
  const data = await apiFetch("/admin/cases?status=needs_review&limit=100");
  const cases = data.cases.sort((a, b) => {
    const pa = PRIO_ORDER[a.scorecard?.priority] ?? 3;
    const pb = PRIO_ORDER[b.scorecard?.priority] ?? 3;
    if (pa !== pb) return pa - pb;
    return (b.scorecard?.claim_strength ?? 0) - (a.scorecard?.claim_strength ?? 0);
  });
  document.getElementById("reviewCount").textContent = cases.length;
  const list = document.getElementById("reviewList");
  list.innerHTML = cases.length
    ? cases.map(renderCaseRow).join("")
    : '<div style="padding:24px;color:var(--muted);text-align:center">Inget att granska</div>';
  list.querySelectorAll(".case-row").forEach(row => {
    row.addEventListener("click", () => openReviewCase(row.dataset.id));
  });
}

function renderFlagged(refs) {
  if (!refs || !refs.length) return "";
  return `<div class="info-card full">
    <div class="info-card-title">⚠️ Overifierade hänvisningar</div>
    <p class="description-text">${refs.join(", ")} — kunde inte verifieras mot kunskapsbasen. Kontrollera manuellt.</p>
  </div>`;
}

async function openReviewCase(id) {
  const right = document.getElementById("reviewRight");
  right.innerHTML = '<div style="padding:24px;color:var(--muted)">Laddar…</div>';
  const c = await apiFetch(`/admin/cases/${id}`);
  const draft = c.latest_draft;
  const flaggedDraft = draft?.flagged_citations?.length
    ? ` · ⚠️ ${draft.flagged_citations.length} overifierade citat` : "";
  right.innerHTML = `
    <div class="detail-header">
      <div>
        <div class="detail-id">${c.id}</div>
        <div class="detail-name">${c.customer_name || "Okänd kund"}</div>
        <div class="detail-sub">${c.insurance_company || "—"} · ${c.damage_category || "—"}</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn-regen" id="approveBtn">✓ Godkänn</button>
        <button class="btn-regen" id="rejectBtn">✕ Avvisa</button>
      </div>
    </div>
    ${renderScorecard(c.scorecard)}
    ${renderFlagged(c.scorecard?.flagged_references)}
    ${draft ? `
      <div class="info-card full">
        <div class="info-card-title">Utkast (${draft.status})${flaggedDraft}</div>
        <p class="description-text" style="white-space:pre-wrap">${draft.draft_text || "—"}</p>
      </div>` : '<div class="info-card full"><div class="info-card-title">Utkast</div><p class="description-text">Inget utkast genererades — hantera manuellt.</p></div>'}
  `;
  document.getElementById("approveBtn").addEventListener("click", () => reviewAction(id, "approve"));
  document.getElementById("rejectBtn").addEventListener("click", () => reviewAction(id, "reject"));
}

async function reviewAction(id, action) {
  await apiFetch(`/admin/cases/${id}/review`, { method: "POST", body: JSON.stringify({ action }) });
  document.getElementById("reviewRight").innerHTML = '<div class="right-empty"><p>Klart ✓</p></div>';
  loadReview();
}

document.getElementById("signoutBtn")?.addEventListener("click", () => {
  localStorage.removeItem("sc_admin_token");
  location.href = "login.html";
});

// ── Init ─────────────────────────────────────────────
if (!getToken()) {
  location.href = "login.html";
} else {
  setupFilters();
  loadDashboard();
}
