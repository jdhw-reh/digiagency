"use strict";

// ---------------------------------------------------------------------------
// SEO Audit view
// ---------------------------------------------------------------------------

const AUDIT_SESSION_KEY = "agency_seo_audit_session";

const AUDIT_STAGES = {
  idle:                { start: true,  analyse: false, recommend: false, implement: false, copy: false, download: false, saveNotion: false, reset: true  },
  auditing:            { start: false, analyse: false, recommend: false, implement: false, copy: false, download: false, saveNotion: false, reset: false },
  awaiting_analyse:    { start: false, analyse: true,  recommend: false, implement: false, copy: false, download: false, saveNotion: false, reset: true  },
  analysing:           { start: false, analyse: false, recommend: false, implement: false, copy: false, download: false, saveNotion: false, reset: false },
  awaiting_recommend:  { start: false, analyse: false, recommend: true,  implement: false, copy: false, download: false, saveNotion: false, reset: true  },
  recommending:        { start: false, analyse: false, recommend: false, implement: false, copy: false, download: false, saveNotion: false, reset: false },
  awaiting_implement:  { start: false, analyse: false, recommend: false, implement: true,  copy: false, download: false, saveNotion: false, reset: true  },
  implementing:        { start: false, analyse: false, recommend: false, implement: false, copy: false, download: false, saveNotion: false, reset: false },
  done:                { start: true,  analyse: false, recommend: false, implement: false, copy: true,  download: true,  saveNotion: true,  reset: true  },
};

const AUDIT_STAGE_ACTIVE_PANEL = {
  auditing:     "auditor",
  analysing:    "analyser",
  recommending: "recommender",
  implementing: "implementer",
};

const AUDIT_PIPELINE_STATE = {
  idle:               { active: 1, completed: [] },
  auditing:           { active: 1, completed: [] },
  awaiting_analyse:   { active: 1, completed: [1] },
  analysing:          { active: 2, completed: [1] },
  awaiting_recommend: { active: 2, completed: [1, 2] },
  recommending:       { active: 3, completed: [1, 2] },
  awaiting_implement: { active: 3, completed: [1, 2, 3] },
  implementing:       { active: 4, completed: [1, 2, 3] },
  done:               { active: 5, completed: [1, 2, 3, 4] },
};

