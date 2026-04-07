"use strict";

// ---------------------------------------------------------------------------
// Video Director view
// ---------------------------------------------------------------------------

const VIDEO_SESSION_KEY  = "agency_video_session";
const PENDING_VIDEO_KEY  = "pendingVideoScript";   // sessionStorage handoff from social team

let _videoInitialized = false;
let _videoActiveES    = null;
let vui               = null;

// ---------------------------------------------------------------------------
// UI element references
// ---------------------------------------------------------------------------

function getVideoUi() {
  return {
    briefInput:      document.getElementById("video-brief-input"),
    platformSelect:  document.getElementById("video-platform-select"),
    durationInput:   document.getElementById("video-duration-input"),
    btnDirect:       document.getElementById("video-btn-direct"),
    btnCopyPrompts:  document.getElementById("video-btn-copy-prompts"),
    btnSave:         document.getElementById("video-btn-save"),
    btnReset:        document.getElementById("video-btn-reset"),
    streamOutput:    document.getElementById("video-stream-output"),
    conceptCard:     document.getElementById("video-concept-card"),
    shotsContainer:  document.getElementById("video-shots-container"),
    directorStatus:  document.getElementById("video-director-status"),
    shotCount:       document.getElementById("video-shot-count"),
    savedList:       document.getElementById("video-saved-list"),
  };
}

// ---------------------------------------------------------------------------
// Stage machine
// ---------------------------------------------------------------------------

const VIDEO_STAGE_CONFIG = {
  idle:      { direct: true,  copy: false, save: false, reset: false },
  directing: { direct: false, copy: false, save: false, reset: false },
  done:      { direct: true,  copy: true,  save: true,  reset: true  },
};

