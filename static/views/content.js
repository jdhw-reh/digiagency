"use strict";

// ---------------------------------------------------------------------------
// Content Team view
// ---------------------------------------------------------------------------

const SESSION_KEY = "agency_content_session";

const STAGES = {
  idle:           { research: true,  plan: false, write: false, save: false, copy: false, reset: false },
  researching:    { research: false, plan: false, write: false, save: false, copy: false, reset: false },
  awaiting_topic: { research: false, plan: true,  write: false, save: false, copy: false, reset: false },
  planning:       { research: false, plan: false, write: false, save: false, copy: false, reset: false },
  awaiting_write: { research: false, plan: false, write: true,  save: false, copy: false, reset: false },
  writing:        { research: false, plan: false, write: false, save: false, copy: false, reset: false },
  done:           { research: true,  plan: false, write: false, save: true,  copy: true,  reset: true  },
};

// Which panel lights up at each stage
const STAGE_ACTIVE_PANEL = {
  researching: "researcher",
  planning:    "planner",
  writing:     "writer",
};

// Pipeline step states per stage
const PIPELINE_STATE = {
  idle:           { active: 1, completed: [] },
  researching:    { active: 1, completed: [] },
  awaiting_topic: { active: 1, completed: [] },
  planning:       { active: 2, completed: [1] },
  awaiting_write: { active: 2, completed: [1] },
  writing:        { active: 3, completed: [1, 2] },
  done:           { active: 3, completed: [1, 2] },
};

// ---------------------------------------------------------------------------
// DOM refs (resolved lazily inside the content view)
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

function getUi() {
  return {
    context:          $("business-context"),
    btnResearch:      $("btn-research"),
    btnPlan:          $("btn-plan"),
    btnWrite:         $("btn-write"),
    btnCopyContent:   $("btn-copy-content"),
    btnSave:          $("btn-save"),
    btnReset:         $("btn-reset"),
    researcherOutput: $("researcher-output"),
    plannerOutput:    $("planner-output"),
    writerOutput:     $("writer-output"),
    researcherStatus: $("researcher-status"),
    plannerStatus:    $("planner-status"),
    writerStatus:     $("writer-status"),
    topicList:        $("topic-list"),
    savedList:        $("saved-list"),
    errorToast:       $("error-toast"),
    wordCount:        $("word-count"),
    panelResearcher:  $("panel-researcher"),
    panelPlanner:     $("panel-planner"),
    panelWriter:      $("panel-writer"),
  };
}

let ui = null;
let SESSION_ID = null;
let _initialized = false;

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function initSession() {
  let sid = localStorage.getItem(SESSION_KEY);

  if (!sid) {
    const res = await fetch("/api/content/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    localStorage.setItem(SESSION_KEY, sid);
  }

  SESSION_ID = sid;

  try {
    const state = await fetch(`/api/content/state?session_id=${SESSION_ID}`).then((r) => r.json());
    restoreState(state);
  } catch (e) {
    console.warn("Could not restore session state:", e);
  }
}

function restoreState(state) {
  if (!state) return;

  if (state.business_context) ui.context.value = state.business_context;

  if (state.article) {
    clearEmptyState(ui.writerOutput);
    ui.writerOutput.textContent = state.article;
    updateWordCount(state.article);
  }

  if (state.brief) {
    clearEmptyState(ui.plannerOutput);
    ui.plannerOutput.textContent = state.brief;
  }

  if (state.topics && state.topics.length > 0) {
    renderTopicList(state.topics, state.selected_topic);
    ui.panelResearcher.classList.add("topics-ready");
    if (state.selected_topic) {
      const idx = state.topics.findIndex((t) => t.title === state.selected_topic.title);
      if (idx >= 0) selectTopicCard(idx);
    }
  }

  if (state.saved_articles && state.saved_articles.length > 0) {
    state.saved_articles.forEach((a) => addSavedArticle(a.title, a.url));
  }

  if (state.notion_url) markSaved();

  // If the server was mid-stream when the window closed, reset to a safe stage
  const safeStage = ["researching", "planning", "writing"].includes(state.stage)
    ? "idle"
    : state.stage || "idle";
  setStage(safeStage);
}

// ---------------------------------------------------------------------------
// Stage machine
// ---------------------------------------------------------------------------

function setStage(stage) {
  const cfg = STAGES[stage] || STAGES.idle;

  ui.btnResearch.disabled = !cfg.research;
  ui.btnPlan.disabled     = !cfg.plan;
  ui.btnWrite.disabled    = !cfg.write;
  ui.btnCopyContent.disabled = !cfg.copy;
  ui.btnSave.disabled        = !cfg.save;
  ui.btnReset.disabled       = !cfg.reset;

  // Clear all status badges and active panel glow
  [ui.researcherStatus, ui.plannerStatus, ui.writerStatus].forEach((el) => {
    el.textContent = "";
    el.classList.remove("running");
  });
  [ui.panelResearcher, ui.panelPlanner, ui.panelWriter].forEach((el) => {
    el.classList.remove("panel--active");
  });

  // Show status badge and glow on the active panel
  const activePanel = STAGE_ACTIVE_PANEL[stage];
  if (activePanel) {
    const statusEl = $(`${activePanel}-status`);
    statusEl.textContent = "Running…";
    statusEl.classList.add("running");
    $(`panel-${activePanel}`).classList.add("panel--active");
  }

  updatePipeline(stage);
}

function updatePipeline(stage) {
  const state = PIPELINE_STATE[stage] || PIPELINE_STATE.idle;

  for (let i = 1; i <= 4; i++) {
    const stepEl = $(`step-${i}`);
    stepEl.classList.remove("active", "completed");

    if (state.completed.includes(i)) {
      stepEl.classList.add("completed");
    } else if (state.active === i) {
      stepEl.classList.add("active");
    }
  }

  for (let i = 1; i <= 3; i++) {
    const lineEl = $(`line-${i}-${i + 1}`);
    if (state.completed.includes(i) && state.completed.includes(i + 1)) {
      lineEl.classList.add("completed");
    } else {
      lineEl.classList.remove("completed");
    }
  }
}

function markSaved() {
  const step4 = $("step-4");
  if (step4) {
    step4.classList.remove("active");
    step4.classList.add("completed");
    $("line-3-4").classList.add("completed");
  }
}

// ---------------------------------------------------------------------------
// SSE helper
// ---------------------------------------------------------------------------

function startSSE(endpoint, { onChunk, onTopics, onDone, onError }) {
  const url = `${endpoint}?session_id=${SESSION_ID}`;
  const es = new EventSource(url);

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk" && onChunk)        onChunk(msg.text);
    else if (msg.type === "topics" && onTopics)  onTopics(msg.data);
    else if (msg.type === "done") { es.close(); if (onDone) onDone(); }
  };

  es.onerror = () => {
    es.close();
    if (onError) onError("Connection to server lost. Please try again.");
  };

  return es;
}

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------

