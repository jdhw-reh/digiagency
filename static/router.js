"use strict";

// ---------------------------------------------------------------------------
// SPA router — keeps URL clean at /app (no hash fragments)
// ---------------------------------------------------------------------------

const VIEWS = ["home", "content", "social", "assistant", "seo-audit", "video", "on-page-opt", "history"];

function navigate(view, replace = false) {
  if (window.clearLimitBanners) window.clearLimitBanners();

  const targetView = VIEWS.includes(view) ? view : "home";

  VIEWS.forEach((v) => {
    const el = document.getElementById(`view-${v}`);
    if (!el) return;
    el.classList.toggle("view--visible", v === targetView);
  });

  document.querySelectorAll(".nav-link[data-view]").forEach((link) => {
    link.classList.toggle("nav-link--active", link.dataset.view === targetView);
  });

  const prev = window._currentView;
  if (prev && prev !== targetView) {
    const unmountFn = window[`viewWillUnmount_${prev}`];
    if (typeof unmountFn === "function") unmountFn();
  }

  const mountFn = window[`viewDidMount_${targetView}`];
  if (typeof mountFn === "function") mountFn();

  window._currentView = targetView;
  const stateMethod = replace ? "replaceState" : "pushState";
  history[stateMethod]({ view: targetView }, "", "/app");
}

// Public API
window.navigateTo = (view) => navigate(view);

window.addEventListener("popstate", (e) => navigate(e.state?.view || "home"));

document.addEventListener("DOMContentLoaded", () => {
  // Intercept nav link clicks so they don't trigger hash changes
  document.querySelectorAll(".nav-link[data-view]").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      navigate(link.dataset.view);
    });
  });

  // Read any existing hash on first load (e.g. old bookmarks), then clean the URL
  const hash = location.hash.replace(/^#\/?/, "").toLowerCase();
  navigate(VIEWS.includes(hash) ? hash : "home", true);
});

// ---------------------------------------------------------------------------
// Mobile sidebar toggle — runs immediately (DOM is ready; scripts are at
// bottom of <body> so all elements exist when this executes)
// ---------------------------------------------------------------------------
(function () {
  const toggle = document.getElementById('sidebar-toggle');
  const sidebar = document.getElementById('sidebar');
  if (!toggle || !sidebar) return;

  const overlay = document.createElement('div');
  overlay.id = 'sidebar-overlay';
  document.body.appendChild(overlay);

  function openSidebar() {
    sidebar.classList.add('sidebar--open');
    document.body.classList.add('sidebar-open');
    overlay.classList.add('overlay--visible');
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-label', 'Close navigation');
  }

  function closeSidebar() {
    sidebar.classList.remove('sidebar--open');
    document.body.classList.remove('sidebar-open');
    overlay.classList.remove('overlay--visible');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open navigation');
  }

  toggle.addEventListener('click', function () {
    if (sidebar.classList.contains('sidebar--open')) {
      closeSidebar();
    } else {
      openSidebar();
    }
  });
  overlay.addEventListener('click', closeSidebar);
  sidebar.addEventListener('click', function (e) {
    if (e.target.closest('.nav-link')) closeSidebar();
  });
})();
