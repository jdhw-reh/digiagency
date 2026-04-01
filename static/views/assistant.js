"use strict";

// ---------------------------------------------------------------------------
// Personal Assistant view — chat interface
// ---------------------------------------------------------------------------

const ASST_SESSION_KEY = "agency_assistant_session";

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $a = (id) => document.getElementById(id);

function getAsstUi() {
  return {
    messages:    $a("asst-messages"),
    welcome:     $a("asst-welcome"),
    input:       $a("asst-input"),
    btnSend:     $a("asst-btn-send"),
    btnClear:    $a("asst-btn-clear"),
    btnAttach:   $a("asst-btn-attach"),
    fileInput:   $a("asst-file-input"),
    fileQueue:   $a("asst-file-queue"),
  };
}

let aui = null;
let ASST_SESSION_ID = null;
let _asstInitialized = false;
let _asstIsResponding = false;

// Pending file attachments: [{uri, mime_type, display_name}]
let _pendingFiles = [];

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function initAsstSession() {
  let sid = localStorage.getItem(ASST_SESSION_KEY);

  if (!sid) {
    const res = await fetch("/api/assistant/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: window.getAppUserId ? window.getAppUserId() : "" }),
    });
    const data = await res.json();
    sid = data.session_id;
    localStorage.setItem(ASST_SESSION_KEY, sid);
  }

  ASST_SESSION_ID = sid;

  try {
    const state = await fetch(`/api/assistant/state?session_id=${ASST_SESSION_ID}`).then((r) => r.json());
    restoreAsstState(state);
  } catch (e) {
    console.warn("Could not restore assistant session state:", e);
  }
}

function restoreAsstState(state) {
  if (!state || !state.conversation_history) return;

  const history = state.conversation_history;
  if (history.length === 0) return;

  history.forEach((msg) => {
    if (msg.role === "user") {
      appendUserMessage(msg.content);
    } else if (msg.role === "model") {
      appendAssistantMessage(msg.content);
    }
  });
}

// ---------------------------------------------------------------------------
// File attachment handling
// ---------------------------------------------------------------------------

function renderFileQueue() {
  aui.fileQueue.innerHTML = "";

  if (_pendingFiles.length === 0) {
    aui.fileQueue.style.display = "none";
    return;
  }

  aui.fileQueue.style.display = "flex";

  _pendingFiles.forEach((file, index) => {
    const chip = document.createElement("div");
    chip.className = "file-chip";
    chip.innerHTML = `
      <span class="file-chip__name">${escapeHtml(file.display_name)}</span>
      <button class="file-chip__remove" data-index="${index}" title="Remove">×</button>
    `;
    aui.fileQueue.appendChild(chip);
  });

  aui.fileQueue.querySelectorAll(".file-chip__remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const idx = parseInt(e.currentTarget.dataset.index, 10);
      _pendingFiles.splice(idx, 1);
      renderFileQueue();
    });
  });
}

async function handleFileSelection(files) {
  const remaining = 3 - _pendingFiles.length;
  if (remaining <= 0) {
    showAsstError("Maximum 3 files per message.");
    return;
  }

  const toUpload = Array.from(files).slice(0, remaining);
  // Disable attach button during upload
  aui.btnAttach.disabled = true;
  aui.btnAttach.textContent = "⏳";

  for (const file of toUpload) {
    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch("/api/assistant/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        showAsstError(data.error || "Upload failed.");
        continue;
      }

      _pendingFiles.push({
        uri: data.uri,
        mime_type: data.mime_type,
        display_name: data.display_name,
      });
    } catch (e) {
      showAsstError(`Upload failed: ${e.message}`);
    }
  }

  aui.btnAttach.disabled = false;
  aui.btnAttach.textContent = "📎";
  renderFileQueue();

  // Reset the file input so the same file can be re-selected if removed
  aui.fileInput.value = "";
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

function hideWelcome() {
  if (aui.welcome) {
    aui.welcome.style.display = "none";
  }
}

function appendUserMessage(text, attachments = []) {
  hideWelcome();

  const div = document.createElement("div");
  div.className = "chat-message chat-message--user";

  let bubbleHtml = `<div class="message-bubble">${escapeHtml(text)}`;
  if (attachments.length > 0) {
    bubbleHtml += `<div class="message-attachments">`;
    attachments.forEach((a) => {
      bubbleHtml += `<span class="attachment-chip">📎 ${escapeHtml(a.display_name)}</span>`;
    });
    bubbleHtml += `</div>`;
  }
  bubbleHtml += `</div>`;

  div.innerHTML = bubbleHtml;
  aui.messages.appendChild(div);
  scrollToBottom();
  return div;
}