function clearEmptyState(el) {
  const empty = el.querySelector(".empty-state");
  if (empty) empty.remove();
}

function appendToOutput(el, text) {
  clearEmptyState(el);
  // Remove streaming cursor before appending, re-add at end
  const cursor = el.querySelector(".stream-cursor");
  if (cursor) cursor.remove();
  el.textContent += text;
  // Add streaming cursor
  const cur = document.createElement("span");
  cur.className = "stream-cursor";
  el.appendChild(cur);
  el.scrollTop = el.scrollHeight;
}

function finaliseOutput(el) {
  const cursor = el.querySelector(".stream-cursor");
  if (cursor) cursor.remove();
}

function updateWordCount(text) {
  if (!text) { ui.wordCount.textContent = ""; return; }
  const count = text.trim().split(/\s+/).filter(Boolean).length;
  ui.wordCount.textContent = `${count.toLocaleString()} words`;
}

// ---------------------------------------------------------------------------
// Topic list rendering
// ---------------------------------------------------------------------------

function renderTopicList(topics, selectedTopic) {
  ui.topicList.innerHTML = "";

  topics.forEach((topic, i) => {
    const label = document.createElement("label");
    label.className = "topic-option";
    label.dataset.index = i;

    const competitionClass = { low: "tag-low", medium: "tag-medium", high: "tag-high" }[topic.competition] || "tag-medium";

    label.innerHTML = `
      <input type="radio" name="topic" value="${i}" />
      <div class="topic-title">${escapeHtml(topic.title)}</div>
      <div class="topic-meta">
        <span class="tag tag-intent">${escapeHtml(topic.search_intent)}</span>
        <span class="tag ${competitionClass}">${escapeHtml(topic.competition)} competition</span>
        <span class="tag tag-keyword">${escapeHtml(topic.primary_keyword)}</span>
        ${topic.estimated_monthly_searches
          ? `<span class="tag tag-keyword">~${escapeHtml(topic.estimated_monthly_searches)}/mo</span>`
          : ""}
      </div>
      <p class="topic-why">${escapeHtml(topic.why_target)}</p>
    `;

    label.addEventListener("click", () => selectTopicCard(i));

    if (selectedTopic && selectedTopic.title === topic.title) {
      label.classList.add("selected");
      label.querySelector("input").checked = true;
    }

    ui.topicList.appendChild(label);
  });
}

function selectTopicCard(index) {
  document.querySelectorAll(".topic-option").forEach((el, i) => {
    el.classList.toggle("selected", i === index);
    el.querySelector("input").checked = i === index;
  });
}

// ---------------------------------------------------------------------------
// Saved articles
// ---------------------------------------------------------------------------

function addSavedArticle(title, url) {
  const empty = ui.savedList.querySelector(".saved-empty");
  if (empty) empty.remove();

  const li = document.createElement("li");
  li.className = "saved-item";
  li.innerHTML = `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">📄 ${escapeHtml(title)} ↗</a>`;
  ui.savedList.appendChild(li);
}

// ---------------------------------------------------------------------------
// Error toast
// ---------------------------------------------------------------------------

let toastTimer = null;

