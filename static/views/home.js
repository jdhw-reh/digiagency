"use strict";

// ---------------------------------------------------------------------------
// Home view — director bar, activity feed, quick-launch shortcuts
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  // Wire all team cards AND quick-launch buttons to navigate on click
  document.querySelectorAll(".team-card[data-view], .launch-btn[data-view]").forEach((el) => {
    el.addEventListener("click", () => {
      window.navigateTo(el.dataset.view);
    });
  });

});

// ---------------------------------------------------------------------------
// Director bar — dynamic greeting based on activity
// ---------------------------------------------------------------------------

function buildDirectorText(data) {
  const { content_saved, social_saved, audits_done } = data;
  const total = content_saved + social_saved + audits_done;

  if (total === 0) return "Good to see you. Where are we heading today?";

  const parts = [];
  if (content_saved > 0) parts.push(`${content_saved} article${content_saved > 1 ? "s" : ""} published`);
  if (social_saved > 0) parts.push(`${social_saved} post set${social_saved > 1 ? "s" : ""} saved`);
  if (audits_done > 0) parts.push(`${audits_done} audit${audits_done > 1 ? "s" : ""} completed`);

  return `The agency is in flow — ${parts.join(", ")}.`;
}

// ---------------------------------------------------------------------------
// Activity feed
// ---------------------------------------------------------------------------

function timeAgo(isoString) {
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const TEAM_LABELS = {
  content: "Content",
  social: "Social",
  seo_audit: "SEO Audit",
  assistant: "Assistant",
  video: "Video Director",
  on_page_opt: "On-Page Optimiser",
};

const ACTIVITY_LIMIT = 7;

function cleanAction(action) {
  if (!action) return null;
  // Strip trailing colon + whitespace (e.g. "Built page:" with nothing after)
  const trimmed = action.replace(/:\s*$/, "").trim();
  return trimmed.length > 0 ? trimmed : null;
}

function renderActivityFeed(items) {
  const feed = document.getElementById("activity-feed");
  const moreBtn = document.getElementById("activity-more-btn");
  if (!feed) return;

  if (!items || items.length === 0) {
    feed.innerHTML = '<li class="activity-empty">No activity yet</li>';
    if (moreBtn) moreBtn.style.display = "none";
    return;
  }

  const visible = items.slice(0, ACTIVITY_LIMIT);
  const overflow = items.length - ACTIVITY_LIMIT;

  feed.innerHTML = visible
    .map((item) => {
      const label = TEAM_LABELS[item.team] || item.team;
      const action = cleanAction(item.action);
      return `
    <li class="activity-item activity-item--${item.team}">
      <span class="activity-team">${label}</span>
      <span class="activity-action">${action ? action : '<em style="color:var(--text-dim)">in progress</em>'}</span>
      <span class="activity-time">${timeAgo(item.ts)}</span>
    </li>`;
    })
    .join("");

  if (moreBtn) {
    if (overflow > 0) {
      moreBtn.textContent = `${overflow} more item${overflow > 1 ? "s" : ""}`;
      moreBtn.style.display = "block";
      moreBtn.onclick = () => {
        // Render all items and hide the button
        feed.innerHTML += items
          .slice(ACTIVITY_LIMIT)
          .map((item) => {
            const label = TEAM_LABELS[item.team] || item.team;
            const action = cleanAction(item.action);
            return `
          <li class="activity-item activity-item--${item.team}">
            <span class="activity-team">${label}</span>
            <span class="activity-action">${action ? action : '<em style="color:var(--text-dim)">in progress</em>'}</span>
            <span class="activity-time">${timeAgo(item.ts)}</span>
          </li>`;
          })
          .join("");
        moreBtn.style.display = "none";
      };
    } else {
      moreBtn.style.display = "none";
    }
  }
}

// ---------------------------------------------------------------------------
// Load summary from server
// ---------------------------------------------------------------------------

async function loadDirectorSummary() {
  try {
    const data = await fetch("/api/director/summary").then((r) => r.json());
    const textEl = document.getElementById("director-text");
    if (textEl) textEl.textContent = buildDirectorText(data);
    renderActivityFeed(data.activity || []);
    if ((data.activity || []).length > 0) {
      const toggle = document.getElementById("activity-toggle");
      const body = document.getElementById("activity-body");
      if (toggle && body) { toggle.setAttribute("aria-expanded", "true"); body.classList.add("is-open"); }
    }
  } catch (e) {
    console.warn("Could not load director summary:", e);
  }
}

// ---------------------------------------------------------------------------
// Live notification stream — updates activity feed without polling
// ---------------------------------------------------------------------------

let _notificationSource = null;

function startNotificationStream() {
  if (_notificationSource) return; // already connected

  _notificationSource = new EventSource("/api/agency/stream/notifications");

  _notificationSource.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      // Re-load the full summary so counters + feed stay in sync
      loadDirectorSummary();
      // Flash the activity feed briefly to signal the update
      const feed = document.getElementById("activity-feed");
      if (feed) {
        feed.classList.add("activity-flash");
        setTimeout(() => feed.classList.remove("activity-flash"), 600);
      }
    } catch (_) {}
  };

  _notificationSource.onerror = () => {
    // Connection dropped — clean up and let the next mount restart it
    _notificationSource.close();
    _notificationSource = null;
  };
}

function stopNotificationStream() {
  if (_notificationSource) {
    _notificationSource.close();
    _notificationSource = null;
  }
}

// ---------------------------------------------------------------------------
// View mount hook
// ---------------------------------------------------------------------------

function viewDidMount_home() {
  loadDirectorSummary();
  startNotificationStream();

  // Wire activity toggle (must happen here, not DOMContentLoaded, as this is a SPA)
  const toggle = document.getElementById("activity-toggle");
  const body = document.getElementById("activity-body");
  if (toggle && body) {
    toggle.onclick = () => {
      const isOpen = body.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    };
  }
}

function viewWillUnmount_home() {
  stopNotificationStream();
}

window.viewDidMount_home = viewDidMount_home;
window.viewWillUnmount_home = viewWillUnmount_home;
