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
        gap: 2px;
        padding: 4px 0;
        max-width: 860px;
      }
      .history-item {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        gap: 12px;
        padding: 12px 14px;
        border-radius: var(--radius-s, 8px);
        cursor: pointer;
        border: 1px solid transparent;
        transition: background 0.12s, border-color 0.12s;
        background: var(--bg-card, #fff);
      }
      .history-item:hover {
        background: var(--bg-hover);
        border-color: var(--border);
      }
      .history-item.copied {
        border-color: #10b981;
      }
      .history-badge {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 999px;
        white-space: nowrap;
        background: var(--bg-tag, #f1f5f9);
        color: var(--text-muted);
      }
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
      .history-copy-hint {
        font-size: 11px;
        color: #10b981;
        font-weight: 600;
        opacity: 0;
        transition: opacity 0.2s;
        white-space: nowrap;
      }
      .history-item.copied .history-copy-hint { opacity: 1; }
      .history-item.copied .history-meta { display: none; }
    `;
    document.head.appendChild(style);
  }

  const TOOL_COLORS = {
    "Content Team":       "#6366f1",
    "Social Team":        "#14b8a6",
    "SEO Audit":          "#8b5cf6",
    "Assistant":          "#f59e0b",
    "Video Director":     "#ef4444",
    "On-Page Optimiser":  "#10b981",
  };

  function formatDate(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
        " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function renderHistory(items) {
    const list = document.getElementById("history-list");
    if (!list) return;

    if (!items || items.length === 0) {
      list.innerHTML = `<div class="empty-state">No history yet. Completed outputs from all teams will appear here.</div>`;
      return;
    }

    list.innerHTML = "";
    items.forEach((item) => {
      const color = TOOL_COLORS[item.tool] || "var(--text-muted)";
      const preview = (item.output || "").replace(/\s+/g, " ").trim().slice(0, 120);

      const el = document.createElement("div");
      el.className = "history-item";
      el.innerHTML = `
        <span class="history-badge" style="color:${color}">${item.tool}</span>
        <div class="history-body">
          <div class="history-title">${item.title || "Untitled"}</div>
          <div class="history-preview">${preview}${(item.output || "").length > 120 ? "…" : ""}</div>
        </div>
        <span class="history-meta">${formatDate(item.ts)}</span>
        <span class="history-copy-hint">Copied!</span>
      `;

      el.addEventListener("click", () => {
        navigator.clipboard.writeText(item.output || "").then(() => {
          el.classList.add("copied");
          setTimeout(() => el.classList.remove("copied"), 2000);
        });
      });

      list.appendChild(el);
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