function showError(message) {
  const toast = $("error-toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 6000);
}

// ---------------------------------------------------------------------------
// HTML escaping
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escapeAttr(str) {
  if (!str) return "#";
  return String(str).replace(/"/g, "%22");
}

// ---------------------------------------------------------------------------
// Button handlers (wired once on first mount)
// ---------------------------------------------------------------------------

function wireButtons() {
  // Discover Topics
  ui.btnResearch.addEventListener("click", async () => {
    const context = ui.context.value.trim();
    if (!context) { showError("Please enter a business context first."); return; }

    await fetch("/api/content/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID }),
    });

    await fetch("/api/content/context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID, context }),
    });

    ui.researcherOutput.innerHTML = '<div class="empty-state">Searching…</div>';
    ui.topicList.innerHTML = "";
    ui.plannerOutput.innerHTML = '<div class="empty-state">Waiting for a topic to be selected…</div>';
    ui.writerOutput.innerHTML = '<div class="empty-state">Waiting for a content brief…</div>';
    ui.panelResearcher.classList.remove("topics-ready");
    ui.wordCount.textContent = "";
    ui.btnSave.innerHTML = '<span class="btn-icon">↑</span> Save to Notion';

    setStage("researching");

    startSSE("/api/content/stream/research", {
      onChunk:  (text) => appendToOutput(ui.researcherOutput, text),
      onTopics: (topics) => {
        renderTopicList(topics, null);
        ui.panelResearcher.classList.add("topics-ready");
      },
      onDone:  () => { finaliseOutput(ui.researcherOutput); setStage("awaiting_topic"); },
      onError: (msg) => { setStage("idle"); showError(msg); },
    });
  });

  // Plan This Topic
  ui.btnPlan.addEventListener("click", async () => {
    const selected = document.querySelector('input[name="topic"]:checked');
    if (!selected) { showError("Please select a topic from the list first."); return; }

    const res = await fetch("/api/content/select-topic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID, topic_index: parseInt(selected.value, 10) }),
    });

    if (!res.ok) { showError("Failed to select topic. Please try again."); return; }

    ui.plannerOutput.innerHTML = "";
    setStage("planning");

    startSSE("/api/content/stream/plan", {
      onChunk: (text) => appendToOutput(ui.plannerOutput, text),
      onDone:  () => { finaliseOutput(ui.plannerOutput); setStage("awaiting_write"); },
      onError: (msg) => { setStage("awaiting_topic"); showError(msg); },
    });
  });

  // Write Article
  ui.btnWrite.addEventListener("click", () => {
    ui.writerOutput.innerHTML = "";
    ui.wordCount.textContent = "";
    setStage("writing");

    let articleText = "";

    startSSE("/api/content/stream/write", {
      onChunk: (text) => {
        appendToOutput(ui.writerOutput, text);
        articleText += text;
        updateWordCount(articleText);
      },
      onDone:  () => { finaliseOutput(ui.writerOutput); setStage("done"); },
      onError: (msg) => { setStage("awaiting_write"); showError(msg); },
    });
  });

  // Copy Content
  ui.btnCopyContent.addEventListener("click", async () => {
    const text = ui.writerOutput.textContent || "";
    try {
      await navigator.clipboard.writeText(text);
      ui.btnCopyContent.textContent = "Copied!";
      setTimeout(() => { ui.btnCopyContent.textContent = "Copy Content"; }, 2000);
    } catch {
      showError("Could not copy to clipboard");
    }
  });

  // Save to Notion
  ui.btnSave.addEventListener("click", async () => {
    ui.btnSave.disabled = true;
    ui.btnSave.innerHTML = '<span class="btn-icon">⏳</span> Saving…';

    try {
      const res = await fetch("/api/content/save-notion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: SESSION_ID }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Unknown error saving to Notion");

      addSavedArticle(data.title, data.url);
      ui.btnSave.innerHTML = '<span class="btn-icon">✓</span> Saved';
      ui.btnReset.disabled = false;
      markSaved();
    } catch (e) {
      ui.btnSave.disabled = false;
      ui.btnSave.innerHTML = '<span class="btn-icon">↑</span> Save to Notion';
      showError(`Notion save failed: ${e.message}`);
    }
  });

  // New Article
  ui.btnReset.addEventListener("click", async () => {
    await fetch("/api/content/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID }),
    });

    ui.researcherOutput.innerHTML = '<div class="empty-state">Waiting to research topics…</div>';
    ui.plannerOutput.innerHTML    = '<div class="empty-state">Waiting for a topic to be selected…</div>';
    ui.writerOutput.innerHTML     = '<div class="empty-state">Waiting for a content brief…</div>';
    ui.topicList.innerHTML = "";
    ui.wordCount.textContent = "";
    ui.panelResearcher.classList.remove("topics-ready");
    ui.btnSave.innerHTML = '<span class="btn-icon">↑</span> Save to Notion';

    setStage("idle");
  });
}

// ---------------------------------------------------------------------------
// View mount hook — called by router on first navigation to #/content
// ---------------------------------------------------------------------------

function viewDidMount_content() {
  if (_initialized) return;
  _initialized = true;

  ui = getUi();
  wireButtons();
  initSession().catch((e) => showError(`Failed to initialise session: ${e.message}`));
}

window.viewDidMount_content = viewDidMount_content;
