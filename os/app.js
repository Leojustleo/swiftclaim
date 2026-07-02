(function () {
  const STORAGE_KEY = "swiftclaim-os-state-v1";
  const DB_NAME = "swiftclaim-os-files";
  const DB_VERSION = 1;
  const FILE_STORE = "files";

  const statuses = [
    "Ny lead",
    "Behöver dokument",
    "Klar för granskning",
    "Accepterad",
    "Inskickad till försäkringsbolag",
    "Väntar på försäkringsbolag",
    "Överklagan/klagomål",
    "Reglerad",
    "Förlorad",
    "Stängd",
    "Avvisad",
  ];

  const pipelineStatuses = [
    "Ny lead",
    "Behöver dokument",
    "Klar för granskning",
    "Accepterad",
    "Inskickad till försäkringsbolag",
    "Väntar på försäkringsbolag",
    "Överklagan/klagomål",
    "Reglerad",
  ];

  const companies = [
    "Folksam",
    "Trygg-Hansa",
    "If",
    "Länsförsäkringar",
    "Dina Försäkringar",
    "Gjensidige",
    "ICA Försäkring",
    "Hedvig",
    "Moderna Försäkringar",
    "Protector",
  ];

  const categories = [
    "Vattenskada",
    "Brand- eller rökskada",
    "Stormskada",
    "Stöld- eller inbrottsskada",
    "Mögel eller fuktskada",
    "Vitvaruskada",
    "Ansvar bostadsrätt/hyresrätt",
    "Avslaget ärende",
    "Underbetalt ärende",
    "Annan egendomsskada",
  ];

  const users = [
    "Leo Sun",
    "Leo Wang",
    "Adrian Rejaeyan Karami",
    "Tom Hao",
    "Adrian Valdani",
    "Frej Anderson",
  ];
  const owners = users;
  const authors = users.concat("AI-utkast");

  const viewTitles = {
    overview: "Översikt",
    cases: "Ärenden",
    pipeline: "Flöde",
    intake: "Intag",
    knowledge: "Kunskap",
  };

  const translations = {
    statuses: {
      "New Lead": "Ny lead",
      "Needs Documents": "Behöver dokument",
      "Ready for Review": "Klar för granskning",
      Accepted: "Accepterad",
      "Submitted to Insurer": "Inskickad till försäkringsbolag",
      "Waiting for Insurer": "Väntar på försäkringsbolag",
      "Appeal/Complaint": "Överklagan/klagomål",
      Settled: "Reglerad",
      Lost: "Förlorad",
      Closed: "Stängd",
      Rejected: "Avvisad",
    },
    stages: {
      "Not submitted": "Ej inskickat",
      "Submitted to insurer": "Inskickat till försäkringsbolag",
      "Decision received": "Beslut mottaget",
      Denied: "Avslaget",
      Underpaid: "Underbetalt",
      "Appeal ongoing": "Överklagan pågår",
    },
    categories: {
      "Water damage": "Vattenskada",
      "Fire or smoke damage": "Brand- eller rökskada",
      "Storm damage": "Stormskada",
      "Theft or burglary": "Stöld- eller inbrottsskada",
      "Stöld eller inbrott": "Stöld- eller inbrottsskada",
      "Mold or moisture": "Mögel eller fuktskada",
      "Appliance damage": "Vitvaruskada",
      "Tenant/co-op responsibility": "Ansvar bostadsrätt/hyresrätt",
      "Denied claim": "Avslaget ärende",
      "Underpaid claim": "Underbetalt ärende",
      "Other property damage": "Annan egendomsskada",
    },
    evidence: {
      Photos: "Foton",
      "Insurance decision": "Försäkringsbeslut",
      "Policy terms": "Försäkringsvillkor",
      Receipts: "Kvitton",
      "Contractor estimate": "Offert från entreprenör",
      "Damage report": "Skaderapport",
    },
    companies: {
      Lansforsakringar: "Länsförsäkringar",
      "Dina Forsakringar": "Dina Försäkringar",
      "ICA Forsakring": "ICA Försäkring",
      "Moderna Forsakringar": "Moderna Försäkringar",
    },
    propertyTypes: {
      Bostadsratt: "Bostadsrätt",
      Hyresratt: "Hyresrätt",
    },
    owners: {
      Unassigned: "Leo Sun",
      "Ej tilldelad": "Leo Sun",
      "Elin Soderberg": "Leo Sun",
      "Elin Söderberg": "Leo Sun",
      "Marcus Holm": "Leo Wang",
      "Lea Nyberg": "Adrian Rejaeyan Karami",
      "Noah Berg": "Tom Hao",
    },
  };

  let state = {
    cases: [],
    selectedCaseId: null,
    view: "overview",
  };

  let dbPromise;
  let lastPipelineDragAt = 0;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    state = loadState();
    state.cases = state.cases.map(localizeCase);
    saveState();

    hydrateSelects();
    bindNavigation();
    bindIntake();
    bindImportExport();
    bindFilters();
    bindBackendSync();
    renderAll();
    syncFromBackend();
  }

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { cases: [], selectedCaseId: null, view: "overview" };
      const parsed = JSON.parse(raw);
      return {
        cases: Array.isArray(parsed.cases) ? parsed.cases : [],
        selectedCaseId: parsed.selectedCaseId || null,
        view: parsed.view || "overview",
      };
    } catch (error) {
      console.warn("Could not load saved state", error);
      return { cases: [], selectedCaseId: null, view: "overview" };
    }
  }

  function localizeCase(caseItem) {
    const item = JSON.parse(JSON.stringify(caseItem));
    item.status = translateValue("statuses", item.status) || item.status || "Ny lead";
    item.responsible = normalizeUser(translateValue("owners", item.responsible) || item.responsible);
    item.priority = translatePriority(item.priority);
    item.category = translateValue("categories", item.category) || item.category || "Annan egendomsskada";
    item.insuranceCompany =
      translateValue("companies", item.insuranceCompany) || item.insuranceCompany || "Okänt bolag";
    item.shortDescription = translateKnownText(item.shortDescription || "");

    item.customer = item.customer || {};
    item.customer.city =
      {
        Gothenburg: "Göteborg",
        Malmo: "Malmö",
      }[item.customer.city] || item.customer.city;
    item.customer.propertyType =
      translateValue("propertyTypes", item.customer.propertyType) || item.customer.propertyType || "Villa";

    item.intake = item.intake || {};
    item.intake.propertyType =
      translateValue("propertyTypes", item.intake.propertyType) || item.intake.propertyType || item.customer.propertyType;
    item.intake.insuranceCompany =
      translateValue("companies", item.intake.insuranceCompany) || item.intake.insuranceCompany || item.insuranceCompany;
    item.intake.damageCategory =
      translateValue("categories", item.intake.damageCategory) || item.intake.damageCategory || item.category;
    item.intake.currentStage =
      translateValue("stages", item.intake.currentStage) || item.intake.currentStage || "Ej inskickat";
    item.intake.description = translateKnownText(item.intake.description || item.shortDescription || "");
    item.intake.evidence = Array.isArray(item.intake.evidence)
      ? item.intake.evidence.map((value) => translateValue("evidence", value) || value)
      : [];

    item.scorecard = analyzeIntake(item.intake);
    item.category = item.scorecard.damageCategory;
    item.insuranceCompany = item.scorecard.insuranceCompany;
    item.documents = Array.isArray(item.documents) ? item.documents : [];

    item.notes = Array.isArray(item.notes) ? item.notes : [];
    item.notes = item.notes.map((note) => ({
      ...note,
      author: normalizeAuthor(translateValue("owners", note.author) || note.author),
      type: translateNoteType(note.type),
      body: note.author === "AI Draft" || note.author === "AI-utkast" ? item.scorecard.summary : translateKnownText(note.body || ""),
    }));

    item.tasks = Array.isArray(item.tasks) ? item.tasks : [];
    item.tasks = item.tasks.map((task) => ({
      ...task,
      owner: normalizeUser(translateValue("owners", task.owner) || task.owner),
      title: translateKnownText(task.title || ""),
    }));

    item.timeline = Array.isArray(item.timeline) ? item.timeline : [];
    item.timeline = item.timeline.map((event) => ({
      ...event,
      title: translateTimelineTitle(event.title),
      body: translateKnownText(event.body || ""),
    }));

    item.outcome = item.outcome || {};
    item.outcome.result = translateOutcome(item.outcome.result);
    item.outcome.lessons = translateKnownText(item.outcome.lessons || "");
    return item;
  }

  function translateValue(group, value) {
    return translations[group]?.[value];
  }

  function normalizeUser(value) {
    return users.includes(value) ? value : users[0];
  }

  function normalizeAuthor(value) {
    if (value === "AI Draft" || value === "AI-utkast") return "AI-utkast";
    return users.includes(value) ? value : users[0];
  }

  function translatePriority(value) {
    return (
      {
        Low: "Låg",
        Normal: "Normal",
        High: "Hög",
        Urgent: "Akut",
      }[value] || value || "Normal"
    );
  }

  function translateOutcome(value) {
    return (
      {
        Pending: "Pågående",
        Recovered: "Ersättning återvunnen",
        "Rejected by Swiftclaim": "Avvisat av Swiftclaim",
        Lost: "Förlorat",
        Withdrawn: "Tillbakadraget",
      }[value] || value || "Pågående"
    );
  }

  function translateNoteType(value) {
    return (
      {
        "Internal note": "Intern anteckning",
        "Customer call": "Kundsamtal",
        "Insurer call": "Samtal med försäkringsbolag",
        "Legal review": "Juridisk granskning",
        "AI note": "AI-anteckning",
      }[value] || value || "Intern anteckning"
    );
  }

  function translateTimelineTitle(value) {
    return (
      {
        "Case created": "Ärende skapat",
        "Status changed": "Status ändrad",
        "Owner changed": "Ansvarig ändrad",
        "Priority changed": "Prioritet ändrad",
        "Outcome updated": "Utfall uppdaterat",
        "Scorecard regenerated": "Bedömningskort regenererat",
        "Scorecard regenererat": "Bedömningskort regenererat",
        "Files added": "Filer tillagda",
        "File removed": "Fil borttagen",
        "Note added": "Anteckning tillagd",
        "Task added": "Uppgift tillagd",
        "Task completed": "Uppgift klar",
        "Task reopened": "Uppgift öppnad igen",
      }[value] || value || "Händelse"
    );
  }

  function translateKnownText(value) {
    if (!value) return "";
    const known = {
      "Kitchen water leak from dishwasher connection. Insurer accepts part of the flooring but rejects cabinet work and drying cost. Customer has photos, contractor estimate, and insurer decision.":
        "Vattenläcka i köket från diskmaskinskoppling. Försäkringsbolaget godkänner delar av golvet men nekar ersättning för skåp, uttorkning och följdkostnader. Kunden har foton, offert från entreprenör och försäkringsbeslut.",
      "Moisture and mold discovered behind bathroom wall. Insurer says gradual damage and poor maintenance. Customer believes hidden pipe failure caused the damage.":
        "Fukt och mögel upptäcktes bakom badrumsvägg. Försäkringsbolaget hänvisar till gradvis skada och bristande underhåll. Kunden menar att ett dolt rörfel orsakade skadan.",
      "Storm damaged roof tiles and led to water ingress in ceiling. Claim submitted with photos, but insurer has not responded yet.":
        "Storm skadade takpannor och ledde till vatteninträngning i innertaket. Ärendet är inskickat med foton, men försäkringsbolaget har inte svarat ännu.",
      "Human review of policy terms and facts": "Mänsklig granskning av villkor och sakförhållanden",
      "Mock intake analyzed and routed to Ready for Review.": "Exempelintag analyserades och skickades till Klar för granskning.",
      "Mock intake analyzed and routed to Needs Documents.": "Exempelintag analyserades och skickades till Behöver dokument.",
      "Mock intake analyzed and routed to Waiting for Insurer.": "Exempelintag analyserades och skickades till Väntar på försäkringsbolag.",
    };
    if (known[value]) return known[value];
    return value
      .replace(/^Request photos$/i, "Begär foton")
      .replace(/^Request insurance decision$/i, "Begär försäkringsbeslut")
      .replace(/^Request policy terms$/i, "Begär försäkringsvillkor")
      .replace(/^Request contractor estimate$/i, "Begär offert från entreprenör")
      .replace(/^Request damage report$/i, "Begär skaderapport")
      .replace(/Mock intake analyzed and routed to (.+)\./, (_match, status) => {
        return `Exempelintag analyserades och skickades till ${translateValue("statuses", status) || status}.`;
      });
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function hydrateSelects() {
    fillSelect(document.getElementById("intakeCompany"), companies);
    fillSelect(document.getElementById("intakeCategory"), categories);

    fillSelect(document.getElementById("statusFilter"), ["Alla statusar"].concat(statuses));
    fillSelect(document.getElementById("ownerFilter"), ["Alla ansvariga"].concat(owners));
    fillSelect(document.getElementById("companyFilter"), ["Alla bolag"].concat(companies));
    fillSelect(document.getElementById("categoryFilter"), ["Alla kategorier"].concat(categories));
  }

  function fillSelect(select, values, selected) {
    if (!select) return;
    select.innerHTML = values
      .map((value) => `<option${value === selected ? " selected" : ""}>${escapeHtml(value)}</option>`)
      .join("");
  }

  function bindNavigation() {
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.view));
    });
    document.querySelectorAll("[data-view-link]").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.viewLink));
    });
    document.getElementById("newCaseTopBtn").addEventListener("click", () => switchView("intake"));
    document.getElementById("globalSearch").addEventListener("input", renderAll);
  }

  function bindFilters() {
    ["statusFilter", "ownerFilter", "companyFilter", "categoryFilter"].forEach((id) => {
      document.getElementById(id).addEventListener("change", renderAll);
    });
  }

  function switchView(view) {
    state.view = view;
    saveState();
    renderAll();
  }

  function bindIntake() {
    const form = document.getElementById("intakeForm");
    document.getElementById("fillSampleBtn").addEventListener("click", () => fillSampleIntake(form));
    document.getElementById("previewScoreBtn").addEventListener("click", () => {
      const payload = getIntakePayload(form);
      const preview = document.getElementById("scorePreview");
      preview.classList.remove("hidden");
      preview.innerHTML = `
        <div class="panel-heading">
          <div>
            <p class="eyebrow">AI-utkast</p>
            <h2>Förhandsvisning av bedömningskort</h2>
          </div>
        </div>
        ${scorecardHtml(analyzeIntake(payload))}
      `;
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const payload = getIntakePayload(form);
      const scorecard = analyzeIntake(payload);
      const newCase = createCaseFromPayload(payload, scorecard);
      state.cases.unshift(newCase);
      state.selectedCaseId = newCase.id;
      saveState();
      form.reset();
      document.getElementById("scorePreview").classList.add("hidden");
      switchView("cases");
    });
  }

  function bindImportExport() {
    document.getElementById("exportJsonBtn").addEventListener("click", () => {
      downloadText(
        `swiftclaim-os-export-${new Date().toISOString().slice(0, 10)}.json`,
        JSON.stringify(state, null, 2),
        "application/json",
      );
    });

    document.getElementById("importJsonInput").addEventListener("change", async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const text = await file.text();
      try {
        const imported = JSON.parse(text);
        if (!Array.isArray(imported.cases)) throw new Error("Saknar ärendelista");
        state = {
          cases: imported.cases.map(localizeCase),
          selectedCaseId: imported.selectedCaseId || imported.cases[0]?.id || null,
          view: "cases",
        };
        saveState();
        renderAll();
      } catch (error) {
        alert("Kunde inte importera filen. Den verkar inte vara en Swiftclaim OS-export.");
      } finally {
        event.target.value = "";
      }
    });
  }

  function getIntakePayload(form) {
    const data = new FormData(form);
    return {
      customerName: String(data.get("customerName") || "").trim(),
      email: String(data.get("email") || "").trim(),
      phone: String(data.get("phone") || "").trim(),
      city: String(data.get("city") || "").trim(),
      propertyType: String(data.get("propertyType") || "Villa"),
      insuranceCompany: String(data.get("insuranceCompany") || companies[0]),
      damageCategory: String(data.get("damageCategory") || categories[0]),
      incidentDate: String(data.get("incidentDate") || ""),
      decisionDate: String(data.get("decisionDate") || ""),
      claimedAmount: Number(data.get("claimedAmount")) || 0,
      offeredAmount: Number(data.get("offeredAmount")) || 0,
      currentStage: String(data.get("currentStage") || "Ej inskickat"),
      description: String(data.get("description") || "").trim(),
      evidence: data.getAll("evidence").map(String),
    };
  }

  function fillSampleIntake(form) {
    form.customerName.value = "Sara Nilsson";
    form.email.value = "sara.nilsson@example.com";
    form.phone.value = "+46 72 444 11 22";
    form.city.value = "Uppsala";
    form.propertyType.value = "Villa";
    form.insuranceCompany.value = "Trygg-Hansa";
    form.damageCategory.value = "Brand- eller rökskada";
    form.incidentDate.value = "2026-03-15";
    form.claimedAmount.value = "275000";
    form.offeredAmount.value = "98000";
    form.decisionDate.value = "2026-04-05";
    form.currentStage.value = "Underbetalt";
    form.description.value =
      "Köksbrand orsakade rökskador på hela bottenvåningen. Försäkringsbolaget ersätter ommålning men nekar sanering, tillfälligt boende och flera skadade vitvaror.";
    form.querySelectorAll('input[name="evidence"]').forEach((checkbox) => {
      checkbox.checked = ["Foton", "Försäkringsbeslut", "Kvitton", "Skaderapport"].includes(
        checkbox.value,
      );
    });
  }

  function createCaseFromPayload(payload, scorecard) {
    const id = nextCaseId();
    const now = new Date().toISOString();
    const status = inferInitialStatus(payload, scorecard);
    return {
      id,
      createdAt: now,
      updatedAt: now,
      customer: {
        name: payload.customerName,
        email: payload.email,
        phone: payload.phone,
        city: payload.city,
        propertyType: payload.propertyType,
      },
      insuranceCompany: payload.insuranceCompany,
      category: payload.damageCategory,
      shortDescription: payload.description,
      incidentDate: payload.incidentDate,
      decisionDate: payload.decisionDate,
      claimedAmount: payload.claimedAmount,
      offeredAmount: payload.offeredAmount,
      status,
      responsible: users[0],
      priority: scorecard.deadlineRisk === "hög" ? "Hög" : "Normal",
      scorecard,
      intake: payload,
      documents: [],
      notes: [
        {
          id: makeId("note"),
          author: "AI-utkast",
          body: scorecard.summary,
          createdAt: now,
        },
      ],
      tasks: defaultTasks(scorecard),
      timeline: [
        {
          id: makeId("event"),
          at: now,
          title: "Ärende skapat",
          body: `Intag analyserades och skickades till ${status}.`,
        },
      ],
      outcome: {
        result: "Pågående",
        recoveredAmount: 0,
        feeAmount: 0,
        lessons: "",
      },
    };
  }

  function bindBackendSync() {
    document.getElementById("syncBackendBtn").addEventListener("click", async () => {
      const added = await syncFromBackend();
      alert(added === null ? "Backend nås inte på localhost:8000." : `${added} nya ärenden hämtade.`);
    });
  }

  async function syncFromBackend() {
    if (!window.SwiftclaimAPI) return null;
    const backendCases = await window.SwiftclaimAPI.getCases();
    if (!backendCases) return null;
    let added = 0;
    backendCases.forEach((remote) => {
      if (state.cases.some((item) => item.id === remote.id)) return;
      const payload = backendCaseToPayload(remote);
      const newCase = createCaseFromPayload(payload, analyzeIntake(payload));
      newCase.id = remote.id;
      newCase.createdAt = remote.created_at || newCase.createdAt;
      newCase.timeline[0].body = "Ärende inskickat via Swiftclaim.se.";
      if (remote.ai_analysis) {
        newCase.notes.unshift({
          id: makeId("note"),
          author: "AI-analys",
          body: formatAiAnalysis(remote.ai_analysis),
          createdAt: newCase.createdAt,
        });
      }
      state.cases.unshift(newCase);
      added += 1;
    });
    if (added > 0) {
      saveState();
      renderAll();
    }
    return added;
  }

  function formatAiAnalysis(a) {
    const parts = [`Styrka: ${a.strength || "okänd"}.`];
    if (a.summary) parts.push(a.summary);
    if (Array.isArray(a.key_arguments) && a.key_arguments.length) {
      parts.push(`Nyckelargument: ${a.key_arguments.join(" • ")}`);
    }
    if (Array.isArray(a.missing_info) && a.missing_info.length) {
      parts.push(`Saknas: ${a.missing_info.join(" • ")}`);
    }
    if (Array.isArray(a.matched_laws) && a.matched_laws.length) {
      parts.push(`Lagrum: ${a.matched_laws.map((l) => l.ref).join(", ")}`);
    }
    if (Array.isArray(a.matched_precedents) && a.matched_precedents.length) {
      parts.push(`ARN-praxis: ${a.matched_precedents.map((p) => p.id).join(", ")}`);
    }
    return parts.join("\n");
  }

  function backendCaseToPayload(remote) {
    return {
      customerName: remote.customer_name || "",
      email: remote.customer_email || "",
      phone: remote.customer_phone || "",
      city: remote.property_address || "",
      propertyType: remote.property_type || "Villa",
      insuranceCompany: remote.insurance_company || companies[0],
      damageCategory: remote.damage_category || "Annan egendomsskada",
      incidentDate: remote.damage_date || "",
      decisionDate: "",
      claimedAmount: Number(remote.claim_amount) || 0,
      offeredAmount: Number(remote.insurer_amount) || 0,
      currentStage: remote.insurer_decision || "Ej inskickat",
      description: remote.damage_description || "",
      evidence: Array.isArray(remote.tags) ? remote.tags : [],
    };
  }

  function defaultTasks(scorecard) {
    const tasks = scorecard.missingDocuments.slice(0, 3).map((documentName) => ({
      id: makeId("task"),
      title: `Begär ${documentName.toLowerCase()}`,
      dueDate: offsetDate(3).slice(0, 10),
      owner: users[0],
      done: false,
    }));
    tasks.push({
      id: makeId("task"),
      title: "Mänsklig granskning av villkor och sakförhållanden",
      dueDate: offsetDate(5).slice(0, 10),
      owner: users[0],
      done: false,
    });
    return tasks;
  }

  function inferInitialStatus(payload, scorecard) {
    if (scorecard.missingDocuments.length >= 3) return "Behöver dokument";
    if (["Avslaget", "Underbetalt", "Beslut mottaget"].includes(payload.currentStage)) {
      return "Klar för granskning";
    }
    if (payload.currentStage === "Inskickat till försäkringsbolag") return "Väntar på försäkringsbolag";
    if (payload.currentStage === "Överklagan pågår") return "Överklagan/klagomål";
    return "Ny lead";
  }

  function analyzeIntake(payload) {
    const category = payload.damageCategory || inferCategory(payload.description);
    const description = payload.description || "";
    const evidence = Array.isArray(payload.evidence) ? payload.evidence : [];
    const stage = payload.currentStage || "Not submitted";
    const amount = Number(payload.claimedAmount) || 0;
    const offered = Number(payload.offeredAmount) || 0;
    const range = estimateTicketRange(category, amount, offered);
    const missingDocuments = getMissingDocuments(evidence, stage);
    const evidenceQuality = clamp(1 + evidence.length + (evidence.includes("Försäkringsbeslut") ? 1 : 0), 1, 5);
    const deadlineRisk = getDeadlineRisk(payload.decisionDate, stage);
    const difficulty = estimateDifficulty({
      category,
      stage,
      evidenceQuality,
      deadlineRisk,
      description,
      propertyType: payload.propertyType,
      missingDocuments,
    });
    const riskFlags = getRiskFlags({
      category,
      stage,
      evidenceQuality,
      deadlineRisk,
      description,
      propertyType: payload.propertyType,
      incidentDate: payload.incidentDate,
    });
    const suggestedNextAction = getSuggestedNextAction({
      missingDocuments,
      deadlineRisk,
      evidenceQuality,
      stage,
      category,
    });

    return {
      summary: buildSummary(payload, category, range, difficulty),
      damageCategory: category,
      insuranceCompany: payload.insuranceCompany || "Unknown",
      estimatedTicketSize: range,
      ticketSizeBand: range.high >= 200000 ? "Hög" : range.high >= 75000 ? "Medel" : "Låg",
      difficultyRating: difficulty,
      evidenceQuality,
      deadlineRisk,
      suggestedNextAction,
      missingDocuments,
      riskFlags,
      aiConfidence: evidenceQuality >= 4 ? "Medelhög" : "Medel",
      reviewStatus: "AI-utkast, mänsklig granskning krävs",
      generatedAt: new Date().toISOString(),
    };
  }

  function inferCategory(description) {
    const text = (description || "").toLowerCase();
    if (text.includes("vatten") || text.includes("läcka") || text.includes("rör")) return "Vattenskada";
    if (text.includes("brand") || text.includes("rök")) return "Brand- eller rökskada";
    if (text.includes("storm") || text.includes("tak")) return "Stormskada";
    if (text.includes("stöld") || text.includes("inbrott")) return "Stöld- eller inbrottsskada";
    if (text.includes("mögel") || text.includes("fukt")) return "Mögel eller fuktskada";
    return "Annan egendomsskada";
  }

  function estimateTicketRange(category, claimedAmount, offeredAmount) {
    const defaults = {
      Vattenskada: [80000, 240000],
      "Brand- eller rökskada": [120000, 520000],
      Stormskada: [40000, 180000],
      "Stöld- eller inbrottsskada": [15000, 90000],
      "Mögel eller fuktskada": [60000, 260000],
      Vitvaruskada: [8000, 55000],
      "Ansvar bostadsrätt/hyresrätt": [25000, 140000],
      "Avslaget ärende": [50000, 220000],
      "Underbetalt ärende": [30000, 180000],
      "Annan egendomsskada": [20000, 140000],
    };
    if (claimedAmount > 0) {
      const upside = offeredAmount > 0 ? Math.max(claimedAmount - offeredAmount, 5000) : claimedAmount;
      return {
        low: Math.round(Math.max(upside * 0.35, 5000)),
        high: Math.round(Math.max(upside, 10000)),
      };
    }
    const [low, high] = defaults[category] || defaults["Annan egendomsskada"];
    return { low, high };
  }

  function getMissingDocuments(evidence, stage) {
    const missing = [];
    if (!evidence.includes("Foton")) missing.push("Foton");
    if (stage !== "Ej inskickat" && !evidence.includes("Försäkringsbeslut")) {
      missing.push("Försäkringsbeslut");
    }
    if (!evidence.includes("Försäkringsvillkor")) missing.push("Försäkringsvillkor");
    if (!evidence.includes("Offert från entreprenör")) missing.push("Offert från entreprenör");
    if (!evidence.includes("Skaderapport")) missing.push("Skaderapport");
    return missing;
  }

  function getDeadlineRisk(decisionDate, stage) {
    if (!decisionDate || ["Ej inskickat", "Inskickat till försäkringsbolag"].includes(stage)) return "låg";
    const days = daysSince(decisionDate);
    if (days >= 150) return "hög";
    if (days >= 105) return "medel";
    return "låg";
  }

  function estimateDifficulty(context) {
    let score = 2;
    if (["Avslaget", "Underbetalt", "Överklagan pågår"].includes(context.stage)) score += 1;
    if (["Mögel eller fuktskada", "Ansvar bostadsrätt/hyresrätt"].includes(context.category)) score += 1;
    if (context.deadlineRisk === "hög") score += 1;
    if (context.evidenceQuality <= 2) score += 1;
    if (context.missingDocuments.length >= 4) score += 1;
    if (/underhåll|gradvis|slitage|tidigare|dolt|maintenance|gradual|wear|pre-existing|hidden/i.test(context.description)) score += 1;
    return clamp(score, 1, 5);
  }

  function getRiskFlags(context) {
    const flags = [];
    if (context.deadlineRisk === "hög") flags.push("Tidsfrist för omprövning eller klagomål kan vara nära");
    if (context.evidenceQuality <= 2) flags.push("Svag bevisning i nuläget");
    if (["Mögel eller fuktskada", "Vattenskada"].includes(context.category)) {
      flags.push("Orsakssamband och underhållsundantag behöver granskas");
    }
    if (["Bostadsrätt", "Hyresrätt"].includes(context.propertyType)) {
      flags.push("Möjligt delat ansvar mellan boende, förening, hyresvärd och försäkringsbolag");
    }
    if (context.incidentDate && daysSince(context.incidentDate) > 90 && context.stage === "Ej inskickat") {
      flags.push("Sen skadeanmälan");
    }
    if (/oklart|osäker|vet inte|kanske|möjligen|unclear|not sure|unknown|maybe|possibly/i.test(context.description)) {
      flags.push("Fakta är osäkra och behöver kundförtydligande");
    }
    if (!flags.length) flags.push("Inga större initiala riskflaggor");
    return flags;
  }

  function getSuggestedNextAction(context) {
    if (context.deadlineRisk === "hög") {
      return "Eskalera för mänsklig granskning och bekräfta omprövnings- eller klagofrist direkt.";
    }
    if (context.missingDocuments.includes("Försäkringsbeslut")) {
      return "Begär försäkringsbolagets beslutsbrev och eventuell motivering till ersättningen eller avslaget.";
    }
    if (context.missingDocuments.includes("Försäkringsvillkor")) {
      return "Samla in försäkringsvillkor och kartlägg relevanta undantag innan argument utformas.";
    }
    if (context.evidenceQuality <= 2) {
      return "Samla in kärnbevisning innan Swiftclaim beslutar om ärendet ska accepteras.";
    }
    if (context.category === "Mögel eller fuktskada") {
      return "Granska skadeorsakens tidslinje och underhållsundantag, och förbered förtydligande frågor.";
    }
    return "Mänsklig granskare bör verifiera fakta, fatta acceptbeslut och förbereda argumentkarta mot försäkringsbolaget.";
  }

  function buildSummary(payload, category, range, difficulty) {
    const customer = payload.customerName || "Kunden";
    const insurer = payload.insuranceCompany || "försäkringsbolaget";
    const stage = payload.currentStage || "Ej inskickat";
    const short = (payload.description || "").trim();
    const firstSentence = short ? short.split(/[.!?]/)[0] : "Egendomsskadeärende inskickat för bedömning";
    return `${customer} anmäler ${category.toLowerCase()} kopplad till ${insurer}. Nuvarande läge är ${stage.toLowerCase()}. Bedömt möjligt ersättningsvärde är ${formatMoney(range.low)}-${formatMoney(range.high)} med svårighet ${difficulty}/5. ${firstSentence}.`;
  }

  function renderAll() {
    renderNavigation();
    renderOverview();
    renderCases();
    renderPipeline();
    renderKnowledge();
  }

  function renderNavigation() {
    document.querySelectorAll(".nav-item").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === state.view);
    });
    document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
    document.getElementById(`${state.view}View`).classList.add("active");
    document.getElementById("viewTitle").textContent = viewTitles[state.view] || "Översikt";
  }

  function filteredCases() {
    const q = document.getElementById("globalSearch").value.trim().toLowerCase();
    const status = document.getElementById("statusFilter")?.value || "Alla statusar";
    const owner = document.getElementById("ownerFilter")?.value || "Alla ansvariga";
    const company = document.getElementById("companyFilter")?.value || "Alla bolag";
    const category = document.getElementById("categoryFilter")?.value || "Alla kategorier";

    return state.cases.filter((item) => {
      const haystack = [
        item.id,
        item.customer.name,
        item.customer.email,
        item.customer.city,
        item.insuranceCompany,
        item.category,
        item.shortDescription,
        item.status,
        item.responsible,
        item.scorecard.summary,
        item.notes.map((note) => note.body).join(" "),
      ]
        .join(" ")
        .toLowerCase();

      return (
        (!q || haystack.includes(q)) &&
        (status === "Alla statusar" || item.status === status) &&
        (owner === "Alla ansvariga" || item.responsible === owner) &&
        (company === "Alla bolag" || item.insuranceCompany === company) &&
        (category === "Alla kategorier" || item.category === category)
      );
    });
  }

  function renderOverview() {
    const active = state.cases.filter((item) => !["Stängd", "Avvisad", "Förlorad"].includes(item.status));
    const highDeadline = state.cases.filter((item) => item.scorecard.deadlineRisk === "hög");
    const totalPipeline = active.reduce((sum, item) => sum + item.scorecard.estimatedTicketSize.high, 0);
    const docsMissing = state.cases.filter((item) => item.scorecard.missingDocuments.length > 2);

    const metrics = [
      ["Öppna ärenden", active.length, `${state.cases.length} totalt`],
      ["Hög tidsrisk", highDeadline.length, "Behöver kollas samma dag"],
      ["Pipelinevärde", formatMoney(totalPipeline), "Högsta uppskattning"],
      ["Behöver dokument", docsMissing.length, "Luckor i bevisningen"],
    ];

    document.getElementById("metricGrid").innerHTML = metrics
      .map(
        ([label, value, helper]) => `
          <div class="metric">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(String(value))}</strong>
            <small>${escapeHtml(helper)}</small>
          </div>
        `,
      )
      .join("");

    const rows = active
      .slice()
      .sort((a, b) => b.scorecard.difficultyRating - a.scorecard.difficultyRating)
      .slice(0, 6);
    document.getElementById("overviewCaseRows").innerHTML = rows.length
      ? rows.map(caseRowCompact).join("")
      : `<tr><td colspan="5" class="empty">Inga aktiva ärenden.</td></tr>`;

    document.getElementById("overviewActions").innerHTML = active
      .slice()
      .sort(actionSort)
      .slice(0, 7)
      .map(
        (item) => `
        <button class="action-item" type="button" data-case-open="${escapeHtml(item.id)}">
          <small>${escapeHtml(item.id)} - ${escapeHtml(item.customer.name)}</small>
          <p>${escapeHtml(item.scorecard.suggestedNextAction)}</p>
        </button>
      `,
      )
      .join("");

    bindCaseOpeners();
  }

  function actionSort(a, b) {
    const riskValue = { hög: 3, medel: 2, låg: 1 };
    return (
      riskValue[b.scorecard.deadlineRisk] - riskValue[a.scorecard.deadlineRisk] ||
      b.scorecard.difficultyRating - a.scorecard.difficultyRating
    );
  }

  function caseRowCompact(item) {
    return `
      <tr class="case-row" data-case-open="${escapeHtml(item.id)}">
        <td><span class="strong-link">${escapeHtml(item.id)}</span></td>
        <td>${escapeHtml(item.customer.name)}</td>
        <td><span class="badge status">${escapeHtml(item.status)}</span></td>
        <td>${escapeHtml(item.responsible)}</td>
        <td><span class="badge deadline-${riskClass(item.scorecard.deadlineRisk)}">${escapeHtml(item.scorecard.deadlineRisk)}</span></td>
      </tr>
    `;
  }

  function renderCases() {
    const rows = filteredCases();
    document.getElementById("caseRows").innerHTML = rows.length
      ? rows.map(caseRowFull).join("")
      : `<tr><td colspan="8" class="empty">Inga ärenden matchar filtren.</td></tr>`;

    const selected = getSelectedCase();
    const detail = document.getElementById("caseDetail");
    if (!selected) {
      detail.classList.add("hidden");
      detail.innerHTML = "";
    } else {
      detail.classList.remove("hidden");
      detail.innerHTML = caseDetailHtml(selected);
      bindCaseDetail(selected.id);
    }

    bindCaseOpeners();
  }

  function caseRowFull(item) {
    return `
      <tr class="case-row" data-case-open="${escapeHtml(item.id)}">
        <td><span class="strong-link">${escapeHtml(item.id)}</span><br><span class="muted">${dateShort(item.createdAt)}</span></td>
        <td>${escapeHtml(item.customer.name)}<br><span class="muted">${escapeHtml(item.customer.city || "Ingen stad")}</span></td>
        <td>${escapeHtml(item.category)}</td>
        <td>${escapeHtml(item.insuranceCompany)}</td>
        <td>${escapeHtml(formatMoney(item.scorecard.estimatedTicketSize.high))}</td>
        <td>${escapeHtml(String(item.scorecard.difficultyRating))}/5</td>
        <td><span class="badge status">${escapeHtml(item.status)}</span></td>
        <td>${escapeHtml(item.responsible)}</td>
      </tr>
    `;
  }

  function caseDetailHtml(item) {
    return `
      <div class="detail-header">
        <div class="detail-title">
          <p class="eyebrow">${escapeHtml(item.id)} - ${escapeHtml(item.insuranceCompany)}</p>
          <h2>${escapeHtml(item.customer.name)}</h2>
          <p>${escapeHtml(item.category)} - ${escapeHtml(item.customer.propertyType)} - ${escapeHtml(item.customer.city || "Ingen stad")}</p>
        </div>
        <div class="detail-actions">
          <button class="secondary" id="regenerateScoreBtn" type="button">Regenerera bedömningskort</button>
          <button class="secondary" id="downloadCaseMdBtn" type="button">Ladda ned markdown</button>
          <button class="danger" id="deleteCaseBtn" type="button">Ta bort ärende</button>
        </div>
      </div>

      <div class="detail-grid">
        <div>
          <section class="subpanel">
            <h3>Ärendestyrning</h3>
            <div class="field-row">
              <label>Status<select id="detailStatus">${optionsHtml(statuses, item.status)}</select></label>
              <label>Ansvarig<select id="detailOwner">${optionsHtml(owners, item.responsible)}</select></label>
              <label>Prioritet<select id="detailPriority">${optionsHtml(["Låg", "Normal", "Hög", "Akut"], item.priority)}</select></label>
              <label>Utfall<select id="detailOutcome">${optionsHtml(["Pågående", "Ersättning återvunnen", "Avvisat av Swiftclaim", "Förlorat", "Tillbakadraget"], item.outcome.result)}</select></label>
            </div>
            <label class="stacked">
              Kort beskrivning
              <textarea id="detailDescription" rows="4">${escapeHtml(item.shortDescription)}</textarea>
            </label>
          </section>

          <section class="subpanel">
            <h3>AI-bedömningskort</h3>
            ${scorecardHtml(item.scorecard)}
          </section>

          <section class="subpanel legal-research">
            <div class="legal-header">
              <h3>Rättskunskap</h3>
              <span class="badge muted" id="backendStatus" data-status="checking">Kontrollerar anslutning...</span>
            </div>
            <div class="legal-actions">
              <button class="primary" id="searchLawBtn" type="button">Sök relevant lagstiftning</button>
              <button class="secondary" id="generateDraftBtn" type="button">Generera juridiskt utkast</button>
              <button class="ghost" id="importCaseBtn" type="button">Synka till backend</button>
            </div>
            <div class="ask-box">
              <input id="askInput" type="search" placeholder="Fråga juridiken om ärendet, t.ex. 'Kan åldersavdraget ifrågasättas?'" />
              <button class="secondary" id="askBtn" type="button">Fråga</button>
            </div>
            <div id="legalResults" class="legal-results"></div>
          </section>

          <section class="subpanel">
            <h3>Tidslinje</h3>
            <div class="timeline-list">
              ${item.timeline
                .slice()
                .reverse()
                .map(
                  (event) => `
                    <div class="timeline-item">
                      <small>${dateTime(event.at)}</small>
                      <p><strong>${escapeHtml(event.title)}</strong> ${escapeHtml(event.body)}</p>
                    </div>
                  `,
                )
                .join("")}
            </div>
          </section>
        </div>

        <div>
          <section class="subpanel">
            <h3>Filer</h3>
            <label>
              Lägg till ärendefiler
              <input id="fileUpload" type="file" multiple />
            </label>
            <div class="file-list" id="fileList">${filesHtml(item)}</div>
          </section>

          <section class="subpanel">
            <h3>Anteckningar</h3>
            <div class="field-row">
              <label>Författare<select id="noteAuthor">${optionsHtml(authors, authors[0])}</select></label>
              <label>Typ<select id="noteType">${optionsHtml(["Intern anteckning", "Kundsamtal", "Samtal med försäkringsbolag", "Juridisk granskning", "AI-anteckning"], "Intern anteckning")}</select></label>
            </div>
            <label>
              Ny anteckning
              <textarea id="noteBody" rows="4" placeholder="Skriv nästa användbara faktum, beslut eller hinder."></textarea>
            </label>
            <button class="primary full" id="addNoteBtn" type="button">Lägg till anteckning</button>
            <div class="note-list">
              ${item.notes
                .slice()
                .reverse()
                .map(
                  (note) => `
                    <div class="note">
                      <small>${escapeHtml(note.author)} - ${dateTime(note.createdAt)}</small>
                      <p>${escapeHtml(note.body)}</p>
                    </div>
                  `,
                )
                .join("")}
            </div>
          </section>

          <section class="subpanel">
            <h3>Uppgifter</h3>
            <div class="field-row">
              <label>Uppgift<input id="taskTitle" placeholder="Förbered argumentkarta mot försäkringsbolaget" /></label>
              <label>Förfallodatum<input id="taskDue" type="date" /></label>
            </div>
            <button class="secondary full" id="addTaskBtn" type="button">Lägg till uppgift</button>
            <div class="task-list">
              ${item.tasks.map(taskHtml).join("")}
            </div>
          </section>
        </div>
      </div>
    `;
  }

  function scorecardHtml(scorecard) {
    return `
      <div class="scorecard">
        <div class="score-item wide">
          <span>Sammanfattning</span>
          <p>${escapeHtml(scorecard.summary)}</p>
        </div>
        <div class="score-item">
          <span>Ärendevärde</span>
          <strong>${escapeHtml(formatMoney(scorecard.estimatedTicketSize.low))}-${escapeHtml(formatMoney(scorecard.estimatedTicketSize.high))}</strong>
          <p class="muted">${escapeHtml(scorecard.ticketSizeBand)}</p>
        </div>
        <div class="score-item">
          <span>Svårighet</span>
          <strong>${escapeHtml(String(scorecard.difficultyRating))}/5</strong>
          <p class="muted">${escapeHtml(scorecard.reviewStatus)}</p>
        </div>
        <div class="score-item">
          <span>Bevisning</span>
          <strong>${escapeHtml(String(scorecard.evidenceQuality))}/5</strong>
          <p class="muted">Säkerhet: ${escapeHtml(scorecard.aiConfidence)}</p>
        </div>
        <div class="score-item">
          <span>Tidsrisk</span>
          <strong><span class="badge deadline-${riskClass(scorecard.deadlineRisk)}">${escapeHtml(scorecard.deadlineRisk)}</span></strong>
        </div>
        <div class="score-item wide">
          <span>Föreslaget nästa steg</span>
          <p>${escapeHtml(scorecard.suggestedNextAction)}</p>
        </div>
        <div class="score-item wide">
          <span>Saknade dokument</span>
          ${listHtml(scorecard.missingDocuments)}
        </div>
        <div class="score-item wide">
          <span>Riskflaggor</span>
          ${listHtml(scorecard.riskFlags)}
        </div>
      </div>
    `;
  }

  function listHtml(items) {
    if (!items || !items.length) return `<p class="muted">Inga</p>`;
    return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }

  function optionsHtml(values, selected) {
    return values
      .map((value) => `<option${value === selected ? " selected" : ""}>${escapeHtml(value)}</option>`)
      .join("");
  }

  function filesHtml(item) {
    if (!item.documents.length) return `<div class="empty">Inga filer tillagda ännu.</div>`;
    return item.documents
      .map(
        (file) => `
          <div class="file-row">
            <div>
              <strong>${escapeHtml(file.name)}</strong><br>
              <small>${escapeHtml(formatBytes(file.size))} - ${dateTime(file.uploadedAt)}</small>
            </div>
            <div class="inline-actions">
              <button class="secondary mini" type="button" data-file-download="${escapeHtml(file.id)}">Ladda ned</button>
              <button class="danger mini" type="button" data-file-delete="${escapeHtml(file.id)}">Ta bort</button>
            </div>
          </div>
        `,
      )
      .join("");
  }

  function taskHtml(task) {
    return `
      <div class="task-row ${task.done ? "done" : ""}">
        <div>
          <strong>${escapeHtml(task.title)}</strong><br>
          <small>${escapeHtml(task.owner || users[0])} - förfaller ${escapeHtml(task.dueDate || "ej satt")}</small>
        </div>
        <button class="secondary mini" type="button" data-task-toggle="${escapeHtml(task.id)}">
          ${task.done ? "Öppna igen" : "Klar"}
        </button>
      </div>
    `;
  }

  function bindCaseOpeners() {
    document.querySelectorAll("[data-case-open]").forEach((element) => {
      element.addEventListener("click", () => {
        state.selectedCaseId = element.dataset.caseOpen;
        state.view = "cases";
        saveState();
        renderAll();
        document.getElementById("caseDetail")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  async function bindLegalResearch(caseId, item) {
    // Check backend status
    const statusBadge = document.getElementById("backendStatus");
    const available = await window.SwiftclaimAPI.isAvailable();
    if (statusBadge) {
      statusBadge.textContent = available ? "Backend ansluten" : "Backend ej tillgänglig";
      statusBadge.dataset.status = available ? "connected" : "offline";
    }

    // Search law button
    document.getElementById("searchLawBtn")?.addEventListener("click", async () => {
      const resultsEl = document.getElementById("legalResults");
      resultsEl.innerHTML = '<p class="muted">Söker lagstiftning och prejudikat...</p>';
      const query = `${item.category} ${item.shortDescription || ""}`.trim();
      const data = await window.SwiftclaimAPI.searchLaw(query);
      if (!data || !data.hits) {
        resultsEl.innerHTML = '<p class="muted">Kunde inte nå backend. Kör <code>python backend/run.py</code> för att starta.</p>';
        return;
      }
      resultsEl.innerHTML = renderLawResults(data.hits);
    });

    // Generate draft button — async job with stage progress
    const DRAFT_STAGES = {
      queued: "Köad...",
      planning: "Planerar argument...",
      retrieving: "Söker rättskällor...",
      drafting: "Skriver utkast...",
      verifying: "Verifierar källor...",
    };

    // Resume: show the latest finished draft, or re-attach to a running job
    if (available) {
      window.SwiftclaimAPI.getLatestDraftJob(item.id).then(async (latest) => {
        const resultsEl = document.getElementById("legalResults");
        if (!latest || !resultsEl || resultsEl.textContent.trim()) return;
        if (latest.status === "done" && latest.draft) {
          resultsEl.innerHTML = renderDraftResult(latest.draft);
        } else if (DRAFT_STAGES[latest.status]) {
          resultsEl.innerHTML = `<p class="muted draft-progress">${DRAFT_STAGES[latest.status]} (återupptaget)</p>`;
          const job = await window.SwiftclaimAPI.pollDraftJob(latest.id, (status) => {
            const label = DRAFT_STAGES[status];
            if (label) resultsEl.innerHTML = `<p class="muted draft-progress">${label}</p>`;
          });
          if (job && job.status === "done") resultsEl.innerHTML = renderDraftResult(job.draft || {});
        }
      });
    }
    document.getElementById("generateDraftBtn")?.addEventListener("click", async () => {
      const resultsEl = document.getElementById("legalResults");
      resultsEl.innerHTML = '<p class="muted draft-progress">Startar utkastjobb...</p>';
      const job = await window.SwiftclaimAPI.generateDraft(item, (status) => {
        const label = DRAFT_STAGES[status];
        if (label) resultsEl.innerHTML = `<p class="muted draft-progress">${label}</p>`;
      });
      if (!job) {
        resultsEl.innerHTML = '<p class="muted">Kunde inte starta utkastjobbet. Kör <code>python backend/run.py</code>.</p>';
        return;
      }
      if (job.status === "failed") {
        resultsEl.innerHTML = `<p class="muted">Utkastet misslyckades: ${escapeHtml(job.error || "okänt fel")}</p>`;
        return;
      }
      if (job.status === "timeout") {
        resultsEl.innerHTML = '<p class="muted">Jobbet tar längre än väntat — öppna ärendet igen om en stund.</p>';
        return;
      }
      resultsEl.innerHTML = renderDraftResult(job.draft || {});
    });

    // Ask button — case-scoped question to the knowledge base
    const askBtn = document.getElementById("askBtn");
    const askInput = document.getElementById("askInput");
    if (askBtn && askInput) {
      askBtn.addEventListener("click", async () => {
        const question = askInput.value.trim();
        if (!question) return;
        const resultsEl = document.getElementById("legalResults");
        resultsEl.innerHTML = '<p class="muted">Söker svar i kunskapsbasen...</p>';
        const data = await window.SwiftclaimAPI.ask(question, item.id);
        resultsEl.innerHTML = data ? renderAnswer(data) : '<p class="muted">Kunde inte få svar. Kontrollera att backend körs.</p>';
      });
      askInput.addEventListener("keydown", (e) => { if (e.key === "Enter") askBtn.click(); });
    }

    // Import case to backend button
    document.getElementById("importCaseBtn")?.addEventListener("click", async () => {
      const resultsEl = document.getElementById("legalResults");
      resultsEl.innerHTML = '<p class="muted">Synkroniserar ärende till backend...</p>';
      const data = await window.SwiftclaimAPI.importCase(item);
      if (data) {
        resultsEl.innerHTML = `<p class="success">Ärende ${escapeHtml(item.id)} synkroniserat till backend.</p>`;
      } else {
        resultsEl.innerHTML = '<p class="muted">Kunde inte synka. Kör <code>python backend/run.py</code></p>';
      }
    });
  }

  function renderLawResults(hits) {
    if (!hits.length) return '<p class="muted">Inga relevanta lagrum eller prejudikat hittades.</p>';
    return `
      <div class="results-count">${hits.length} relevanta träffar</div>
      ${hits.map((hit) => `
        <div class="law-result ${hit.path.startsWith("ARN/") ? "precedent" : "statute"}">
          <div class="law-result-header">
            <span class="badge ${hit.path.startsWith("ARN/") ? "precedent" : "statute"}">${hit.path.startsWith("ARN/") ? "ARN" : "Lagrum"}</span>
            <strong>${escapeHtml(hit.title)}</strong>
            <span class="muted score">${Math.round(hit.score * 100)}% match</span>
          </div>
          <p>${escapeHtml(hit.text?.slice(0, 500) || "")}${(hit.text?.length || 0) > 500 ? "..." : ""}</p>
        </div>
      `).join("")}
    `;
  }

  function renderSourceList(sources) {
    if (!sources || !sources.length) return "";
    return `<ul class="source-list">${sources.map((s) => `
      <li>
        <span class="badge ${String(s.path || s.ref).startsWith("ARN") ? "precedent" : "statute"}">${escapeHtml(s.ref)}</span>
        ${s.source_url ? `<a href="${escapeHtml(s.source_url)}" target="_blank" rel="noopener">lagen.nu ↗</a>` : ""}
        ${s.score ? `<span class="muted score">${Math.round(s.score * 100)}%</span>` : ""}
      </li>`).join("")}</ul>`;
  }

  function renderAnswer(data) {
    return `
      <div class="answer-card">
        <h4>Svar</h4>
        <pre class="draft-text">${escapeHtml(data.answer_markdown || "")}</pre>
        ${data.sources?.length ? `<h4>Källor</h4>${renderSourceList(data.sources)}` : ""}
        ${data.unverified_refs?.length ? `
          <p class="flagged-warning">⚠ Overifierade hänvisningar: ${data.unverified_refs.map(escapeHtml).join(", ")}</p>` : ""}
      </div>
    `;
  }

  function renderDraftResult(draft) {
    const flagged = draft.flagged_citations || [];
    const evidence = draft.evidence || [];
    const citations = draft.citations_used || [];
    return `
      <div class="results-count">Juridiskt utkast genererat (v${draft.version || 1}${draft.model_used ? ` · ${escapeHtml(draft.model_used)}` : ""})</div>
      ${draft.status === "needs_review" ? `
        <div class="needs-review-banner">⚠ Kräver manuell granskning${flagged.length ? ` — overifierade hänvisningar: ${flagged.map(escapeHtml).join(", ")}` : " — inga källor hittades"}</div>` : ""}
      ${draft.strategy ? `
        <div class="draft-section">
          <h4>Strategi</h4>
          <pre class="draft-text">${escapeHtml(draft.strategy)}</pre>
        </div>
      ` : ""}
      <div class="draft-section">
        <h4>Brevutkast</h4>
        <pre class="draft-text">${escapeHtml(draft.draft_text || "")}</pre>
      </div>
      ${citations.length ? `
        <div class="draft-section">
          <h4>Verifierade referenser</h4>
          <ul>${citations.map((c) => `<li>✓ ${escapeHtml(c)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${evidence.length ? `
        <div class="draft-section">
          <h4>Källunderlag</h4>
          ${renderSourceList(evidence.map((d) => ({ ref: d.title, path: d.path, score: d.score, source_url: d.source_url })))}
        </div>
      ` : ""}
    `;
  }

  function bindCaseDetail(caseId) {
    const item = getCase(caseId);
    if (!item) return;

    bindLegalResearch(caseId, item);

    document.getElementById("detailStatus").addEventListener("change", (event) => {
      updateCase(caseId, (draft) => {
        draft.status = event.target.value;
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Status ändrad", `Flyttades till ${draft.status}.`);
      });
    });

    document.getElementById("detailOwner").addEventListener("change", (event) => {
      updateCase(caseId, (draft) => {
        draft.responsible = event.target.value;
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Ansvarig ändrad", `Tilldelades ${draft.responsible}.`);
      });
    });

    document.getElementById("detailPriority").addEventListener("change", (event) => {
      updateCase(caseId, (draft) => {
        draft.priority = event.target.value;
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Prioritet ändrad", `Prioritet satt till ${draft.priority}.`);
      });
    });

    document.getElementById("detailOutcome").addEventListener("change", (event) => {
      updateCase(caseId, (draft) => {
        draft.outcome.result = event.target.value;
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Utfall uppdaterat", `Utfall markerat som ${draft.outcome.result}.`);
      });
    });

    document.getElementById("detailDescription").addEventListener("change", (event) => {
      updateCase(caseId, (draft) => {
        draft.shortDescription = event.target.value.trim();
        draft.intake.description = draft.shortDescription;
        draft.updatedAt = new Date().toISOString();
      });
    });

    document.getElementById("regenerateScoreBtn").addEventListener("click", () => {
      updateCase(caseId, (draft) => {
        draft.scorecard = analyzeIntake(draft.intake);
        draft.category = draft.scorecard.damageCategory;
        draft.insuranceCompany = draft.scorecard.insuranceCompany;
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Bedömningskort regenererat", "AI-utkast uppdaterat från senaste intagsfält.");
      });
    });

    document.getElementById("downloadCaseMdBtn").addEventListener("click", () => {
      const selected = getCase(caseId);
      downloadText(`${slugify(selected.id)}-${slugify(selected.customer.name)}.md`, caseToMarkdown(selected), "text/markdown");
    });

    document.getElementById("deleteCaseBtn").addEventListener("click", () => {
      if (!confirm(`Ta bort ${caseId}? Detta tar bort ärendedata från den här webbläsaren.`)) return;
      state.cases = state.cases.filter((caseItem) => caseItem.id !== caseId);
      state.selectedCaseId = state.cases[0]?.id || null;
      saveState();
      renderAll();
    });

    document.getElementById("fileUpload").addEventListener("change", async (event) => {
      const files = Array.from(event.target.files || []);
      if (!files.length) return;
      await Promise.all(files.map((file) => saveCaseFile(caseId, file)));
      event.target.value = "";
      updateCase(caseId, (draft) => {
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Filer tillagda", `${files.length} ${files.length === 1 ? "fil" : "filer"} laddades upp till ärendet.`);
      });
    });

    document.querySelectorAll("[data-file-download]").forEach((button) => {
      button.addEventListener("click", () => downloadStoredFile(button.dataset.fileDownload));
    });

    document.querySelectorAll("[data-file-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        const fileId = button.dataset.fileDelete;
        await deleteStoredFile(fileId);
        updateCase(caseId, (draft) => {
          draft.documents = draft.documents.filter((file) => file.id !== fileId);
          draft.updatedAt = new Date().toISOString();
          addTimeline(draft, "Fil borttagen", "En fil togs bort från ärendet.");
        });
      });
    });

    document.getElementById("addNoteBtn").addEventListener("click", () => {
      const body = document.getElementById("noteBody").value.trim();
      if (!body) return;
      const author = document.getElementById("noteAuthor").value;
      const type = document.getElementById("noteType").value;
      updateCase(caseId, (draft) => {
        draft.notes.push({
          id: makeId("note"),
          author,
          type,
          body,
          createdAt: new Date().toISOString(),
        });
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Anteckning tillagd", `${author} lade till ${type.toLowerCase()}.`);
      });
    });

    document.getElementById("addTaskBtn").addEventListener("click", () => {
      const title = document.getElementById("taskTitle").value.trim();
      if (!title) return;
      const dueDate = document.getElementById("taskDue").value;
      updateCase(caseId, (draft) => {
        draft.tasks.push({
          id: makeId("task"),
          title,
          dueDate,
          owner: draft.responsible,
          done: false,
        });
        draft.updatedAt = new Date().toISOString();
        addTimeline(draft, "Uppgift tillagd", title);
      });
    });

    document.querySelectorAll("[data-task-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const taskId = button.dataset.taskToggle;
        updateCase(caseId, (draft) => {
          const task = draft.tasks.find((candidate) => candidate.id === taskId);
          if (!task) return;
          task.done = !task.done;
          draft.updatedAt = new Date().toISOString();
          addTimeline(draft, task.done ? "Uppgift klar" : "Uppgift öppnad igen", task.title);
        });
      });
    });
  }

  function renderPipeline() {
    document.getElementById("pipelineBoard").innerHTML = pipelineStatuses
      .map((status) => {
        const items = state.cases.filter((item) => item.status === status);
        return `
          <section class="pipeline-column" data-pipeline-status="${escapeHtml(status)}">
            <h2>${escapeHtml(status)} <span class="badge">${items.length}</span></h2>
            ${items.map(pipelineCardHtml).join("") || `<div class="empty">Inga ärenden</div>`}
          </section>
        `;
      })
      .join("");
    bindPipelineDragAndDrop();
    bindCaseOpeners();
  }

  function pipelineCardHtml(item) {
    return `
      <button class="pipeline-card" type="button" draggable="true" data-pipeline-case="${escapeHtml(item.id)}" data-case-open="${escapeHtml(item.id)}" aria-label="Flytta eller öppna ${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.id)} - ${escapeHtml(item.customer.name)}</strong>
        <small>${escapeHtml(item.category)} - ${escapeHtml(item.insuranceCompany)}</small><br>
        <small>${escapeHtml(formatMoney(item.scorecard.estimatedTicketSize.high))} - svårighet ${escapeHtml(String(item.scorecard.difficultyRating))}/5</small>
      </button>
    `;
  }

  function bindPipelineDragAndDrop() {
    let draggedCaseId = null;
    let dragStarted = false;

    document.querySelectorAll("[data-pipeline-case]").forEach((card) => {
      card.addEventListener("dragstart", (event) => {
        draggedCaseId = card.dataset.pipelineCase;
        dragStarted = true;
        card.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", draggedCaseId);
      });

      card.addEventListener("dragend", () => {
        card.classList.remove("dragging");
        lastPipelineDragAt = Date.now();
        document.querySelectorAll(".pipeline-column").forEach((column) => {
          column.classList.remove("drop-target");
        });
        window.setTimeout(() => {
          dragStarted = false;
        }, 0);
      });

      card.addEventListener("click", (event) => {
        if (dragStarted || Date.now() - lastPipelineDragAt < 300) {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      });
    });

    document.querySelectorAll("[data-pipeline-status]").forEach((column) => {
      column.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        column.classList.add("drop-target");
      });

      column.addEventListener("dragleave", (event) => {
        if (!event.relatedTarget || !column.contains(event.relatedTarget)) {
          column.classList.remove("drop-target");
        }
      });

      column.addEventListener("drop", (event) => {
        event.preventDefault();
        column.classList.remove("drop-target");
        lastPipelineDragAt = Date.now();
        const caseId = event.dataTransfer.getData("text/plain") || draggedCaseId;
        const nextStatus = column.dataset.pipelineStatus;
        moveCaseToStatus(caseId, nextStatus);
      });
    });
  }

  function moveCaseToStatus(caseId, nextStatus) {
    const item = getCase(caseId);
    if (!item || !pipelineStatuses.includes(nextStatus) || item.status === nextStatus) return;
    updateCase(caseId, (draft) => {
      const previousStatus = draft.status;
      draft.status = nextStatus;
      draft.updatedAt = new Date().toISOString();
      addTimeline(draft, "Status ändrad", `Drogs från ${previousStatus} till ${nextStatus}.`);
    });
  }

  function renderKnowledge() {
    const select = document.getElementById("knowledgeCaseSelect");
    if (select) {
      const selectedId = select.value || state.selectedCaseId || state.cases[0]?.id;
      select.innerHTML = state.cases
        .map(
          (item) =>
            `<option value="${escapeHtml(item.id)}"${item.id === selectedId ? " selected" : ""}>${escapeHtml(item.id)} - ${escapeHtml(item.customer.name)}</option>`,
        )
        .join("");
      select.onchange = () => {
        state.selectedCaseId = select.value;
        saveState();
        renderKnowledgeMarkdown();
      };
    }
    document.getElementById("downloadMarkdownBtn").onclick = () => {
      const item = getCase(document.getElementById("knowledgeCaseSelect").value);
      if (!item) return;
      downloadText(`${slugify(item.id)}-${slugify(item.customer.name)}.md`, caseToMarkdown(item), "text/markdown");
    };
    document.getElementById("copyMarkdownBtn").onclick = async () => {
      const output = document.getElementById("markdownOutput");
      output.select();
      try {
        await navigator.clipboard.writeText(output.value);
      } catch (error) {
        document.execCommand("copy");
      }
    };

    // Vault search
    const vaultSearchBtn = document.getElementById("vaultSearchBtn");
    const vaultSearchInput = document.getElementById("vaultSearchInput");
    if (vaultSearchBtn && vaultSearchInput) {
      vaultSearchBtn.onclick = async () => {
        const query = vaultSearchInput.value.trim();
        if (!query) return;
        const resultsEl = document.getElementById("vaultResults");
        resultsEl.innerHTML = '<p class="muted">Söker i juridisk kunskapsbas...</p>';
        const data = await window.SwiftclaimAPI.searchLaw(query);
        if (!data || !data.hits) {
          resultsEl.innerHTML = '<p class="muted">Kunde inte nå backend. Starta med <code>python backend/run.py</code>.</p>';
          return;
        }
        resultsEl.innerHTML = renderLawResults(data.hits);
      };
      vaultSearchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") vaultSearchBtn.click();
      });
    }

    // Knowledge base Q&A
    const askKBtn = document.getElementById("knowledgeAskBtn");
    const askKInput = document.getElementById("knowledgeAskInput");
    if (askKBtn && askKInput) {
      askKBtn.onclick = async () => {
        const question = askKInput.value.trim();
        if (!question) return;
        const resultEl = document.getElementById("knowledgeAskResult");
        resultEl.innerHTML = '<p class="muted">Söker svar i kunskapsbasen...</p>';
        const data = await window.SwiftclaimAPI.ask(question);
        resultEl.innerHTML = data ? renderAnswer(data) : '<p class="muted">Kunde inte få svar. Kör <code>python backend/run.py</code>.</p>';
      };
      askKInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") askKBtn.click();
      });
    }

    renderKnowledgeMarkdown();
  }

  function renderKnowledgeMarkdown() {
    const item = getCase(document.getElementById("knowledgeCaseSelect")?.value || state.selectedCaseId);
    document.getElementById("markdownOutput").value = item ? caseToMarkdown(item) : "";
  }

  function caseToMarkdown(item) {
    const sources = [
      `raw/arenden/${item.id}/intag.json`,
      ...item.documents.map((file) => `raw/arenden/${item.id}/dokument/${file.name}`),
      `raw/arenden/${item.id}/anteckningar.json`,
      `raw/arenden/${item.id}/tidslinje.json`,
    ];
    return `---
id: ${item.id}
typ: forsakring_egendomsskade_arende
status: ${yamlValue(item.status)}
kund_stad: ${yamlValue(item.customer.city || "okänt")}
bostadstyp: ${yamlValue(item.customer.propertyType)}
forsakringsbolag: ${yamlValue(item.insuranceCompany)}
skadekategori: ${yamlValue(item.category)}
arendevarde_lag_sek: ${item.scorecard.estimatedTicketSize.low}
arendevarde_hog_sek: ${item.scorecard.estimatedTicketSize.high}
svarighetsgrad: ${item.scorecard.difficultyRating}
bevisningskvalitet: ${item.scorecard.evidenceQuality}
tidsrisk: ${yamlValue(item.scorecard.deadlineRisk)}
utfall: ${yamlValue(item.outcome.result)}
kallor:
${sources.map((source) => `  - ${yamlValue(source)}`).join("\n")}
---

# ${item.id} ${item.customer.name}

## Ärendesammanfattning
${item.scorecard.summary}

## Nuvarande läge
- Status: ${item.status}
- Ansvarig: ${item.responsible}
- Försäkringsbolag: [[${item.insuranceCompany}]]
- Skadekategori: [[${item.category}]]
- Bostadstyp: ${item.customer.propertyType}
- Skadedatum: ${item.incidentDate || "okänt"}
- Beslutsdatum från försäkringsbolag: ${item.decisionDate || "okänt"}
- Begärt belopp: ${formatMoney(item.claimedAmount)}
- Erbjudet belopp: ${formatMoney(item.offeredAmount)}

## AI-bedömningskort
- Bedömt ärendevärde: ${formatMoney(item.scorecard.estimatedTicketSize.low)}-${formatMoney(item.scorecard.estimatedTicketSize.high)}
- Svårighet: ${item.scorecard.difficultyRating}/5
- Bevisningskvalitet: ${item.scorecard.evidenceQuality}/5
- Tidsrisk: ${item.scorecard.deadlineRisk}
- AI-säkerhet: ${item.scorecard.aiConfidence}
- Granskningsstatus: ${item.scorecard.reviewStatus}

## Föreslaget nästa steg
${item.scorecard.suggestedNextAction}

## Saknade dokument
${markdownList(item.scorecard.missingDocuments)}

## Riskflaggor
${markdownList(item.scorecard.riskFlags)}

## Kundens beskrivning
${item.shortDescription || "Ingen beskrivning ännu."}

## Uppladdade dokument
${markdownList(item.documents.map((file) => `${file.name} (${formatBytes(file.size)})`))}

## Anteckningar
${item.notes
  .map((note) => `- ${dateTime(note.createdAt)} - ${note.author}: ${note.body.replace(/\n/g, " ")}`)
  .join("\n") || "- Inga anteckningar ännu."}

## Tidslinje
${item.timeline
  .map((event) => `- ${dateTime(event.at)} - ${event.title}: ${event.body}`)
  .join("\n") || "- Inga tidslinjehändelser ännu."}

## Lärdomar från utfall
Resultat: ${item.outcome.result}

Lärdomar:
${item.outcome.lessons || "Utfall saknas ännu. Lägg till uppgörelse, avslagsorsak, bolagsbeteende och användbara argumentmönster efter stängning."}
`;
  }

  function markdownList(items) {
    if (!items || !items.length) return "- Inga";
    return items.map((item) => `- ${item}`).join("\n");
  }

  function yamlValue(value) {
    return `"${String(value).replace(/"/g, '\\"')}"`;
  }

  function updateCase(caseId, mutator) {
    const index = state.cases.findIndex((item) => item.id === caseId);
    if (index === -1) return;
    mutator(state.cases[index]);
    saveState();
    renderAll();
  }

  function addTimeline(item, title, body) {
    item.timeline.push({
      id: makeId("event"),
      at: new Date().toISOString(),
      title,
      body,
    });
  }

  function getSelectedCase() {
    return getCase(state.selectedCaseId) || state.cases[0] || null;
  }

  function getCase(caseId) {
    return state.cases.find((item) => item.id === caseId);
  }

  function nextCaseId() {
    const next = state.cases.length + 1 + Math.floor(Math.random() * 9);
    const date = new Date();
    const yymm = String(date.getFullYear()).slice(2) + String(date.getMonth() + 1).padStart(2, "0");
    let id = `SC-${yymm}-${String(next).padStart(3, "0")}`;
    while (state.cases.some((item) => item.id === id)) {
      id = `SC-${yymm}-${String(next + Math.floor(Math.random() * 99)).padStart(3, "0")}`;
    }
    return id;
  }

  async function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(FILE_STORE)) {
          const store = db.createObjectStore(FILE_STORE, { keyPath: "id" });
          store.createIndex("caseId", "caseId", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return dbPromise;
  }

  async function saveCaseFile(caseId, file) {
    const id = makeId("file");
    const metadata = {
      id,
      caseId,
      name: file.name,
      type: file.type || "application/octet-stream",
      size: file.size,
      uploadedAt: new Date().toISOString(),
      uploadedBy: "Nuvarande användare",
    };
    const db = await openDb();
    await txPromise(db, FILE_STORE, "readwrite", (store) => {
      store.put({ ...metadata, blob: file });
    });
    const item = getCase(caseId);
    if (item) {
      item.documents.push(metadata);
      saveState();
    }
  }

  async function downloadStoredFile(fileId) {
    const fileRecord = await getStoredFile(fileId);
    if (!fileRecord) {
      alert("Den här filen finns inte i webbläsarens lagring.");
      return;
    }
    const url = URL.createObjectURL(fileRecord.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileRecord.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function getStoredFile(fileId) {
    const db = await openDb();
    return txPromise(db, FILE_STORE, "readonly", (store) => store.get(fileId));
  }

  async function deleteStoredFile(fileId) {
    const db = await openDb();
    return txPromise(db, FILE_STORE, "readwrite", (store) => store.delete(fileId));
  }

  function txPromise(db, storeName, mode, operation) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);
      const request = operation(store);
      let result;
      if (request) {
        request.onsuccess = () => {
          result = request.result;
        };
        request.onerror = () => reject(request.error);
      }
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
    });
  }

  function downloadText(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function formatMoney(value) {
    const number = Number(value) || 0;
    return `${Math.round(number).toLocaleString("sv-SE")} SEK`;
  }

  function riskClass(value) {
    return (
      {
        hög: "high",
        medel: "medium",
        låg: "low",
        high: "high",
        medium: "medium",
        low: "low",
      }[value] || "low"
    );
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const value = bytes / 1024 ** index;
    return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
  }

  function dateShort(value) {
    if (!value) return "Inget datum";
    return new Date(value).toLocaleDateString("sv-SE");
  }

  function dateTime(value) {
    if (!value) return "Inget datum";
    return new Date(value).toLocaleString("sv-SE", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function daysSince(value) {
    if (!value) return 0;
    const start = new Date(`${value}T00:00:00`);
    const now = new Date();
    return Math.floor((now - start) / 86400000);
  }

  function offsetDate(days) {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return date.toISOString();
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function makeId(prefix) {
    return `${prefix}_${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-4)}`;
  }

  function slugify(value) {
    return String(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
})();
