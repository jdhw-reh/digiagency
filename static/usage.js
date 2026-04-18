"use strict";

// ---------------------------------------------------------------------------
// Usage tracking — progress bars, limit banners, locked modals, data loading
// ---------------------------------------------------------------------------

const TOOL_NAMES = {
  content:     "Content Team",
  social:      "Social Team",
  seo_audit:   "SEO Audit",
  video:       "Video Director",
  on_page_opt: "On-Page Optimiser",
  assistant:   "Assistant",
};

const TOOL_OUTPUT_LABELS = {
  content:     "articles",
  social:      "campaigns",
  seo_audit:   "audits",
  video:       "videos",
  on_page_opt: "optimisations",
  assistant:   "messages",
};

// 1st of next month, e.g. "1 June"
function getResetDateStr() {
  const now  = new Date();
  const next = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  return next.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
}

// ---------------------------------------------------------------------------
// renderUsageBar — returns an HTML string, or "" for unlimited plans
// ---------------------------------------------------------------------------

function renderUsageBar(tool, toolUsage) {
  if (!toolUsage) return "";

  const { used = 0, cap, locked } = toolUsage;

  if (locked === true || cap === 0) {
    return `<div class="usage-bar-locked">
      <span class="usage-lock-icon">🔒</span>
      <span>Upgrade to Pro to unlock this tool</span>
      <a href="/app" class="usage-upgrade-link" onclick="window.navigateTo('home');return false;">Upgrade →</a>
    </div>`;
  }

  if (cap === null || cap === undefined) return "";

  const pct      = Math.min(100, cap > 0 ? Math.round((used / cap) * 100) : 0);
  const colorCls = pct >= 90 ? "usage-bar-fill--red"
                 : pct >= 60 ? "usage-bar-fill--amber"
                 :             "usage-bar-fill--green";
  const atCap    = used >= cap;
  const label    = TOOL_OUTPUT_LABELS[tool] || "outputs";
  const resetStr = getResetDateStr();

  let html = `<div class="usage-bar-wrap">
    <div class="usage-bar-label">${used} of ${cap} ${label} used this month</div>
    <div class="usage-bar-track">
      <div class="usage-bar-fill ${colorCls}" style="width:${pct}%"></div>
    </div>
    <div class="usage-bar-sub">Resets ${resetStr}`;

  if (atCap) {
    html += ` &mdash; <a href="/app" class="usage-upgrade-link" onclick="window.navigateTo('home');return false;">Upgrade to Pro for unlimited access &rarr;</a>`;
  }
  html += `</div></div>`;
  return html;
}

// ---------------------------------------------------------------------------
// DOM injection — slot per view, created lazily after the view header
// ---------------------------------------------------------------------------

const VIEW_TOOL_MAP = {
  "view-content":     "content",
  "view-social":      "social",
  "view-seo-audit":   "seo_audit",
  "view-video":       "video",
  "view-on-page-opt": "on_page_opt",
  "view-assistant":   "assistant",
};

function getOrCreateSlot(viewEl) {
  let slot = viewEl.querySelector(".usage-bar-slot");
  if (!slot) {
    slot = document.createElement("div");
    slot.className = "usage-bar-slot";
    const header = viewEl.querySelector(".view-header");
    if (header && header.parentNode) {
      header.parentNode.insertBefore(slot, header.nextSibling);
    } else {
      viewEl.prepend(slot);
    }
  }
  return slot;
}

function refreshUsageBarsInDom() {
  const data = window._usageData;
  if (!data || !data.usage) return;

  Object.entries(VIEW_TOOL_MAP).forEach(([viewId, tool]) => {
    const viewEl = document.getElementById(viewId);
    if (!viewEl) return;
    const slot = getOrCreateSlot(viewEl);
    slot.innerHTML = renderUsageBar(tool, data.usage[tool]);
  });

  refreshHomeUsageCard(data.usage);

  // Keep video locked state in sync whenever we're on that view
  if (window._currentView === "video") applyVideoLockedState();
}

// ---------------------------------------------------------------------------
// Home usage card
// ---------------------------------------------------------------------------

function refreshHomeUsageCard(usage) {
  const card = document.getElementById("home-usage-card");
  if (!card || !usage) return;

  const allUnlimited = Object.values(usage).every(
    u => (u.cap === null || u.cap === undefined) && !u.locked
  );

  if (allUnlimited) {
    card.innerHTML = `<p class="usage-unlimited-msg">Unlimited plan — no usage limits.</p>`;
    return;
  }

  const rows = Object.entries(usage).map(([tool, toolUsage]) => {
    const bar = renderUsageBar(tool, toolUsage);
    if (!bar) return "";
    return `<div class="usage-card-row">${bar}</div>`;
  }).filter(Boolean).join("");

  if (!rows) {
    card.innerHTML = `<p class="usage-unlimited-msg">Unlimited plan — no usage limits.</p>`;
    return;
  }

  card.innerHTML = rows;
}

