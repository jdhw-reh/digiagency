"use strict";

// ---------------------------------------------------------------------------
// Public Contact Support — modal for login + landing pages (no auth required)
// Sends POST /api/support; email is entered manually or pre-filled by caller.
// Exposes: window.openSupportModal(prefillEmail)
// ---------------------------------------------------------------------------

(function () {

  // ── Inject styles ─────────────────────────────────────────────────────────

  function injectStyles() {
    if (document.getElementById("pub-support-styles")) return;
    const style = document.createElement("style");
    style.id = "pub-support-styles";
    style.textContent = `
      .pub-support-overlay {
        position: fixed;
        inset: 0;
        background: rgba(10,10,10,0.65);
        backdrop-filter: blur(3px);
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
      }
      .pub-support-modal {
        background: #141414;
        border: 1px solid #2a2a2a;
        border-radius: 14px;
        padding: 28px 30px 24px;
        width: 100%;
        max-width: 480px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.45);
        display: flex;
        flex-direction: column;
        gap: 18px;
        font-family: 'DM Sans', system-ui, sans-serif;
      }
      .pub-support-modal h2 {
        font-size: 1.05rem;
        font-weight: 650;
        color: #e5e5e5;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .pub-support-modal h2 svg { opacity: 0.75; flex-shrink: 0; }
      .pub-support-field {
        display: flex;
        flex-direction: column;
        gap: 5px;
      }
      .pub-support-field label {
        font-size: 0.75rem;
        font-weight: 600;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .pub-support-field input,
      .pub-support-field select,
      .pub-support-field textarea {
        background: #0f0f0f;
        border: 1px solid #2a2a2a;
        border-radius: 8px;
        padding: 9px 12px;
        font-size: 0.875rem;
        color: #e5e5e5;
        font-family: inherit;
        width: 100%;
        box-sizing: border-box;
        outline: none;
        transition: border-color 0.15s;
      }
      .pub-support-field input:focus,
      .pub-support-field select:focus,
      .pub-support-field textarea:focus { border-color: #6366f1; }
      .pub-support-field textarea {
        resize: vertical;
        min-height: 110px;
        line-height: 1.55;
      }
      .pub-support-field select {
        cursor: pointer;
        appearance: none;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 10px center;
        padding-right: 28px;
      }
      .pub-support-msg {
        font-size: 0.85rem;
        padding: 9px 12px;
        border-radius: 7px;
        display: none;
      }
      .pub-support-msg.success {
        display: block;
        background: rgba(16,185,129,0.12);
        color: #10b981;
        border: 1px solid rgba(16,185,129,0.25);
      }
      .pub-support-msg.error {
        display: block;
        background: rgba(239,68,68,0.1);
        color: #ef4444;
        border: 1px solid rgba(239,68,68,0.2);
      }
      .pub-support-actions {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
      }
      .pub-support-btn-cancel {
        padding: 9px 18px;
        background: none;
        border: 1px solid #2a2a2a;
        border-radius: 8px;
        color: #888;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        font-family: inherit;
        transition: border-color 0.15s, color 0.15s;
      }
      .pub-support-btn-cancel:hover { border-color: #444; color: #e5e5e5; }
      .pub-support-btn-send {
        padding: 9px 20px;
        background: #6366f1;
        border: none;
        border-radius: 8px;
        color: #fff;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        font-family: inherit;
        transition: background 0.15s, opacity 0.15s;
      }
      .pub-support-btn-send:hover { background: #4f52d6; }
      .pub-support-btn-send:disabled { opacity: 0.5; cursor: not-allowed; }
    `;
    document.head.appendChild(style);
  }

  // ── Build modal ───────────────────────────────────────────────────────────

  function createModal() {
    if (document.getElementById("pub-support-overlay")) return;

    const overlay = document.createElement("div");
    overlay.id = "pub-support-overlay";
    overlay.className = "pub-support-overlay";
    overlay.style.display = "none";
    overlay.innerHTML = `
      <div class="pub-support-modal" role="dialog" aria-modal="true" aria-labelledby="pub-support-title">
        <h2 id="pub-support-title">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          Contact Support
        </h2>

        <div class="pub-support-field">
          <label for="pub-support-email">Your email</label>
          <input id="pub-support-email" type="email" placeholder="you@example.com" autocomplete="email">
        </div>

        <div class="pub-support-field">
          <label for="pub-support-type">What can we help with?</label>
          <select id="pub-support-type">
            <option value="Get Help">Get Help</option>
            <option value="Login Issue">Login Issue</option>
            <option value="Billing">Billing</option>
            <option value="Feature Request">Feature Request</option>
            <option value="Bug Report">Bug Report</option>
            <option value="Other">Other</option>
          </select>
        </div>

        <div class="pub-support-field">
          <label for="pub-support-message">Message</label>
          <textarea id="pub-support-message" placeholder="Describe what you need…"></textarea>
        </div>

        <div id="pub-support-feedback" class="pub-support-msg"></div>

        <div class="pub-support-actions">
          <button id="pub-support-cancel" class="pub-support-btn-cancel">Cancel</button>
          <button id="pub-support-submit" class="pub-support-btn-send">Send message →</button>
        </div>
      </div>`;

    document.body.appendChild(overlay);

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeModal();
    });

    overlay.querySelector("#pub-support-cancel").addEventListener("click", closeModal);
    overlay.querySelector("#pub-support-submit").addEventListener("click", handleSubmit);

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.style.display !== "none") closeModal();
    });
  }

  // ── Open / close ──────────────────────────────────────────────────────────

  function openModal(prefillEmail) {
    const overlay = document.getElementById("pub-support-overlay");
    if (!overlay) return;

    // Reset
    document.getElementById("pub-support-message").value = "";
    document.getElementById("pub-support-type").value = "Get Help";
    const fb = document.getElementById("pub-support-feedback");
    fb.className = "pub-support-msg";
    fb.textContent = "";
    const btn = document.getElementById("pub-support-submit");
    btn.style.display = "";
    btn.disabled = false;
    btn.textContent = "Send message →";
    document.getElementById("pub-support-cancel").textContent = "Cancel";

    // Pre-fill email if provided, or try to read from page email inputs
    const emailInput = document.getElementById("pub-support-email");
    if (prefillEmail) {
      emailInput.value = prefillEmail;
    } else {
      const pageEmail =
        document.getElementById("login-email") ||
        document.getElementById("reg-email");
      emailInput.value = (pageEmail && pageEmail.value.trim()) ? pageEmail.value.trim() : "";
    }

    overlay.style.display = "flex";
    setTimeout(() => {
      const target = emailInput.value ? document.getElementById("pub-support-message") : emailInput;
      target.focus();
    }, 50);
  }

  function closeModal() {
    const overlay = document.getElementById("pub-support-overlay");
    if (overlay) overlay.style.display = "none";
  }

  // ── Submit ────────────────────────────────────────────────────────────────

  async function handleSubmit() {
    const email   = document.getElementById("pub-support-email").value.trim();
    const type    = document.getElementById("pub-support-type").value;
    const message = document.getElementById("pub-support-message").value.trim();
    const fb      = document.getElementById("pub-support-feedback");
    const btn     = document.getElementById("pub-support-submit");

    fb.className = "pub-support-msg";
    fb.textContent = "";

    if (!email) {
      fb.className = "pub-support-msg error";
      fb.textContent = "Please enter your email address.";
      return;
    }
    if (!message) {
      fb.className = "pub-support-msg error";
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
        fb.className = "pub-support-msg success";
        fb.textContent = "Message sent! We'll get back to you soon.";
        btn.style.display = "none";
        document.getElementById("pub-support-cancel").textContent = "Close";
      } else {
        fb.className = "pub-support-msg error";
        fb.textContent = data.error || "Something went wrong. Please try again.";
        btn.disabled = false;
        btn.textContent = "Send message →";
      }
    } catch {
      fb.className = "pub-support-msg error";
      fb.textContent = "Network error. Please check your connection and try again.";
      btn.disabled = false;
      btn.textContent = "Send message →";
    }
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", () => {
    injectStyles();
    createModal();
  });

  window.openSupportModal = openModal;

})();
