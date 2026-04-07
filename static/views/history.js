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
        grid-template-columns: auto 1fr auto auto;
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
        background: var(--bg-card, #1e1e2e);
        border: 1px solid var(--border, #2d2d3d);
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
        border-bottom: 1px solid var(--border, #2d2d3d);
        flex-shrink: 0;
      }
      .history-modal-tool {
        font-size: 12px;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 999px;
        background: var(--bg-tag, #2d2d3d);
      }
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
        background: var(--bg-hover, #2d2d3d);
        padding: 1px 5px;
        border-radius: 4px;
        font-size: 12.5px;
      }
      .history-modal-body pre code {
        background: none;
        padding: 0;
      }
      .history-modal-body pre {
        background: var(--bg-hover, #2d2d3d);
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
        border-top: 1px solid var(--border, #2d2d3d);
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
        background: var(--accent, #6366f1);
        color: #fff;
      }
      .history-modal-btn.secondary {
        background: var(--bg-hover, #2d2d3d);
        color: var(--text-body);
        border: 1px solid var(--border, #3d3d4d);
      }
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

  function openModal(item) {
    const color = TOOL_COLORS[item.tool] || "var(--text-muted)";

    const backdrop = document.createElement("div");
    backdrop.className = "history-modal-backdrop";

    const modal = document.createElement("div");
    modal.className = "history-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    const header = document.createElement("div");
    header.className = "history-modal-header";
    header.innerHTML = `
      <span class="history-modal-tool" style="color:${color}">${item.tool}</span>
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
          if (list.children.length === 0) {
            list.innerHTML = `<div class="empty-state">No history yet. Completed outputs from all teams will appear here.</div>`;
          }
        } catch (err) {
          console.error("Failed to delete history item", err);
        }
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