// ---------------------------------------------------------------------------
// Video Director — apply gated UI when locked
// ---------------------------------------------------------------------------

function applyVideoLockedState() {
  const data = window._usageData;
  if (!data || !data.usage) return;

  const videoUsage = data.usage.video;
  if (!videoUsage || !(videoUsage.locked || videoUsage.cap === 0)) return;

  const viewEl = document.getElementById("view-video");
  if (!viewEl) return;

  viewEl.querySelectorAll("input, textarea, select").forEach(el => {
    el.disabled = true;
  });

  const btnDirect = document.getElementById("video-btn-direct");
  if (btnDirect) {
    btnDirect.disabled   = false; // keep clickable so the CTA works
    btnDirect.textContent = "Upgrade to unlock →";
    btnDirect.className   = "btn-primary btn-red";
    btnDirect.onclick = (e) => {
      e.preventDefault();
      window.navigateTo("home");
    };
  }
}

// ---------------------------------------------------------------------------
// Limit banner — full-width amber stripe in current tool view
// ---------------------------------------------------------------------------

function showLimitBanner(tool, limit, used) {
  clearLimitBanners();

  const toolLabel = TOOL_NAMES[tool] || tool;
  const monthName = new Date().toLocaleDateString("en-GB", { month: "long" });
  const resetStr  = getResetDateStr();

  const banner = document.createElement("div");
  banner.className  = "limit-banner";
  banner.id         = "limit-banner-active";
  banner.innerHTML  = `
    <span><strong>${toolLabel} limit reached</strong> — you've used all ${limit} outputs for ${monthName}.
    Your limit resets on ${resetStr}.</span>
    <a href="/app" class="limit-banner-upgrade"
       onclick="window.navigateTo('home');return false;">Upgrade to Pro for unlimited access &rarr;</a>
  `;

  const currentView = window._currentView;
  const viewEl = currentView
    ? document.getElementById(`view-${currentView}`)
    : document.getElementById("app-main");

  if (viewEl) viewEl.insertBefore(banner, viewEl.firstChild);

  disableActionButtonForTool(tool);

  // Reload usage so bars update to red/full
  if (window.loadUsageData) window.loadUsageData();
}

function clearLimitBanners() {
  document.querySelectorAll(".limit-banner").forEach(el => el.remove());
}

function disableActionButtonForTool(tool) {
  const BTN_IDS = {
    content:     "btn-research",
    social:      "social-btn-scout",
    seo_audit:   "audit-btn-start",
    video:       "video-btn-direct",
    on_page_opt: "opt-btn-start-review",
    assistant:   "asst-btn-send",
  };
  const btn = document.getElementById(BTN_IDS[tool]);
  if (btn) {
    btn.disabled    = true;
    btn.textContent = "Limit reached";
  }
}

// ---------------------------------------------------------------------------
// Tool locked modal (403 tool_locked from API)
// ---------------------------------------------------------------------------

function showToolLockedModal(toolName) {
  const existing = document.getElementById("tool-locked-modal");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id        = "tool-locked-modal";
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-box">
      <div class="modal-title">Tool not available on your plan</div>
      <p class="modal-body">The ${toolName || "Video Director"} is available on Pro and Agency plans.
         Upgrade your plan to access this tool.</p>
      <div class="modal-actions">
        <a href="/app" class="btn-primary"
           onclick="window.navigateTo('home');document.getElementById('tool-locked-modal')?.remove();return false;">
          View plans &rarr;
        </a>
        <button class="btn-ghost"
                onclick="document.getElementById('tool-locked-modal').remove()">
          Close
        </button>
      </div>
    </div>
  `;

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.remove();
  });

  document.body.appendChild(overlay);
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadUsageData() {
  try {
    const res = await fetch("/api/usage");
    if (!res.ok) return;
    window._usageData = await res.json();
    refreshUsageBarsInDom();
  } catch (e) {
    console.warn("Could not load usage data:", e);
  }
}

// ---------------------------------------------------------------------------
// Clear banners on navigation
// ---------------------------------------------------------------------------

window.addEventListener("hashchange", clearLimitBanners);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

window.renderUsageBar        = renderUsageBar;
window.loadUsageData         = loadUsageData;
window.showLimitBanner       = showLimitBanner;
window.showToolLockedModal   = showToolLockedModal;
window.applyVideoLockedState = applyVideoLockedState;
window.refreshUsageBarsInDom = refreshUsageBarsInDom;
window._usageToolNames       = TOOL_NAMES;

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadUsageData();
});
