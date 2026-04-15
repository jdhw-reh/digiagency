"use strict";

// ---------------------------------------------------------------------------
// Hash-based SPA router
// Navigates between #/home, #/content, #/social, #/assistant
// ---------------------------------------------------------------------------

const VIEWS = ["home", "content", "social", "assistant", "seo-audit", "video", "on-page-opt", "history"];

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
