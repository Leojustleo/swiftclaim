/**
 * api.js — Swiftclaim OS ↔ Backend bridge
 *
 * Connects the offline dashboard to the FastAPI backend (localhost:8000).
 * All functions degrade gracefully when backend is unavailable.
 */
(function () {
  const API_BASE = "http://localhost:8000/api";
  let _available = null;

  /**
   * Check if backend is reachable. Caches result for 30s.
   */
  async function isAvailable() {
    if (_available !== null && _available.checkedAt > Date.now() - 30000) {
      return _available.ok;
    }
    try {
      const r = await fetch(`${API_BASE}/status`, { signal: timeoutSignal(3000) });
      _available = { ok: r.ok, checkedAt: Date.now() };
      return r.ok;
    } catch {
      _available = { ok: false, checkedAt: Date.now() };
      return false;
    }
  }

  function timeoutSignal(ms) {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), ms);
    return ctrl.signal;
  }

  async function apiFetch(path, options = {}) {
    if (!(await isAvailable())) return null;
    try {
      const r = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json", ...options.headers },
        signal: timeoutSignal(15000),
        ...options,
      });
      if (!r.ok) return null;
      return r.json();
    } catch {
      return null;
    }
  }

  // ── Schema bridge ──────────────────────────────────────────────

  function osCaseToBackend(item) {
    return {
      id: item.id,
      customer_name: item.customer?.name || "",
      customer_email: item.customer?.email || "",
      customer_phone: item.customer?.phone || "",
      property_address: item.customer?.city || "",
      property_type: item.customer?.propertyType || "",
      insurance_company: item.insuranceCompany || "",
      damage_category: item.category || "",
      damage_description: item.shortDescription || "",
      damage_date: item.incidentDate || null,
      claim_amount: item.claimedAmount || null,
      insurer_decision: item.intake?.currentStage || null,
      insurer_amount: item.offeredAmount || null,
      insurer_reason: item.scorecard?.summary || "",
    };
  }

  // ── Public API ─────────────────────────────────────────────────

  const api = {
    /**
     * Check if backend is reachable.
     */
    isAvailable,

    /**
     * Semantic search over the legal vault (statutes + ARN precedents).
     * Returns { hits: [{score, title, path, text}] } or null.
     */
    async searchLaw(query) {
      return apiFetch("/search/law", {
        method: "POST",
        body: JSON.stringify({ question: query, top_k: 8 }),
      });
    },

    /**
     * Generate a legal draft letter via LLM + RAG.
     * First imports the case to backend if needed.
     */
    async generateDraft(caseItem) {
      await api.importCase(caseItem);
      return apiFetch("/draft", {
        method: "POST",
        body: JSON.stringify({ case_id: caseItem.id }),
      });
    },

    /**
     * Push a local case to the backend database.
     */
    async importCase(item) {
      return apiFetch("/cases", {
        method: "POST",
        body: JSON.stringify(osCaseToBackend(item)),
      });
    },

    /**
     * Fetch all cases from the backend.
     */
    async getCases() {
      return apiFetch("/cases");
    },

    /**
     * Get a single law section reference (e.g. "FAL/4/kap/6/%C2%A7").
     */
    async getLawSection(reference) {
      return apiFetch(`/laws/${encodeURIComponent(reference)}`);
    },

    /**
     * Get all imported ARN decisions.
     */
    async getARN(filters = {}) {
      const params = new URLSearchParams();
      if (filters.category) params.set("category", filters.category);
      if (filters.outcome) params.set("outcome", filters.outcome);
      if (filters.keyword) params.set("keyword", filters.keyword);
      const qs = params.toString();
      return apiFetch(`/arn${qs ? "?" + qs : ""}`);
    },
  };

  window.SwiftclaimAPI = api;
})();
