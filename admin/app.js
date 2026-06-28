const API = "http://localhost:8000/api";

function getToken() {
  return localStorage.getItem("sc_admin_token") || "";
}

function authHeaders() {
  return { "Authorization": `Bearer ${getToken()}`, "Content-Type": "application/json" };
}

async function apiFetch(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders(), ...opts });
  if (r.status === 401) { localStorage.removeItem("sc_admin_token"); location.href = "login.html"; }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

let allCases = [];
let activeFilter = "all";
let activeCaseId = null;

function priorityBadge(sc) {
  if (!sc) return '<span class="badge badge-unknown">—</span>';
  const map = { high: ["badge-high", "Hög prio"], medium: ["badge-medium", "Medel"], low: ["badge-low", "Låg prio"] };
  const [cls, label] = map[sc.priority] || ["badge-unknown", "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function strengthColor(v) {
  if (v >= 70) return "#2ecc71";
  if (v >= 40) return "#f39c12";
  return "#e74c3c";
}

function fmt(n) {
  if (n == null) return "—";
  return new Intl.NumberFormat("sv-SE").format(n) + " kr";
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

document.getElementById("signoutBtn")?.addEventListener("click", () => {
  localStorage.removeItem("sc_admin_token");
  location.href = "login.html";
});

if (!getToken()) { location.href = "login.html"; } else {
  setupFilters();
  loadCases();
}
