"use strict";

// ---------------------------------------------------------------------------
// On-Page Optimiser view
// Two modes: Review (analyse + rewrite existing copy) | Build (research + write new page)
// ---------------------------------------------------------------------------

const OPT_SESSION_KEY = "agency_on_page_opt_session";

// Stages are shared across both modes — the mode field on the session determines
// which backend endpoints are called.
const OPT_STAGES = {
  idle:              { startReview: true,  startBuild: true,  nextStep: false, copy: false, saveNotion: false, reset: false },
  analysing:         { startReview: false, startBuild: false, nextStep: false, copy: false, saveNotion: false, reset: false },
  awaiting_rewrite:  { startReview: false, startBuild: false, nextStep: true,  copy: false, saveNotion: false, reset: false },
  rewriting:         { startReview: false, startBuild: false, nextStep: false, copy: false, saveNotion: false, reset: false },
  researching:       { startReview: false, startBuild: false, nextStep: false, copy: false, saveNotion: false, reset: false },
  awaiting_write:    { startReview: false, startBuild: false, nextStep: true,  copy: false, saveNotion: false, reset: false },
  writing:           { startReview: false, startBuild: false, nextStep: false, copy: false, saveNotion: false, reset: false },
  done:              { startReview: true,  startBuild: true,  nextStep: false, copy: true,  saveNotion: true,  reset: true  },
};

// Which panel shows "Running…" in each stage
const OPT_ACTIVE_PANEL = {
  analysing:   "panel-a",
  researching: "panel-a",
  rewriting:   "panel-b",
  writing:     "panel-b",
};