function setVideoStage(stage) {
  const cfg = VIDEO_STAGE_CONFIG[stage] || VIDEO_STAGE_CONFIG.idle;
  vui.btnDirect.disabled        = !cfg.direct;
  vui.btnCopyPrompts.disabled   = !cfg.copy;
  vui.btnCopyPrompts.style.display = cfg.copy ? "" : "none";
  vui.btnSave.disabled          = !cfg.save;
  vui.btnReset.disabled         = !cfg.reset;

  vui.directorStatus.textContent =
    stage === "directing" ? "Working…" :
    stage === "done"      ? "Done"     : "";
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

function getVideoSessionId() {
  return localStorage.getItem(VIDEO_SESSION_KEY);
}

function setVideoSessionId(sid) {
  localStorage.setItem(VIDEO_SESSION_KEY, sid);
}

async function initVideoSession() {
  let sid = getVideoSessionId();
  if (!sid) {
    const res  = await fetch("/api/video/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    setVideoSessionId(sid);
  }
  const stateRes = await fetch(`/api/video/state?session_id=${sid}`);
  const state    = await stateRes.json();
  restoreVideoState(state);
}

function restoreVideoState(state) {
  if (state.brief)    vui.briefInput.value = state.brief;
  if (state.platform) {
    const opt = [...vui.platformSelect.options].find(o => o.value === state.platform);
    if (opt) vui.platformSelect.value = state.platform;
  }
  if (state.duration) vui.durationInput.value = state.duration;

  if (state.stage === "done" && state.shots && state.shots.length) {
    renderConceptCard(state.concept || {});
    renderShotCards(state.shots);
    setVideoStage("done");
  } else if (state.stage === "directing") {
    // In-progress on reload — reset to idle so user can retry
    setVideoStage("idle");
  } else {
    setVideoStage(state.stage || "idle");
  }

  if (state.saved_briefs && state.saved_briefs.length) {
    state.saved_briefs.forEach((url, i) => addSavedBrief(url, i + 1));
  }
}

// ---------------------------------------------------------------------------
// SSE streaming helper
// ---------------------------------------------------------------------------

function startVideoSSE(url, { onChunk, onShots, onSaved, onDone, onError }) {
  if (_videoActiveES) {
    _videoActiveES.close();
    _videoActiveES = null;
  }

  const es = new EventSource(url);
  _videoActiveES = es;

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      onChunk && onChunk(msg.text || "");
    } else if (msg.type === "shots") {
      onShots && onShots(msg.data || {});
    } else if (msg.type === "saved") {
      onSaved && onSaved(msg.url || "");
    } else if (msg.type === "done") {
      es.close();
      _videoActiveES = null;
      onDone && onDone();
    }
  };

  es.onerror = (err) => {
    es.close();
    _videoActiveES = null;
    onError && onError(err);
  };
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------

function escapeHtmlVideo(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderConceptCard(concept) {
  if (!concept || !concept.title) {
    vui.conceptCard.style.display = "none";
    return;
  }

  vui.conceptCard.innerHTML = `
    <div class="concept-card-title">${escapeHtmlVideo(concept.title)}</div>
    <div class="concept-field">
      <label>Platform</label>
      <span>${escapeHtmlVideo(concept.platform || "")}</span>
    </div>
    <div class="concept-field">
      <label>Duration</label>
      <span>${escapeHtmlVideo(concept.duration || "")}</span>
    </div>
    <div class="concept-field">
      <label>Visual Style</label>
      <span>${escapeHtmlVideo(concept.visual_style || "")}</span>
    </div>
    <div class="concept-field">
      <label>Audio Mood</label>
      <span>${escapeHtmlVideo(concept.audio_mood || "")}</span>
    </div>
    <div class="concept-field concept-hook">
      <label>Hook Strategy</label>
      <span>${escapeHtmlVideo(concept.hook_strategy || "")}</span>
    </div>
  `;
  vui.conceptCard.style.display = "grid";
}

function renderShotCards(shots) {
  vui.shotsContainer.innerHTML = "";

  shots.forEach((shot) => {
    const card = document.createElement("div");
    card.className = "shot-card";
    card.innerHTML = `
      <div class="shot-card-header">
        <span class="shot-number">Shot ${escapeHtmlVideo(String(shot.id))}</span>
        <span class="shot-duration-badge">${escapeHtmlVideo(shot.duration || "")}</span>
      </div>
      <div class="shot-field shot-field--runway">
        <label>Runway Gen-4 Prompt</label>
        <div class="runway-prompt-text">${escapeHtmlVideo(shot.runway_prompt || "")}</div>
        <button class="btn-copy-prompt">Copy Prompt</button>
      </div>
      <div class="shot-field">
        <label>Camera</label>
        <div class="shot-field-text">${escapeHtmlVideo(shot.camera || "")}</div>
      </div>
      <div class="shot-field">
        <label>On-Screen Text</label>
        <div class="shot-field-text">${escapeHtmlVideo(shot.on_screen_text || "None")}</div>
      </div>
      <div class="shot-field">
        <label>B-Roll Note</label>
        <div class="shot-field-text">${escapeHtmlVideo(shot.broll_note || "None")}</div>
      </div>
    `;

    const copyBtn = card.querySelector(".btn-copy-prompt");
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(shot.runway_prompt || "");
        copyBtn.textContent = "Copied!";
        copyBtn.classList.add("copied");
        setTimeout(() => {
          copyBtn.textContent = "Copy Prompt";
          copyBtn.classList.remove("copied");
        }, 2000);
      } catch {
        copyBtn.textContent = "Error";
        setTimeout(() => { copyBtn.textContent = "Copy Prompt"; }, 1500);
      }
    });

    vui.shotsContainer.appendChild(card);
  });

  vui.shotCount.textContent = shots.length ? `${shots.length} shot${shots.length !== 1 ? "s" : ""}` : "";
}

// ---------------------------------------------------------------------------
// Saved briefs footer
// ---------------------------------------------------------------------------

function addSavedBrief(url, index) {
  const empty = vui.savedList.querySelector(".saved-empty");
  if (empty) empty.remove();

  const li = document.createElement("li");
  li.className = "saved-item";
  li.innerHTML = `<a href="${escapeHtmlVideo(url)}" target="_blank" rel="noopener">📄 Video Brief #${index} ↗</a>`;
  vui.savedList.appendChild(li);
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

async function handleDirectClick() {
  const brief    = vui.briefInput.value.trim();
  const platform = vui.platformSelect.value;
  const duration = vui.durationInput.value || "30";

  if (!brief) {
    showVideoError("Please enter a brief before directing.");
    return;
  }

  let sid = getVideoSessionId();
  if (!sid) {
    const res  = await fetch("/api/video/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    setVideoSessionId(sid);
  }

  // Save brief to session
  await fetch("/api/video/brief", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sid, brief, platform, duration }),
  });

  // Reset output areas
  vui.streamOutput.innerHTML = "";
  vui.conceptCard.style.display = "none";
  vui.shotsContainer.innerHTML = "";
  vui.shotCount.textContent = "";

  setVideoStage("directing");

  let streamBuffer = "";

  startVideoSSE(`/api/video/stream/direct?session_id=${sid}`, {
    onChunk(text) {
      streamBuffer += text;
      vui.streamOutput.textContent = streamBuffer;
      vui.streamOutput.scrollTop = vui.streamOutput.scrollHeight;
    },
    onShots(data) {
      renderConceptCard(data.concept || {});
      renderShotCards(data.shots || []);
    },
    onSaved(url) {
      const savedCount = vui.savedList.querySelectorAll(".saved-item").length + 1;
      addSavedBrief(url, savedCount);
    },
    onDone() {
      setVideoStage("done");
    },
    onError() {
      setVideoStage("idle");
      showVideoError("The Director encountered an error. Please try again.");
    },
  });
}