const NEXT_BAR_CONFIG = {
  awaiting_analyse:   { msg: "<strong>Audit complete.</strong> Ready for deep analysis.", cta: "Run Analysis" },
  awaiting_recommend: { msg: "<strong>Analysis complete.</strong> Ready for recommendations.", cta: "Get Recommendations" },
  awaiting_implement: { msg: "<strong>Recommendations ready.</strong> Build the implementation guide.", cta: "Create Guide" },
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $au = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Mobile carousel helpers
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Accordion state map
// ---------------------------------------------------------------------------

const AUDIT_ACCORDION = {
  idle:               { auditor: 'active', analyser: 'locked',  recommender: 'locked',  implementer: 'locked' },
  auditing:           { auditor: 'active', analyser: 'locked',  recommender: 'locked',  implementer: 'locked' },
  awaiting_analyse:   { auditor: 'done',   analyser: 'active',  recommender: 'locked',  implementer: 'locked' },
  analysing:          { auditor: 'done',   analyser: 'active',  recommender: 'locked',  implementer: 'locked' },
  awaiting_recommend: { auditor: 'done',   analyser: 'done',    recommender: 'active',  implementer: 'locked' },
  recommending:       { auditor: 'done',   analyser: 'done',    recommender: 'active',  implementer: 'locked' },
  awaiting_implement: { auditor: 'done',   analyser: 'done',    recommender: 'done',    implementer: 'active' },
  implementing:       { auditor: 'done',   analyser: 'done',    recommender: 'done',    implementer: 'active' },
  done:               { auditor: 'done',   analyser: 'done',    recommender: 'done',    implementer: 'done'   },
};

function updateAuditAccordion(stage) {
  const acc = AUDIT_ACCORDION[stage] || AUDIT_ACCORDION.idle;
  setPanelState(sau.panelAuditor,     acc.auditor);
  setPanelState(sau.panelAnalyser,    acc.analyser);
  setPanelState(sau.panelRecommender, acc.recommender);
  setPanelState(sau.panelImplementer, acc.implementer);
}

function getAuditUi() {
  return {
    urlInput:           $au("audit-url"),
    contextInput:       $au("audit-context"),
    competitorInputs:   [$au("audit-competitor-1"), $au("audit-competitor-2"), $au("audit-competitor-3")],
    btnStart:           $au("audit-btn-start"),
    btnAnalyse:         $au("audit-btn-analyse"),
    btnRecommend:       $au("audit-btn-recommend"),
    btnImplement:       $au("audit-btn-implement"),
    btnCopy:            $au("audit-btn-copy"),
    btnDownload:        $au("audit-btn-download"),
    btnSaveNotion:      $au("audit-btn-save-notion"),
    btnReset:           $au("audit-btn-reset"),
    auditorOutput:      $au("audit-auditor-output"),
    analyserOutput:     $au("audit-analyser-output"),
    recommenderOutput:  $au("audit-recommender-output"),
    implementerOutput:  $au("audit-implementer-output"),
    auditorStatus:      $au("audit-auditor-status"),
    analyserStatus:     $au("audit-analyser-status"),
    recommenderStatus:  $au("audit-recommender-status"),
    implementerStatus:  $au("audit-implementer-status"),
    panelAuditor:       $au("audit-panel-auditor"),
    panelAnalyser:      $au("audit-panel-analyser"),
    panelRecommender:   $au("audit-panel-recommender"),
    panelImplementer:   $au("audit-panel-implementer"),
    scoreCard:          $au("audit-score-card"),
    scoreBadge:         $au("audit-score-badge"),
    scoreDetails:       $au("audit-score-details"),
  };
}

let sau = null;
let AUDIT_SESSION_ID = null;
let _auditInitialized = false;

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function initAuditSession() {
  let sid = localStorage.getItem(AUDIT_SESSION_KEY);

  if (!sid) {
    const res = await fetch("/api/seo-audit/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    localStorage.setItem(AUDIT_SESSION_KEY, sid);
  }

  AUDIT_SESSION_ID = sid;

  try {
    const state = await fetch(`/api/seo-audit/state?session_id=${AUDIT_SESSION_ID}`).then((r) => r.json());
    restoreAuditState(state);
  } catch (e) {
    console.warn("Could not restore audit session:", e);
  }
}

function restoreAuditState(state) {
  if (!state) return;

  if (state.url) sau.urlInput.value = state.url;
  if (state.audit_context) sau.contextInput.value = state.audit_context;
  if (state.competitor_urls) {
    state.competitor_urls.forEach((u, i) => {
      if (sau.competitorInputs[i]) sau.competitorInputs[i].value = u;
    });
  }

  if (state.implementation) {
    clearEmptyState(sau.implementerOutput);
    sau.implementerOutput.innerHTML = renderMarkdown(state.implementation);
    setPanelSummary(sau.panelImplementer, '<span>Implementation guide ready</span>');
    showGuideActions();
  }

  if (state.recommendations) {
    clearEmptyState(sau.recommenderOutput);
    sau.recommenderOutput.innerHTML = renderMarkdown(state.recommendations);
    setPanelSummary(sau.panelRecommender, '<span>Recommendations ready</span>');
  }

  if (state.analysis) {
    clearEmptyState(sau.analyserOutput);
    sau.analyserOutput.innerHTML = renderMarkdown(state.analysis);
    setPanelSummary(sau.panelAnalyser, '<span>Analysis complete</span>');
  }

  if (state.audit_data && Object.keys(state.audit_data).length) {
    renderScoreCard(state.audit_data); // also calls setPanelSummary for auditor
  }

  // Reset in-progress stages on reload
  const safeStage = ["auditing", "analysing", "recommending", "implementing"].includes(state.stage)
    ? "idle"
    : state.stage || "idle";
  setAuditStage(safeStage);
}

// ---------------------------------------------------------------------------
// Stage machine
// ---------------------------------------------------------------------------

function setAuditStage(stage) {
  const cfg = AUDIT_STAGES[stage] || AUDIT_STAGES.idle;

  sau.btnStart.disabled       = !cfg.start;
  sau.btnAnalyse.disabled     = !cfg.analyse;
  sau.btnRecommend.disabled   = !cfg.recommend;
  sau.btnImplement.disabled   = !cfg.implement;
  sau.btnCopy.disabled        = !cfg.copy;
  sau.btnDownload.disabled    = !cfg.download;
  sau.btnSaveNotion.disabled  = !cfg.saveNotion;
  sau.btnReset.disabled       = !cfg.reset;

  [sau.auditorStatus, sau.analyserStatus, sau.recommenderStatus, sau.implementerStatus].forEach((el) => {
    el.textContent = "";
    el.classList.remove("running");
  });
  const activePanel = AUDIT_STAGE_ACTIVE_PANEL[stage];
  if (activePanel) {
    const statusEl = $au(`audit-${activePanel}-status`);
    statusEl.textContent = "Running…";
    statusEl.classList.add("running");
  }

  updateAuditPipeline(stage);
  updateNextBar(stage);
  updateAuditAccordion(stage);
}

function updateNextBar(stage) {
  const bar    = document.getElementById("audit-next-bar");
  const msgEl  = document.getElementById("audit-next-bar-msg");
  const btnEl  = document.getElementById("audit-next-bar-btn");
  if (!bar || !msgEl || !btnEl) return;

  const cfg = NEXT_BAR_CONFIG[stage];
  if (cfg) {
    msgEl.innerHTML = cfg.msg;
    btnEl.innerHTML = cfg.cta + ' <span class="btn-arrow">→</span>';
    bar.style.display = "flex";
    requestAnimationFrame(() => bar.classList.add("visible"));
  } else {
    bar.classList.remove("visible");
    setTimeout(() => { if (!bar.classList.contains("visible")) bar.style.display = "none"; }, 260);
  }
}

function updateAuditPipeline(stage) {
  const state = AUDIT_PIPELINE_STATE[stage] || AUDIT_PIPELINE_STATE.idle;

  for (let i = 1; i <= 5; i++) {
    const stepEl = $au(`audit-step-${i}`);
    if (!stepEl) continue;
    const lineEl = i < 5 ? $au(`audit-line-${i}-${i + 1}`) : null;
    stepEl.classList.remove("active", "completed");
    if (lineEl) lineEl.classList.remove("completed");

    if (state.completed.includes(i)) {
      stepEl.classList.add("completed");
      if (lineEl) lineEl.classList.add("completed");
    } else if (state.active === i) {
      stepEl.classList.add("active");
    }
  }
}

// ---------------------------------------------------------------------------
// Score card
// ---------------------------------------------------------------------------

function renderScoreCard(auditData) {
  const score = auditData.technical_score;
  const cms = auditData.cms || "Unknown";
  const tech = auditData.technical_signals || {};
  const issues = auditData.technical_issues || [];

  if (!score && !tech.title) return;

  sau.scoreCard.style.display = "block";

  if (score !== undefined) {
    sau.scoreBadge.textContent = `${score}/10`;
    const scoreNum = parseInt(score, 10);
    sau.scoreBadge.className = "score-badge " + (
      scoreNum >= 8 ? "score-high" :
      scoreNum >= 5 ? "score-mid" : "score-low"
    );
  }

  const lines = [];
  lines.push(`CMS: ${cms}`);
  if (tech.https !== undefined) lines.push(`HTTPS: ${tech.https ? "Yes" : "No"}`);
  if (tech.title) lines.push(`Title: ${tech.title_length} chars`);
  lines.push(`Meta description: ${tech.meta_description ? tech.meta_description_length + " chars" : "Missing"}`);
  lines.push(`H1: ${tech.h1_count || 0} | Schema: ${(tech.schema_types || []).join(", ") || "None"}`);
  if (tech.images_missing_alt > 0) lines.push(`${tech.images_missing_alt} images missing alt text`);

  if (issues.length) {
    const high = issues.filter((i) => i.severity === "high").length;
    const med = issues.filter((i) => i.severity === "medium").length;
    lines.push(`Issues: ${high} high, ${med} medium`);
  }

  sau.scoreDetails.innerHTML = lines.map((l) => `<span>${l}</span>`).join("");

  // Populate accordion summary for the Auditor panel
  if (score !== undefined) {
    const scoreNum2 = parseInt(score, 10);
    const scoreClass = scoreNum2 >= 8 ? 'score-high' : scoreNum2 >= 5 ? '' : 'score-low';
    const high2 = issues.filter((i) => i.severity === 'high').length;
    const med2  = issues.filter((i) => i.severity === 'medium').length;
    const issueTxt = (high2 || med2)
      ? `${high2} high, ${med2} medium issue${high2 + med2 !== 1 ? 's' : ''}`
      : 'No issues found';
    const summaryHtml =
      `<span class="panel-summary-score ${scoreClass}">${score}/10</span>` +
      `<span>${issueTxt}</span>`;
    setPanelSummary(sau.panelAuditor, summaryHtml);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clearEmptyState(el) {
  const empty = el.querySelector(".empty-state");
  if (empty) empty.remove();
}

function appendCursor(el) {
  const cur = document.createElement("span");
  cur.className = "stream-cursor";
  el.appendChild(cur);
  return cur;
}

function showAuditError(msg) {
  const toast = document.getElementById("error-toast");
  toast.textContent = msg;
  toast.classList.add("visible");
  setTimeout(() => toast.classList.remove("visible"), 6000);
}

// ---------------------------------------------------------------------------
// Run Audit
// ---------------------------------------------------------------------------

async function startAudit() {
  const url = sau.urlInput.value.trim();
  const context = sau.contextInput.value.trim();

  if (!url) {
    showAuditError("Please enter a URL to audit.");
    return;
  }

  const competitor_urls = sau.competitorInputs
    .map((el) => el.value.trim())
    .filter(Boolean);

  try {
    const res = await fetch("/api/seo-audit/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: AUDIT_SESSION_ID, url, context, competitor_urls }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Failed to start audit");
    }
  } catch (e) {
    showAuditError(`Failed to start audit: ${e.message}`);
    return;
  }

  // Reset score card
  sau.scoreCard.style.display = "none";
  sau.scoreBadge.textContent = "–";
  sau.scoreBadge.className = "score-badge";
  sau.scoreDetails.innerHTML = "";

  setAuditStage("auditing");
  clearEmptyState(sau.auditorOutput);
  sau.auditorOutput.textContent = "";
  const cursor = appendCursor(sau.auditorOutput);

  const es = new EventSource(`/api/seo-audit/stream/audit?session_id=${AUDIT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      sau.auditorOutput.innerHTML = renderMarkdown(fullText);
      appendCursor(sau.auditorOutput);
    } else if (msg.type === "technical_signals") {
      // Show score card as soon as crawl data arrives (before LLM finishes)
      renderScoreCard({ technical_signals: msg.data, cms: msg.data.cms });
    } else if (msg.type === "audit_data") {
      renderScoreCard(msg.data);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setAuditStage("awaiting_analyse");
      startAnalyse();
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showAuditError(msg.message || "Audit failed");
      setAuditStage("idle");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showAuditError("Stream error during audit");
    setAuditStage("idle");
  };
}

// ---------------------------------------------------------------------------
// Analyse
// ---------------------------------------------------------------------------

async function startAnalyse() {
  try {
    const res = await fetch("/api/seo-audit/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: AUDIT_SESSION_ID }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Failed to start analysis");
    }
  } catch (e) {
    showAuditError(`Failed to start analysis: ${e.message}`);
    return;
  }

  setAuditStage("analysing");
  clearEmptyState(sau.analyserOutput);
  sau.analyserOutput.textContent = "";
  const cursor = appendCursor(sau.analyserOutput);

  const es = new EventSource(`/api/seo-audit/stream/analysis?session_id=${AUDIT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      sau.analyserOutput.innerHTML = renderMarkdown(fullText);
      appendCursor(sau.analyserOutput);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setPanelSummary(sau.panelAnalyser, '<span>Analysis complete</span>');
      setAuditStage("awaiting_recommend");
      startRecommend();
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showAuditError(msg.message || "Analysis failed");
      setAuditStage("awaiting_analyse");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showAuditError("Stream error during analysis");
    setAuditStage("awaiting_analyse");
  };
}

// ---------------------------------------------------------------------------
// Recommend
// ---------------------------------------------------------------------------

async function startRecommend() {
  try {
    const res = await fetch("/api/seo-audit/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: AUDIT_SESSION_ID }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Failed to start recommendations");
    }
  } catch (e) {
    showAuditError(`Failed to start recommendations: ${e.message}`);
    return;
  }

  setAuditStage("recommending");
  clearEmptyState(sau.recommenderOutput);
  sau.recommenderOutput.textContent = "";
  const cursor = appendCursor(sau.recommenderOutput);

  const es = new EventSource(`/api/seo-audit/stream/recommendations?session_id=${AUDIT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      sau.recommenderOutput.innerHTML = renderMarkdown(fullText);
      appendCursor(sau.recommenderOutput);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setPanelSummary(sau.panelRecommender, '<span>Recommendations ready</span>');
      setAuditStage("awaiting_implement");
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showAuditError(msg.message || "Recommendations failed");
      setAuditStage("awaiting_recommend");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showAuditError("Stream error during recommendations");
    setAuditStage("awaiting_recommend");
  };
}

// ---------------------------------------------------------------------------
// Implement
// ---------------------------------------------------------------------------

async function startImplement() {
  try {
    const res = await fetch("/api/seo-audit/implement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: AUDIT_SESSION_ID }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Failed to start implementation");
    }
  } catch (e) {
    showAuditError(`Failed to start implementation: ${e.message}`);
    return;
  }

  setAuditStage("implementing");
  clearEmptyState(sau.implementerOutput);
  sau.implementerOutput.textContent = "";
  const cursor = appendCursor(sau.implementerOutput);

  const es = new EventSource(`/api/seo-audit/stream/implementation?session_id=${AUDIT_SESSION_ID}`);
  let fullText = "";

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      fullText += msg.text;
      cursor.remove();
      sau.implementerOutput.innerHTML = renderMarkdown(fullText);
      appendCursor(sau.implementerOutput);
    } else if (msg.type === "done") {
      es.close();
      cursor.remove();
      setPanelSummary(sau.panelImplementer, '<span>Implementation guide ready</span>');
      showGuideActions();
      setAuditStage("done");
    } else if (msg.type === "error") {
      es.close();
      cursor.remove();
      showAuditError(msg.message || "Implementation guide failed");
      setAuditStage("awaiting_implement");
    }
  };

  es.onerror = () => {
    es.close();
    cursor.remove();
    showAuditError("Stream error during implementation");
    setAuditStage("awaiting_implement");
  };
}

// ---------------------------------------------------------------------------
// Save to Notion
// ---------------------------------------------------------------------------

async function saveToNotion() {
  sau.btnSaveNotion.disabled = true;
  sau.btnSaveNotion.textContent = "Saving…";

  try {
    const res = await fetch("/api/seo-audit/save-to-notion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: AUDIT_SESSION_ID }),
    });
    const data = await res.json();

    if (data.notion_url) {
      sau.btnSaveNotion.textContent = "Saved to Notion ✓";
    } else if (data.code === "notion_not_configured" || !data.error) {
      showNotionConfigPrompt();
      sau.btnSaveNotion.disabled = false;
      sau.btnSaveNotion.textContent = "Save to Notion";
    } else {
      showAuditError(`Notion save failed: ${data.error}`);
      sau.btnSaveNotion.disabled = false;
      sau.btnSaveNotion.textContent = "Save to Notion";
    }
  } catch (e) {
    showAuditError(`Notion save failed: ${e.message}`);
    sau.btnSaveNotion.disabled = false;
    sau.btnSaveNotion.textContent = "Save to Notion";
  }
}

// ---------------------------------------------------------------------------
// Guide actions — copy / download .docx for the implementation guide
// ---------------------------------------------------------------------------

function showGuideActions() {
  const el = document.getElementById('audit-guide-actions');
  if (el) el.classList.add('visible');
}

window.copyImplementerGuide = async function (btn) {
  const text = (sau.implementerOutput.innerText || sau.implementerOutput.textContent || '').trim();
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(function () { btn.textContent = orig; }, 2000);
    }
  } catch (e) {
    showAuditError('Could not copy to clipboard');
  }
};

window.downloadImplementerGuide = function () {
  const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>SEO Implementation Guide</title></head><body>'
    + sau.implementerOutput.innerHTML
    + '</body></html>';
  try {
    const blob = window.htmlDocx ? window.htmlDocx.asBlob(html) : new Blob([html], { type: 'application/msword' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'seo-implementation-guide.' + (window.htmlDocx ? 'docx' : 'doc');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    showAuditError('Could not generate file');
  }
};

// ---------------------------------------------------------------------------
// Copy report
// ---------------------------------------------------------------------------

async function copyReport() {
  const url = sau.urlInput.value || "";
  const auditorText   = sau.auditorOutput.textContent || "";
  const analyserText  = sau.analyserOutput.textContent || "";
  const recommenderText = sau.recommenderOutput.textContent || "";
  const implementerText = sau.implementerOutput.textContent || "";

  const report = [
    `SEO AUDIT REPORT — ${url}`,
    "=".repeat(60),
    "",
    "AUDIT FINDINGS",
    "-".repeat(40),
    auditorText,
    "",
    "ANALYSIS",
    "-".repeat(40),
    analyserText,
    "",
    "RECOMMENDATIONS",
    "-".repeat(40),
    recommenderText,
    "",
    "IMPLEMENTATION GUIDE",
    "-".repeat(40),
    implementerText,
  ].join("\n");

  try {
    await navigator.clipboard.writeText(report);
    sau.btnCopy.textContent = "Copied!";
    setTimeout(() => { sau.btnCopy.textContent = "Copy Report"; }, 2000);
  } catch (e) {
    showAuditError("Could not copy to clipboard");
  }
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

async function resetAudit() {
  await fetch("/api/seo-audit/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: AUDIT_SESSION_ID }),
  });

  sau.urlInput.value = "";
  sau.contextInput.value = "";
  sau.competitorInputs.forEach((el) => { el.value = ""; });

  sau.scoreCard.style.display = "none";
  sau.scoreBadge.textContent = "–";
  sau.scoreBadge.className = "score-badge";
  sau.scoreDetails.innerHTML = "";

  sau.auditorOutput.innerHTML     = '<div class="empty-state">Waiting to audit…</div>';
  sau.analyserOutput.innerHTML    = '<div class="empty-state">Waiting for audit to complete…</div>';
  sau.recommenderOutput.innerHTML = '<div class="empty-state">Waiting for analysis to complete…</div>';
  sau.implementerOutput.innerHTML = '<div class="empty-state">Waiting for recommendations to complete…</div>';

  const guideActionsEl = document.getElementById('audit-guide-actions');
  if (guideActionsEl) guideActionsEl.classList.remove('visible');

  sau.btnSaveNotion.textContent = "Save to Notion";

  setAuditStage("idle");
}

// ---------------------------------------------------------------------------
// Wire buttons
// ---------------------------------------------------------------------------

function wireAuditButtons() {
  sau.btnStart.addEventListener("click", startAudit);
  sau.btnAnalyse.addEventListener("click", startAnalyse);
  sau.btnRecommend.addEventListener("click", startRecommend);
  sau.btnImplement.addEventListener("click", startImplement);
  sau.btnCopy.addEventListener("click", copyReport);
  sau.btnDownload.addEventListener("click", () => {
    window.location.href = `/api/seo-audit/download?session_id=${AUDIT_SESSION_ID}`;
  });
  sau.btnSaveNotion.addEventListener("click", saveToNotion);
  sau.btnReset.addEventListener("click", resetAudit);

  // Next-action bar — delegates to whichever stage action is currently active
  document.getElementById("audit-next-bar-btn")?.addEventListener("click", () => {
    if (!sau.btnAnalyse.disabled)   { startAnalyse();   return; }
    if (!sau.btnRecommend.disabled) { startRecommend(); return; }
    if (!sau.btnImplement.disabled) { startImplement(); return; }
  });
}

// ---------------------------------------------------------------------------
// View mount hook
// ---------------------------------------------------------------------------

function viewDidMount_seoAudit() {
  if (_auditInitialized) return;
  _auditInitialized = true;

  try {
    sau = getAuditUi();
    wireAuditButtons();

    // Wire Review buttons — each opens the drawer for its panel
    [sau.panelAuditor, sau.panelAnalyser, sau.panelRecommender, sau.panelImplementer].forEach((panelEl) => {
      const btn = panelEl.querySelector('.panel-review-btn');
      if (btn) btn.addEventListener('click', () => openPanelDrawer(panelEl));
    });
  } catch (e) {
    console.error("SEO Audit init error:", e);
    _auditInitialized = false; // allow retry on next navigation
    return;
  }
  initAuditSession().catch((e) => showAuditError(`Failed to initialise session: ${e.message}`));
}

window["viewDidMount_seo-audit"] = viewDidMount_seoAudit;