function appendAssistantMessage(text) {
  hideWelcome();

  const div = document.createElement("div");
  div.className = "chat-message chat-message--assistant";
  div.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`;
  aui.messages.appendChild(div);
  scrollToBottom();
  return div;
}

function createAssistantBubble() {
  hideWelcome();

  const div = document.createElement("div");
  div.className = "chat-message chat-message--assistant";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  const cursor = document.createElement("span");
  cursor.className = "stream-cursor";
  bubble.appendChild(cursor);

  div.appendChild(bubble);
  aui.messages.appendChild(div);
  scrollToBottom();
  return bubble;
}

function scrollToBottom() {
  aui.messages.scrollTop = aui.messages.scrollHeight;
}

// ---------------------------------------------------------------------------
// Send message flow
// ---------------------------------------------------------------------------

async function sendMessage() {
  const text = aui.input.value.trim();
  if (!text || _asstIsResponding) return;

  _asstIsResponding = true;
  aui.btnSend.disabled = true;
  aui.input.disabled = true;
  aui.btnAttach.disabled = true;
  aui.input.value = "";
  resetInputHeight();

  // Capture attachments and clear the queue
  const attachments = [..._pendingFiles];
  _pendingFiles = [];
  renderFileQueue();

  // Render user message immediately (with attachment chips)
  appendUserMessage(text, attachments);

  // POST message + file refs to server
  try {
    const res = await fetch("/api/assistant/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: ASST_SESSION_ID,
        message: text,
        file_refs: attachments,
      }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Failed to send message");
    }
  } catch (e) {
    showAsstError(`Failed to send message: ${e.message}`);
    _asstIsResponding = false;
    aui.btnSend.disabled = false;
    aui.input.disabled = false;
    aui.btnAttach.disabled = false;
    return;
  }

  // Open SSE stream for the response
  const bubble = createAssistantBubble();
  let responseText = "";

  const url = `/api/assistant/stream/response?session_id=${ASST_SESSION_ID}`;
  const es = new EventSource(url);

  es.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "chunk") {
      responseText += msg.text;
      const cursor = bubble.querySelector(".stream-cursor");
      if (cursor) cursor.remove();
      bubble.textContent = responseText;
      const cur = document.createElement("span");
      cur.className = "stream-cursor";
      bubble.appendChild(cur);
      scrollToBottom();
    } else if (msg.type === "done") {
      es.close();
      const cursor = bubble.querySelector(".stream-cursor");
      if (cursor) cursor.remove();
      _asstIsResponding = false;
      aui.btnSend.disabled = false;
      aui.input.disabled = false;
      aui.btnAttach.disabled = false;
      aui.input.focus();
    }
  };

  es.onerror = () => {
    es.close();
    const cursor = bubble.querySelector(".stream-cursor");
    if (cursor) cursor.remove();
    if (!responseText) {
      bubble.textContent = "Something went wrong. Please try again.";
      bubble.style.color = "var(--danger)";
    }
    _asstIsResponding = false;
    aui.btnSend.disabled = false;
    aui.input.disabled = false;
    aui.btnAttach.disabled = false;
  };
}

// ---------------------------------------------------------------------------
// Auto-expand textarea
// ---------------------------------------------------------------------------

function resetInputHeight() {
  aui.input.style.height = "auto";
}

function autoExpand(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

// ---------------------------------------------------------------------------
// Error toast
// ---------------------------------------------------------------------------

function showAsstError(message) {
  const toast = document.getElementById("error-toast");
  toast.textContent = message;
  toast.classList.add("visible");
  setTimeout(() => toast.classList.remove("visible"), 6000);
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

// ---------------------------------------------------------------------------
// Wire buttons + input
// ---------------------------------------------------------------------------

function wireAsstButtons() {
  // Send button
  aui.btnSend.addEventListener("click", sendMessage);

  // Enter to send, Shift+Enter for newline
  aui.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-expand textarea
  aui.input.addEventListener("input", () => autoExpand(aui.input));

  // Attach button — open file picker
  aui.btnAttach.addEventListener("click", () => {
    if (_pendingFiles.length >= 3) {
      showAsstError("Maximum 3 files per message.");
      return;
    }
    aui.fileInput.click();
  });

  // File input change
  aui.fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelection(e.target.files);
    }
  });

  // Clear conversation
  aui.btnClear.addEventListener("click", async () => {
    await fetch("/api/assistant/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: ASST_SESSION_ID }),
    });

    // Clear pending files
    _pendingFiles = [];
    renderFileQueue();

    aui.messages.innerHTML = "";
    const welcome = document.createElement("div");
    welcome.className = "chat-welcome";
    welcome.id = "asst-welcome";
    welcome.innerHTML = `
      <div class="chat-welcome-icon">◈</div>
      <p>What can I help you with today?</p>
    `;
    aui.messages.appendChild(welcome);
    aui.welcome = welcome;
  });

  // Quick action pills
  document.querySelectorAll(".quick-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      const prompt = pill.dataset.prompt || "";
      aui.input.value = prompt;
      autoExpand(aui.input);
      aui.input.focus();
      aui.input.selectionStart = aui.input.selectionEnd = aui.input.value.length;
    });
  });
}

// ---------------------------------------------------------------------------
// View mount hook
// ---------------------------------------------------------------------------

function viewDidMount_assistant() {
  if (_asstInitialized) return;
  _asstInitialized = true;

  aui = getAsstUi();
  wireAsstButtons();
  initAsstSession().catch((e) => showAsstError(`Failed to initialise session: ${e.message}`));
}

window.viewDidMount_assistant = viewDidMount_assistant;
