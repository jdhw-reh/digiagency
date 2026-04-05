"use strict";

// ---------------------------------------------------------------------------
// Contact Support — sidebar button + modal
// Sends POST /api/support; email pre-filled from /api/auth/me
// ---------------------------------------------------------------------------

(function () {

  // ── Build modal HTML ──────────────────────────────────────────────────────

  function createModal() {
    const overlay = document.createElement("div");
    overlay.id = "support-overlay";
    overlay.className = "support-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `
      <div class="support-modal" role="dialog" aria-modal="true" aria-labelledby="support-title">
        <h2 id="support-title">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          Contact Support
        </h2>

        <div class="support-field">
          <label for="support-email">Your email</label>
          <input id="support-email" type="email" placeholder="you@example.com" autocomplete="email">
        </div>

        <div class="support-field">
          <label for="support-type">What can we help with?</label>
          <select id="support-type">
            <option value="Get Help">Get Help</option>
            <option value="Feature Request">Feature Request</option>
            <option value="Bug Report">Bug Report</option>
            <option value="Other">Other</option>
          </select>
        </div>

        <div class="support-field">
          <label for="support-message">Message</label>
          <textarea id="support-message" placeholder="Describe what you need…"></textarea>
        </div>

        <div id="support-feedback" class="support-msg"></div>

        <div class="support-actions">
          <button id="support-cancel" class="btn-ghost">Cancel</button>
          <button id="support-submit" class="btn-primary">Send Message <span class="btn-arrow">→</span></button>
        </div>
      </div>`;

    document.body.appendChild(overlay);

    // Close on overlay background click
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeModal();
    });

    // Cancel button
    overlay.querySelector("#support-cancel").addEventListener("click", closeModal);

    // Submit
    overlay.querySelector("#support-submit").addEventListener("click", handleSubmit);

    // Esc key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.style.display !== "none") closeModal();
    });
  }

  // ── Open / close ──────────────────────────────────────────────────────────

  function openModal() {
    const overlay = document.getElementById("support-overlay");
    if (!overlay) return;

    // Reset state
    document.getElementById("support-message").value = "";
    document.getElementById("support-type").value = "Get Help";
    const fb = document.getElementById("support-feedback");
    fb.className = "support-msg";
    fb.textContent = "";

    // Pre-fill email from session
    fetch("/api/auth/me")
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.email) {
          document.getElementById("support-email").value = data.email;
        }
      })
      .catch(() => {});

    overlay.style.display = "flex";
    setTimeout(() => document.getElementById("support-message").focus(), 50);
  }

  function closeModal() {
    const overlay = document.getElementById("support-overlay");
    if (overlay) overlay.style.display = "none";
  }

  // ── Submit handler ────────────────────────────────────────────────────────

  async function handleSubmit() {
    const email   = document.getElementById("support-email").value.trim();
    const type    = document.getElementById("support-type").value;
    const message = document.getElementById("support-message").value.trim();
    const fb      = document.getElementById("support-feedback");
    const btn     = document.getElementById("support-submit");

    fb.className = "support-msg";
    fb.textContent = "";

    if (!email) {
      fb.className = "support-msg error";
      fb.textContent = "Please enter your email address.";
      return;
    }
    if (!message) {
      fb.className = "support-msg error";
      fb.textContent = "Please write a message before sending.";
      return;
    }

    btn.disabled = true;
    btn.textContent = "Sending…";

    try {
      const res = await fetch("/api/support", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, type, message }),
      });
      const data = await res.json();

      if (res.ok && data.ok) {
        fb.className = "support-msg success";
        fb.textContent = "Message sent! We'll get back to you soon.";
        btn.style.display = "none";
        document.getElementById("support-cancel").textContent = "Close";
      } else {
        fb.className = "support-msg error";
        fb.textContent = data.error || "Something went wrong. Please try again.";
        btn.disabled = false;
        btn.innerHTML = 'Send Message <span class="btn-arrow">→</span>';
      }
    } catch {
      fb.className = "support-msg error";
      fb.textContent = "Network error. Please check your connection and try again.";
      btn.disabled = false;
      btn.innerHTML = 'Send Message <span class="btn-arrow">→</span>';
    }
  }

  // ── Inject sidebar button ─────────────────────────────────────────────────

  function injectSidebarButton() {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;

    const group = document.createElement("div");
    group.className = "nav-group";
    group.innerHTML = `
      <button id="btn-contact-support" class="nav-support-btn" title="Contact support">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span>Contact Support</span>
      </button>`;

    // Insert before the sidebar-footer (theme toggle) so it sits just above it
    const footer = sidebar.querySelector(".sidebar-footer");
    if (footer) {
      sidebar.insertBefore(group, footer);
    } else {
      sidebar.appendChild(group);
    }

    group.querySelector("#btn-contact-support").addEventListener("click", openModal);
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", () => {
    createModal();
    injectSidebarButton();
  });

})();
