"use strict";

// ---------------------------------------------------------------------------
// Hash-based SPA router
// Navigates between #/home, #/content, #/social, #/assistant
// ---------------------------------------------------------------------------

const VIEWS = ["home", "content", "social", "assistant", "seo-audit", "video", "on-page-opt"];

function navigate(hash) {
  const raw = hash.replace(/^#\/?/, "").toLowerCase();
  const view = VIEWS.includes(raw) ? raw : "home";

  // Fade all views out, fade target view in
  VIEWS.forEach((v) => {
    const el = document.getElementById(`view-${v}`);
    if (!el) return;
    if (v === view) {
      el.classList.add("view--visible");
    } else {
      el.classList.remove("view--visible");
    }
  });

  // Update active sidebar link
  document.querySelectorAll(".nav-link[data-view]").forEach((link) => {
    link.classList.toggle("nav-link--active", link.dataset.view === view);
  });

  // Call previous view's unmount hook if navigating away
  const prev = window._currentView;
  if (prev && prev !== view) {
    const unmountFn = window[`viewWillUnmount_${prev}`];
    if (typeof unmountFn === "function") unmountFn();
  }

  // Call view's mount hook
  const mountFn = window[`viewDidMount_${view}`];
  if (typeof mountFn === "function") mountFn();

  window._currentView = view;
}

// Public API
window.navigateTo = (view) => {
  location.hash = `#/${view}`;
};

window.addEventListener("hashchange", () => navigate(location.hash));

document.addEventListener("DOMContentLoaded", () => {
  if (!location.hash || location.hash === "#" || location.hash === "#/") {
    history.replaceState(null, "", "#/home");
  }
  navigate(location.hash);
});
