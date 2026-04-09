"use strict";

// ---------------------------------------------------------------------------
// History view — fetches /api/history and renders a clickable list
// ---------------------------------------------------------------------------

(function () {
  // Inject styles once
  const STYLE_ID = "history-view-styles";
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .history-list {
        display: flex;
        flex-direction: column;
        gap: 1px;
        padding: 4px 0;
        max-width: 860px;
      }
      .history-date-group {
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.09em;
        padding: 16px 14px 6px;
      }
      .history-date-group:first-child { padding-top: 4px; }
      .history-item {
        display: grid;
        grid-template-columns: auto 1fr auto auto auto;
        align-items: center;
        gap: 12px;
        padding: 13px 14px;
        border-radius: var(--radius-s, 8px);
        cursor: pointer;
        border: 1px solid transparent;
        transition: background 0.12s, border-color 0.12s;
        background: var(--bg-surface);
      }
      .history-item:hover {
        background: var(--bg-hover);
        border-color: var(--border);
      }
      .history-badge {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 999px;
        white-space: nowrap;
      }
      .history-badge[data-team="content"]    { background: rgba(99,102,241,0.12);  color: #6366f1; }
      .history-badge[data-team="social"]     { background: rgba(20,184,166,0.12);  color: #14b8a6; }
      .history-badge[data-team="seo_audit"]  { background: rgba(139,92,246,0.12); color: #8b5cf6; }
      .history-badge[data-team="assistant"]  { background: rgba(245,158,11,0.12);  color: #d97706; }
      .history-badge[data-team="video"]      { background: rgba(239,68,68,0.12);   color: #ef4444; }
      .history-badge[data-team="on_page_opt"]{ background: rgba(16,185,129,0.12);  color: #10b981; }
      .history-badge[data-team="unknown"]    { background: var(--bg-raised); color: var(--text-muted); }
      .history-body {
        min-width: 0;
      }
      .history-title {
        font-size: 13.5px;
        font-weight: 500;
        color: var(--text-body);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .history-preview {
        font-size: 12px;
        color: var(--text-muted);
        margin-top: 2px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .history-meta {
        font-size: 11px;
        color: var(--text-muted);
        white-space: nowrap;
      }
      .history-view-hint {
        font-size: 11px;
        color: var(--text-muted);
        opacity: 0.55;
        white-space: nowrap;
      }
      .history-item:hover .history-view-hint {
        opacity: 1;
      }
      .history-delete-btn {
        background: none;
        border: none;
        cursor: pointer;
        color: var(--text-muted);
        font-size: 14px;
        line-height: 1;
        padding: 2px 4px;
        border-radius: 4px;
        opacity: 0;
        transition: opacity 0.15s, color 0.15s;
      }
      .history-item:hover .history-delete-btn {
        opacity: 1;
      }
      .history-delete-btn:hover {
        color: #ef4444;
      }

      /* Modal */
      .history-modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.6);
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
      }
      .history-modal {
        background: var(--bg-surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        width: 100%;
        max-width: 740px;
        max-height: 80vh;
        display: flex;
        flex-direction: column;
        box-shadow: 0 24px 48px rgba(0,0,0,0.4);
      }
      .history-modal-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 16px 20px;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
      }
      .history-modal-tool {
        font-size: 12px;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 999px;
      }
      .history-modal-tool[data-team="content"]    { background: rgba(99,102,241,0.12);  color: #6366f1; }
      .history-modal-tool[data-team="social"]     { background: rgba(20,184,166,0.12);  color: #14b8a6; }
      .history-modal-tool[data-team="seo_audit"]  { background: rgba(139,92,246,0.12); color: #8b5cf6; }
      .history-modal-tool[data-team="assistant"]  { background: rgba(245,158,11,0.12);  color: #d97706; }
      .history-modal-tool[data-team="video"]      { background: rgba(239,68,68,0.12);   color: #ef4444; }
      .history-modal-tool[data-team="on_page_opt"]{ background: rgba(16,185,129,0.12);  color: #10b981; }
      .history-modal-tool[data-team="unknown"]    { background: var(--bg-raised); color: var(--text-muted); }
      .history-modal-ts {
        font-size: 12px;
        color: var(--text-muted);
        margin-left: auto;
      }
      .history-modal-body {
        overflow-y: auto;
        padding: 20px 24px;
        flex: 1;
        color: var(--text-body);
        font-size: 14px;
        line-height: 1.7;
      }
      .history-modal-body h1,
      .history-modal-body h2,
      .history-modal-body h3 {
        color: var(--text-body);
        margin: 1.2em 0 0.4em;
      }
      .history-modal-body p { margin: 0 0 0.8em; }
      .history-modal-body ul,
      .history-modal-body ol { padding-left: 1.4em; margin: 0 0 0.8em; }
      .history-modal-body code {
        background: var(--bg-hover);
        padding: 1px 5px;
        border-radius: 4px;
        font-size: 12.5px;
      }
      .history-modal-body pre code {
        background: none;
        padding: 0;
      }
      .history-modal-body pre {
        background: var(--bg-hover);
        padding: 12px 16px;
        border-radius: 8px;
        overflow-x: auto;
        margin: 0 0 0.8em;
      }
      .history-modal-footer {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
        padding: 14px 20px;
        border-top: 1px solid var(--border);
        flex-shrink: 0;
      }
      .history-modal-btn {
        padding: 7px 18px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: opacity 0.15s;
      }
      .history-modal-btn:hover { opacity: 0.85; }
      .history-modal-btn.primary {
        background: var(--accent);
        color: #fff;
      }
      .history-modal-btn.secondary {
        background: var(--bg-hover);
        color: var(--text-body);
        border: 1px solid var(--border);
      }
    `;
    document.head.appendChild(style);
  }

  const TOOL_TEAM_KEY = {
    "Content Team":       "content",
    "Social Team":        "social",
    "SEO Audit":          "seo_audit",
    "Assistant":          "assistant",
    "Video Director":     "video",
    "On-Page Optimiser":  "on_page_opt",
  };

  function getTeamKey(toolName) {
    return TOOL_TEAM_KEY[toolName] || "unknown";
  }

  function getDateBucket(isoStr) {
    const now = new Date();
    const d = new Date(isoStr);
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfYesterday = new Date(startOfToday - 86400000);
    const startOfWeek = new Date(startOfToday - 6 * 86400000);
    if (d >= startOfToday)     return "Today";
    if (d >= startOfYesterday) return "Yesterday";
    if (d >= startOfWeek)      return "This week";
    return "Earlier";
  }

  function formatDate(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
        " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function openModal(item) {
    const teamKey = getTeamKey(item.tool);

    const backdrop = document.createElement("div");
    backdrop.className = "history-modal-backdrop";

    const modal = document.createElement("div");
    modal.className = "history-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    const header = document.createElement("div");
    header.className = "history-modal-header";
    header.innerHTML = `
      <span class="history-modal-tool" data-team="${teamKey}">${item.tool}</span>
      <span class="history-modal-ts">${formatDate(item.ts)}</span>
    `;

    const body = document.createElement("div");
    body.className = "history-modal-body";
    body.innerHTML = (typeof renderMarkdown === "function")
      ? renderMarkdown(item.output || "")
      : (item.output || "").replace(/\n/g, "<br>");

    const footer = document.createElement("div");
    footer.className = "history-modal-footer";

    const copyBtn = document.createElement("button");
    copyBtn.className = "history-modal-btn primary";
    copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(item.output || "").then(() => {
        copyBtn.textContent = "Copied!";
        setTimeout(() => { copyBtn.textContent = "Copy"; }, 2000);
      });
    });

    const closeBtn = document.createElement("button");
    closeBtn.className = "history-modal-btn secondary";
    closeBtn.textContent = "Close";
    closeBtn.addEventListener("click", () => backdrop.remove());

    footer.appendChild(copyBtn);
    footer.appendChild(closeBtn);
    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(footer);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) backdrop.remove();
    });

    const onKey = (e) => {
      if (e.key === "Escape") { backdrop.remove(); document.removeEventListener("keydown", onKey); }
    };
    document.addEventListener("keydown", onKey);
  }

  function renderHistory(items) {
    const list = document.getElementById("history-list");
    if (!list) return;

    if (!items || items.length === 0) {
      list.innerHTML = `<div class="empty-state">No history yet. Completed outputs from all teams will appear here.</div>`;
      return;
    }

    list.innerHTML = "";

    // Group items into date buckets preserving original order
    const BUCKET_ORDER = ["Today", "Yesterday", "This week", "Earlier"];
    const buckets = { "Today": [], "Yesterday": [], "This week": [], "Earlier": [] };
    items.forEach((item) => buckets[getDateBucket(item.ts)].push(item));

    BUCKET_ORDER.forEach((bucket) => {
      if (buckets[bucket].length === 0) return;

      const groupEl = document.createElement("div");
      groupEl.className = "history-date-group";
      groupEl.textContent = bucket;
      list.appendChild(groupEl);

      buckets[bucket].forEach((item) => {
        const teamKey = getTeamKey(item.tool);
        const preview = (item.output || "").replace(/\s+/g, " ").trim().slice(0, 120);

        const el = document.createElement("div");
        el.className = "history-item";
        el.innerHTML = `
          <span class="history-badge" data-team="${teamKey}">${item.tool}</span>
          <div class="history-body">
            <div class="history-title">${item.title || "Untitled"}</div>
            <div class="history-preview">${preview}${(item.output || "").length > 120 ? "…" : ""}</div>
          </div>
          <span class="history-view-hint">click to view</span>
          <span class="history-meta">${formatDate(item.ts)}</span>
          <button class="history-delete-btn" title="Delete" aria-label="Delete history item">✕</button>
        `;

        el.addEventListener("click", (e) => {
          if (e.target.classList.contains("history-delete-btn")) return;
          openModal(item);
        });

        el.querySelector(".history-delete-btn").addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            const res = await fetch(`/api/history/${item.id}`, { method: "DELETE" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            el.remove();
            // Remove the group header if it's now empty
            const remaining = groupEl.nextElementSibling;
            if (!remaining || remaining.classList.contains("history-date-group")) {
              groupEl.remove();
            }
            if (list.children.length === 0) {
              list.innerHTML = `<div class="empty-state">No history yet. Completed outputs from all teams will appear here.</div>`;
            }
          } catch (err) {
            console.error("Failed to delete history item", err);
          }
        });

        list.appendChild(el);
      });
    });
  }

  async function loadHistory() {
    const list = document.getElementById("history-list");
    if (!list) return;
    list.innerHTML = `<div class="empty-state">Loading…</div>`;
    try {
      const res = await fetch("/api/history");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const items = await res.json();
      renderHistory(items);
    } catch (err) {
      list.innerHTML = `<div class="empty-state">Failed to load history.</div>`;
    }
  }

  window.viewDidMount_history = loadHistory;
})();