// Pipeline steps: 3 steps for both modes (step labels are updated dynamically)
const OPT_PIPELINE = {
  idle:             { active: 1, completed: [] },
  analysing:        { active: 1, completed: [] },
  awaiting_rewrite: { active: 1, completed: [1] },
  rewriting:        { active: 2, completed: [1] },
  researching:      { active: 1, completed: [] },
  awaiting_write:   { active: 1, completed: [1] },
  writing:          { active: 2, completed: [1] },
  done:             { active: 3, completed: [1, 2] },
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $op = (id) => document.getElementById(id);

function getOptUi() {
  return {
    // Mode toggle
    modeToggleReview: $op("opt-mode-review"),
    modeToggleBuild:  $op("opt-mode-build"),
    modeToggleRow:    $op("opt-mode-toggle"),
    // Review inputs
    reviewInputs:     $op("opt-review-inputs"),
    copyInput:        $op("opt-copy-input"),
    keywordInput:     $op("opt-keyword-input"),
    pageTypeReview:   $op("opt-page-type-review"),
    auditCtxReview:   $op("opt-audit-ctx-review"),
    btnStartReview:   $op("opt-btn-start-review"),
    // Build inputs
    buildInputs:      $op("opt-build-inputs"),
    promptInput:      $op("opt-prompt-input"),
    locationInput:    $op("opt-location-input"),
    pageTypeBuild:    $op("opt-page-type-build"),
    auditCtxBuild:    $op("opt-audit-ctx-build"),
    btnStartBuild:    $op("opt-btn-start-build"),
    // Panel A (Analyser / Researcher)
    panelA:           $op("opt-panel-a"),
    panelATitle:      $op("opt-panel-a-title"),
    panelASubtitle:   $op("opt-panel-a-subtitle"),
    panelAStatus:     $op("opt-panel-a-status"),
    panelAOutput:     $op("opt-panel-a-output"),
    keywordCard:      $op("opt-keyword-card"),
    btnNextStep:      $op("opt-btn-next-step"),
    // Panel B (Copywriter)
    panelB:           $op("opt-panel-b"),
    panelBStatus:     $op("opt-panel-b-status"),
    panelBOutput:     $op("opt-panel-b-output"),
    wordCount:        $op("opt-word-count"),
    btnCopy:          $op("opt-btn-copy"),
    btnSaveNotion:    $op("opt-btn-save-notion"),
    // Pipeline
    step1:            $op("opt-step-1"),
    step2:            $op("opt-step-2"),
    step3:            $op("opt-step-3"),
    line12:           $op("opt-line-1-2"),
    line23:           $op("opt-line-2-3"),
    stepLabel1:       $op("opt-step-label-1"),
    stepLabel2:       $op("opt-step-label-2"),
    stepLabel3:       $op("opt-step-label-3"),
    // Header button
    btnReset:         $op("opt-btn-reset"),
  };
}

let opu = null;
let OPT_SESSION_ID = null;
let _optInitialized = false;
let _currentMode = "review"; // tracks UI mode selection

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function initOptSession() {
  let sid = localStorage.getItem(OPT_SESSION_KEY);

  if (!sid) {
    const res = await fetch("/api/on-page-opt/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    localStorage.setItem(OPT_SESSION_KEY, sid);
  }

  OPT_SESSION_ID = sid;

  try {
    const state = await fetch(`/api/on-page-opt/state?session_id=${OPT_SESSION_ID}`).then((r) => r.json());
    restoreOptState(state);
  } catch (e) {
    console.warn("Could not restore on-page opt session:", e);
  }
}

function restoreOptState(state) {
  if (!state) return;

  const mode = state.mode || "review";
  _currentMode = mode;
  setModeUi(mode);

  if (mode === "review") {
    if (state.original_copy) opu.copyInput.value = state.original_copy;
    if (state.target_keyword) opu.keywordInput.value = state.target_keyword;
  } else {
    if (state.prompt) opu.promptInput.value = state.prompt;
    if (state.location) opu.locationInput.value = state.location;
  }

  if (state.analysis) {
    clearOptEmptyState(opu.panelAOutput);
    opu.panelAOutput.textContent = state.analysis;
  }
  if (state.keyword_brief) {
    clearOptEmptyState(opu.panelAOutput);
    opu.panelAOutput.textContent = state.keyword_brief;
    if (state.keyword_data && Object.keys(state.keyword_data).length) {
      renderKeywordCard(state.keyword_data);
    }
  }
  if (state.final_copy) {
    clearOptEmptyState(opu.panelBOutput);
    opu.panelBOutput.textContent = state.final_copy;
    updateWordCount(state.final_copy);
  }

  // Recover from in-progress stages safely
  const safeStage = ["analysing", "rewriting", "researching", "writing"].includes(state.stage)
    ? "idle"
    : state.stage || "idle";
  setOptStage(safeStage);
}

// ---------------------------------------------------------------------------
// Mode toggle
// ---------------------------------------------------------------------------

function setModeUi(mode) {
  _currentMode = mode;
  const isReview = mode === "review";
  opu.reviewInputs.style.display = isReview ? "" : "none";
  opu.buildInputs.style.display  = isReview ? "none" : "";

  opu.modeToggleReview.classList.toggle("mode-btn--active", isReview);
  opu.modeToggleBuild.classList.toggle("mode-btn--active", !isReview);

  // Update pipeline labels
  if (isReview) {
    opu.stepLabel1.textContent = "Analyse";
    opu.stepLabel2.textContent = "Optimise";
    opu.panelATitle.textContent   = "Analyser";
    opu.panelASubtitle.textContent = "On-page SEO issues identified";
    opu.btnNextStep.textContent = "Optimise Copy →";
  } else {
    opu.stepLabel1.textContent = "Research";
    opu.stepLabel2.textContent = "Write";
    opu.panelATitle.textContent   = "Researcher";
    opu.panelASubtitle.textContent = "Keyword research · Search intent · Brief";
    opu.btnNextStep.textContent = "Write Page →";
  }
}

// ---------------------------------------------------------------------------
// Stage machine
// ---------------------------------------------------------------------------

function setOptStage(stage) {
  const cfg = OPT_STAGES[stage] || OPT_STAGES.idle;
  const isIdle = stage === "idle" || stage === "done";

  opu.btnStartReview.disabled = !cfg.startReview;
  opu.btnStartBuild.disabled  = !cfg.startBuild;
  opu.btnNextStep.disabled    = !cfg.nextStep;
  opu.btnCopy.disabled        = !cfg.copy;
  opu.btnSaveNotion.disabled  = !cfg.saveNotion;
  opu.btnReset.disabled       = !cfg.reset;

  // Mode toggle only available at idle/done
  opu.modeToggleRow.style.display = isIdle ? "" : "none";

  // Clear all statuses
  [opu.panelAStatus, opu.panelBStatus].forEach((el) => {
    el.textContent = "";
    el.classList.remove("running");
  });
  [opu.panelA, opu.panelB].forEach((el) => el.classList.remove("panel--active"));

  const activePanel = OPT_ACTIVE_PANEL[stage];
  if (activePanel) {
    const statusEl = $op(`opt-${activePanel}-status`);
    if (statusEl) {
      statusEl.textContent = "Running…";
      statusEl.classList.add("running");
    }
    $op(`opt-${activePanel}`).classList.add("panel--active");
  }

  updateOptPipeline(stage);
}

function updateOptPipeline(stage) {
  const state = OPT_PIPELINE[stage] || OPT_PIPELINE.idle;

  for (let i = 1; i <= 3; i++) {
    const stepEl = $op(`opt-step-${i}`);
    if (!stepEl) continue;
    stepEl.classList.remove("active", "completed");

    if (state.completed.includes(i)) {
      stepEl.classList.add("completed");
    } else if (state.active === i) {
      stepEl.classList.add("active");
    }
  }

  // Lines
  [[1,2], [2,3]].forEach(([a, b]) => {
    const lineEl = $op(`opt-line-${a}-${b}`);
    if (!lineEl) return;
    lineEl.classList.toggle("completed", state.completed.includes(a));
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clearOptEmptyState(el) {
  const empty = el.querySelector(".empty-state");
  if (empty) empty.remove();
}

function appendOptCursor(el) {
  const cur = document.createElement("span");
  cur.className = "stream-cursor";
  el.appendChild(cur);
  return cur;
}

function showOptError(msg) {
  const toast = document.getElementById("error-toast");
  toast.textContent = msg;
  toast.classList.add("visible");
  setTimeout(() => toast.classList.remove("visible"), 6000);
}

function updateWordCount(text) {
  const count = text.trim().split(/\s+/).filter(Boolean).length;
  opu.wordCount.textContent = `${count.toLocaleString()} words`;
}

function renderKeywordCard(kwData) {
  if (!kwData || !kwData.primary_keyword) return;
  opu.keywordCard.style.display = "block";
  opu.keywordCard.innerHTML = `
    <div class="kw-card-inner">
      <div class="kw-primary">${escapeOptHtml(kwData.primary_keyword)}</div>
      ${kwData.search_intent ? `<span class="kw-intent">${escapeOptHtml(kwData.search_intent)}</span>` : ""}
      ${kwData.secondary_keywords && kwData.secondary_keywords.length
        ? `<div class="kw-secondary">${kwData.secondary_keywords.slice(0, 5).map(k => `<span>${escapeOptHtml(k)}</span>`).join("")}</div>`
        : ""}
    </div>
  `;
}

function escapeOptHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Review mode — Analyse copy
// ---------------------------------------------------------------------------

async function startReview() {
  const copy = opu.copyInput.value.trim();
  const keyword = opu.keywordInput.value.trim();
  const pageType = opu.pageTypeReview.value.trim();
  const auditCtx = opu.auditCtxReview.value.trim();

  if (!copy) { showOptError("Please paste the page copy to review."); return; }
  if (!keyword) { showOptError("Please enter a target keyword."); return; }

  try {
    const res = await fetch("/api/on-page-opt/start-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: OPT_SESSION_ID,
        copy,
        target_keyword: keyword,
        page_type: pageType,
        audit_context: auditCtx,
      }),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.error || "Failed to start review");
    }
  } catch (e) {
    showOptError(`Failed to start review: ${e.message}`);
    return;
  }

  setModeUi("review");
  setOptStage("analysing");
  clearOptEmptyState(opu.panelAOutput);
  opu.panelAOutput.textContent = "";
  opu.keywordCard.style.display = "none";

  const cursor = appendOptCursor(opu.panelAOutput);
  const es = new EventSource(`/api/on-page-opt/stream/analysis?session_id=${OPT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      opu.panelAOutput.textContent = fullText;
      appendOptCursor(opu.panelAOutput);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setOptStage("awaiting_rewrite");
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showOptError(msg.message || "Analysis failed");
      setOptStage("idle");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showOptError("Stream error during analysis");
    setOptStage("idle");
  };
}

// ---------------------------------------------------------------------------
// Review mode — Rewrite copy
// ---------------------------------------------------------------------------

async function startRewrite() {
  try {
    const res = await fetch("/api/on-page-opt/rewrite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: OPT_SESSION_ID }),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.error || "Failed to start rewrite");
    }
  } catch (e) {
    showOptError(`Failed to start rewrite: ${e.message}`);
    return;
  }

  setOptStage("rewriting");
  clearOptEmptyState(opu.panelBOutput);
  opu.panelBOutput.textContent = "";

  const cursor = appendOptCursor(opu.panelBOutput);
  const es = new EventSource(`/api/on-page-opt/stream/rewrite?session_id=${OPT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      opu.panelBOutput.textContent = fullText;
      appendOptCursor(opu.panelBOutput);
      updateWordCount(fullText);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setOptStage("done");
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showOptError(msg.message || "Rewrite failed");
      setOptStage("awaiting_rewrite");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showOptError("Stream error during rewrite");
    setOptStage("awaiting_rewrite");
  };
}

// ---------------------------------------------------------------------------
// Build mode — Research keywords
// ---------------------------------------------------------------------------

async function startBuild() {
  const prompt = opu.promptInput.value.trim();
  const pageType = opu.pageTypeBuild.value.trim();
  const location = opu.locationInput.value.trim();
  const auditCtx = opu.auditCtxBuild.value.trim();

  if (!prompt) { showOptError("Please describe the page you need."); return; }

  try {
    const res = await fetch("/api/on-page-opt/start-build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: OPT_SESSION_ID,
        prompt,
        page_type: pageType,
        location,
        audit_context: auditCtx,
      }),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.error || "Failed to start build");
    }
  } catch (e) {
    showOptError(`Failed to start build: ${e.message}`);
    return;
  }

  setModeUi("build");
  setOptStage("researching");
  clearOptEmptyState(opu.panelAOutput);
  opu.panelAOutput.textContent = "";
  opu.keywordCard.style.display = "none";

  const cursor = appendOptCursor(opu.panelAOutput);
  const es = new EventSource(`/api/on-page-opt/stream/research?session_id=${OPT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      opu.panelAOutput.textContent = fullText;
      appendOptCursor(opu.panelAOutput);
    } else if (msg.type === "keyword_data") {
      renderKeywordCard(msg.data);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setOptStage("awaiting_write");
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showOptError(msg.message || "Research failed");
      setOptStage("idle");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showOptError("Stream error during research");
    setOptStage("idle");
  };
}

// ---------------------------------------------------------------------------
// Build mode — Write page copy
// ---------------------------------------------------------------------------

async function startWrite() {
  try {
    const res = await fetch("/api/on-page-opt/write", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: OPT_SESSION_ID }),
    });
    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.error || "Failed to start writing");
    }
  } catch (e) {
    showOptError(`Failed to start writing: ${e.message}`);
    return;
  }

  setOptStage("writing");
  clearOptEmptyState(opu.panelBOutput);
  opu.panelBOutput.textContent = "";

  const cursor = appendOptCursor(opu.panelBOutput);
  const es = new EventSource(`/api/on-page-opt/stream/copy?session_id=${OPT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      opu.panelBOutput.textContent = fullText;
      appendOptCursor(opu.panelBOutput);
      updateWordCount(fullText);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setOptStage("done");
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showOptError(msg.message || "Writing failed");
      setOptStage("awaiting_write");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showOptError("Stream error during writing");
    setOptStage("awaiting_write");
  };
}

// ---------------------------------------------------------------------------
// Next step button (dispatches to rewrite or write depending on stage)
// ---------------------------------------------------------------------------

function handleNextStep() {
  if (_currentMode === "review") {
    startRewrite();
  } else {
    startWrite();
  }
}

// ---------------------------------------------------------------------------
// Save to Notion
// ---------------------------------------------------------------------------

async function saveOptToNotion() {
  opu.btnSaveNotion.disabled = true;
  opu.btnSaveNotion.textContent = "Saving…";

  try {
    const res = await fetch("/api/on-page-opt/save-to-notion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: OPT_SESSION_ID }),
    });
    const data = await res.json();

    if (data.notion_url) {
      opu.btnSaveNotion.textContent = "Saved ✓";
    } else if (data.error) {
      showOptError(`Notion save failed: ${data.error}`);
      opu.btnSaveNotion.disabled = false;
      opu.btnSaveNotion.textContent = "Save to Notion";
    } else {
      showOptError("Set NOTION_ON_PAGE_OPT_DB_ID in .env to enable Notion saving.");
      opu.btnSaveNotion.disabled = false;
      opu.btnSaveNotion.textContent = "Save to Notion";
    }
  } catch (e) {
    showOptError(`Notion save failed: ${e.message}`);
    opu.btnSaveNotion.disabled = false;
    opu.btnSaveNotion.textContent = "Save to Notion";
  }
}

