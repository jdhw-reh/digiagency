"use strict";

// ---------------------------------------------------------------------------
// Auth interceptor — redirect to /login if any API call returns 401 or 402
// Also injects a Sign Out button into the sidebar.
// ---------------------------------------------------------------------------

(function () {
  const _origFetch = window.fetch.bind(window);

  window.fetch = async function (...args) {
    const response = await _origFetch(...args);

    if (response.status === 401 || response.status === 402) {
      // Clone so the original caller can still read the body if needed
      const clone = response.clone();
      clone.json().then(data => {
        const msg = data?.error || "";
        if (msg === "Not authenticated" || msg === "Session expired" || msg === "No active subscription") {
          window.location.href = "/login";
        }
      }).catch(() => {
        window.location.href = "/login";
      });
    }

    return response;
  };

  // Add a Sign Out button to the sidebar once the DOM is ready
  document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;

    const signOutGroup = document.createElement("div");
    signOutGroup.className = "nav-group nav-group--bottom";
    signOutGroup.innerHTML = `
      <button id="btn-sign-out" class="nav-settings-btn" title="Sign out" onclick="doSignOut()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
          <polyline points="16 17 21 12 16 7"/>
          <line x1="21" y1="12" x2="9" y2="12"/>
        </svg>
        <span>Sign out</span>
      </button>`;
    sidebar.appendChild(signOutGroup);
  });
})();

async function doSignOut() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}
