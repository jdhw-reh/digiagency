"use strict";

// ---------------------------------------------------------------------------
// Shared accordion helpers used by all view modules
// ---------------------------------------------------------------------------
// API:
//   setPanelState(panelEl, 'locked' | 'active' | 'done')
//   setPanelSummary(panelEl, htmlString)
//   openPanelDrawer(panelEl)
//   closeDrawer()

(function () {

  /**
   * Set the accordion state of a panel element.
   * Removes existing state classes and adds the new one.
   * Updates badge text: ✓ for done, step number otherwise.
   */
  function setPanelState(panelEl, state) {
    if (!panelEl) return;
    panelEl.classList.remove('panel--locked', 'panel--active', 'panel--done');
    panelEl.classList.add('panel--' + state);

    const badge = panelEl.querySelector('.panel-badge');
    if (!badge) return;
    if (state === 'done') {
      badge.textContent = '✓';
    } else {
      badge.textContent = badge.dataset.step || badge.textContent;
    }
  }

  /**
   * Set the one-line summary shown when a panel is in 'done' state.
   * html can contain inline elements (spans, score pills, etc.)
   */
  function setPanelSummary(panelEl, html) {
    if (!panelEl) return;
    const el = panelEl.querySelector('.panel-summary-text');
    if (el) el.innerHTML = html;
  }

  /**
   * Open the review modal populated with a clone of panelEl's .panel-body.
   * Footer CTAs are stripped from the clone — they're not actionable in the modal.
   * Guide action buttons (copy/download) are re-wired after cloning.
   */
  function openPanelDrawer(panelEl) {
    const drawer  = document.getElementById('panel-drawer');
    const scrim   = document.getElementById('panel-scrim');
    const titleEl = document.getElementById('panel-drawer-title');
    const bodyEl  = document.getElementById('panel-drawer-body');
    if (!drawer || !scrim || !titleEl || !bodyEl) return;

    const h2 = panelEl.querySelector('h2');
    titleEl.textContent = h2 ? h2.textContent : '';

    const panelBody = panelEl.querySelector('.panel-body');
    bodyEl.innerHTML = panelBody ? panelBody.innerHTML : '';
    // Strip footer CTAs — not actionable from within the modal
    bodyEl.querySelectorAll('.panel-footer').forEach(function (el) { el.remove(); });

    // Re-wire guide action buttons (copy / download) — onclick attrs don't survive innerHTML clone
    bodyEl.querySelectorAll('[data-guide-action]').forEach(function (btn) {
      var action = btn.dataset.guideAction;
      btn.addEventListener('click', function () {
        if (action === 'copy' && typeof window.copyImplementerGuide === 'function') {
          window.copyImplementerGuide(btn);
        } else if (action === 'download' && typeof window.downloadImplementerGuide === 'function') {
          window.downloadImplementerGuide();
        }
      });
    });

    scrim.classList.add('visible');
    drawer.classList.add('open');
    drawer.focus();
  }

  /**
   * Close the review drawer / bottom sheet.
   */
  function closeDrawer() {
    var drawer = document.getElementById('panel-drawer');
    var scrim  = document.getElementById('panel-scrim');
    if (drawer) drawer.classList.remove('open');
    if (scrim)  scrim.classList.remove('visible');
  }

  // Wire scrim click and Escape key once DOM is ready
  document.addEventListener('DOMContentLoaded', function () {
    var scrim = document.getElementById('panel-scrim');
    if (scrim) scrim.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDrawer();
    });
  });

  // Expose globally so view modules can call them
  window.setPanelState   = setPanelState;
  window.setPanelSummary = setPanelSummary;
  window.openPanelDrawer = openPanelDrawer;
  window.closeDrawer     = closeDrawer;

})();