// ---------------------------------------------------------------------------
// Copy output
// ---------------------------------------------------------------------------

async function copyOptOutput() {
  const text = opu.panelBOutput.textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    opu.btnCopy.textContent = "Copied!";
    setTimeout(() => { opu.btnCopy.textContent = "Copy Copy"; }, 2000);
  } catch (e) {
    showOptError("Could not copy to clipboard");
  }
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

async function resetOpt() {
  await fetch("/api/on-page-opt/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: OPT_SESSION_ID }),
  });

  opu.copyInput.value = "";
  opu.keywordInput.value = "";
  opu.promptInput.value = "";
  opu.locationInput.value = "";
  opu.auditCtxReview.value = "";
  opu.auditCtxBuild.value = "";
  opu.keywordCard.style.display = "none";
  opu.keywordCard.innerHTML = "";

  opu.panelAOutput.innerHTML = '<div class="empty-state">Waiting to start…</div>';
  opu.panelBOutput.innerHTML = '<div class="empty-state">Waiting for step 1 to complete…</div>';
  opu.wordCount.textContent = "";

  opu.btnSaveNotion.textContent = "Save to Notion";

  setModeUi("review");
  setOptStage("idle");
}

// ---------------------------------------------------------------------------
// Wire buttons
// ---------------------------------------------------------------------------