async function handleSaveClick() {
  const sid = getVideoSessionId();
  vui.btnSave.disabled = true;
  vui.btnSave.textContent = "Saving…";

  try {
    const res  = await fetch("/api/video/save-notion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid }),
    });
    const data = await res.json();

    if (data.error) {
      showVideoError(`Notion save failed: ${data.error}`);
      vui.btnSave.textContent = "↑ Save to Notion";
      vui.btnSave.disabled = false;
      return;
    }

    const savedCount = vui.savedList.querySelectorAll(".saved-item").length + 1;
    addSavedBrief(data.url, savedCount);
    vui.btnSave.textContent = "Saved ✓";
    setTimeout(() => {
      vui.btnSave.textContent = "↑ Save to Notion";
      vui.btnSave.disabled = false;
    }, 2500);
  } catch {
    showVideoError("Could not reach the server. Please try again.");
    vui.btnSave.textContent = "↑ Save to Notion";
    vui.btnSave.disabled = false;
  }
}

async function handleResetClick() {
  const sid = getVideoSessionId();
  await fetch("/api/video/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sid }),
  });

  vui.briefInput.value = "";
  vui.durationInput.value = "";
  vui.streamOutput.innerHTML = '<div class="empty-state">Waiting for a brief…</div>';
  vui.conceptCard.style.display = "none";
  vui.shotsContainer.innerHTML = "";
  vui.shotCount.textContent = "";
  vui.directorStatus.textContent = "";
  setVideoStage("idle");
}

// ---------------------------------------------------------------------------
// Error toast
// ---------------------------------------------------------------------------

function showVideoError(message) {
  const toast = document.getElementById("error-toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("visible");
  setTimeout(() => toast.classList.remove("visible"), 6000);
}

// ---------------------------------------------------------------------------
// Mount / unmount hooks (called by router)
// ---------------------------------------------------------------------------

function viewDidMount_video() {
  if (_videoInitialized) return;
  _videoInitialized = true;

  vui = getVideoUi();

  // Wire buttons
  vui.btnDirect.addEventListener("click", handleDirectClick);
  vui.btnCopyPrompts.addEventListener("click", async () => {
    const promptEls = vui.shotsContainer.querySelectorAll(".runway-prompt-text");
    const lines = [];
    promptEls.forEach((el, i) => {
      lines.push(`Shot ${i + 1}: ${el.textContent.trim()}`);
    });
    try {
      await navigator.clipboard.writeText(lines.join("\n\n"));
      vui.btnCopyPrompts.textContent = "Copied!";
      setTimeout(() => { vui.btnCopyPrompts.textContent = "Copy All Prompts"; }, 2000);
    } catch {
      showVideoError("Could not copy to clipboard");
    }
  });
  vui.btnSave.addEventListener("click", handleSaveClick);
  vui.btnReset.addEventListener("click", handleResetClick);

  // Check for handoff from social team
  try {
    const pending = sessionStorage.getItem(PENDING_VIDEO_KEY);
    if (pending) {
      const { content, platform } = JSON.parse(pending);
      sessionStorage.removeItem(PENDING_VIDEO_KEY);
      if (content) vui.briefInput.value = content;
      if (platform) {
        const opt = [...vui.platformSelect.options].find(
          o => o.value === platform || o.value.startsWith(platform)
        );
        if (opt) vui.platformSelect.value = opt.value;
      }
    }
  } catch { /* fall through to blank state */ }

  initVideoSession();
}

function viewWillUnmount_video() {
  if (_videoActiveES) {
    _videoActiveES.close();
    _videoActiveES = null;
  }
}

window.viewDidMount_video    = viewDidMount_video;
window.viewWillUnmount_video = viewWillUnmount_video;