function wireOptButtons() {
  opu.modeToggleReview.addEventListener("click", () => {
    if (!opu.btnStartReview.disabled) setModeUi("review");
  });
  opu.modeToggleBuild.addEventListener("click", () => {
    if (!opu.btnStartBuild.disabled) setModeUi("build");
  });

  opu.btnStartReview.addEventListener("click", startReview);
  opu.btnStartBuild.addEventListener("click", startBuild);
  opu.btnNextStep.addEventListener("click", handleNextStep);
  opu.btnCopy.addEventListener("click", copyOptOutput);
  opu.btnSaveNotion.addEventListener("click", saveOptToNotion);
  opu.btnReset.addEventListener("click", resetOpt);
}

// ---------------------------------------------------------------------------
// View mount hook
// ---------------------------------------------------------------------------

function viewDidMount_onPageOpt() {
  if (_optInitialized) return;
  _optInitialized = true;

  try {
    opu = getOptUi();
    setModeUi("review");
    wireOptButtons();
  } catch (e) {
    console.error("On-Page Opt init error:", e);
    _optInitialized = false;
    return;
  }

  initOptSession().catch((e) => showOptError(`Failed to initialise session: ${e.message}`));
}

window["viewDidMount_on-page-opt"] = viewDidMount_onPageOpt;
