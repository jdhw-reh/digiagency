"use strict";

// ---------------------------------------------------------------------------
// Onboarding & settings — manages user credentials stored in localStorage
// and synced to the server via /api/setup/user
//
// Global exports:
//   window.getAppUserId()   — returns the current user_id (or "")
//   window.showSettings()   — open the settings modal
// ---------------------------------------------------------------------------

const APP_USER_KEY = "agencyUserId";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getUserId() {
  return localStorage.getItem(APP_USER_KEY) || "";
}

function saveUserId(id) {
  localStorage.setItem(APP_USER_KEY, id);
}

// Expose globally for view scripts
window.getAppUserId = getUserId;

// ---------------------------------------------------------------------------
// Modal state
// ---------------------------------------------------------------------------

let _userId = "";

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

function getModal()          { return document.getElementById("onboarding-modal"); }
function getOverlay()        { return document.getElementById("onboarding-overlay"); }
function getNotionInput()    { return document.getElementById("ob-notion-token"); }
function getPageInput()      { return document.getElementById("ob-notion-page"); }
function getStep2Btn()       { return document.getElementById("ob-step2-save"); }
function getSkipBtn()        { return document.getElementById("ob-step2-skip"); }
function getProvisionBtn()   { return document.getElementById("ob-provision-btn"); }
function getProvisionStatus(){ return document.getElementById("ob-provision-status"); }
function getStep2Error()     { return document.getElementById("ob-step2-error"); }

// ---------------------------------------------------------------------------
// Show / hide
// ---------------------------------------------------------------------------

function showModal() {
  getModal().style.display = "flex";
  getOverlay().style.display = "block";

  // Pre-populate if re-opening from settings
  const existing = _loadStoredCreds();
  if (existing.notion_token) getNotionInput().value = existing.notion_token;
  if (existing.notion_page)  getPageInput().value   = existing.notion_page;

  getStep2Error().textContent = "";

  // Notify team.js (and any other hooks) that settings opened
  if (typeof window.onSettingsOpen === "function") window.onSettingsOpen();
}

function hideModal() {
  getModal().style.display = "none";
  getOverlay().style.display = "none";
}

// ---------------------------------------------------------------------------
// Stored creds helpers
// ---------------------------------------------------------------------------

function _loadStoredCreds() {
  try {
    return JSON.parse(localStorage.getItem("agencyCreds") || "{}");
  } catch {
    return {};
  }
}

function _saveStoredCreds(creds) {
  localStorage.setItem("agencyCreds", JSON.stringify(creds));
}

// ---------------------------------------------------------------------------
// Notion setup
// ---------------------------------------------------------------------------

async function handleProvision() {
  const token = getNotionInput().value.trim();
  const page  = getPageInput().value.trim();

  if (!token) { getStep2Error().textContent = "Please enter your Notion integration token."; return; }
  if (!page)  { getStep2Error().textContent = "Please enter the Notion page URL."; return; }

  getStep2Error().textContent = "";
  getProvisionBtn().disabled = true;
  getProvisionBtn().textContent = "Creating databases…";
  getProvisionStatus().innerHTML = "";

  try {
    const saveRes = await fetch("/api/setup/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: _userId || getUserId(),
        notion_token: token,
        notion_parent_page_id: page,
      }),
    });
    const saveData = await saveRes.json();
    if (!saveRes.ok) throw new Error(saveData.error || "Failed to save Notion credentials");

    _userId = saveData.user_id;
    saveUserId(_userId);
    _saveStoredCreds({ ..._loadStoredCreds(), notion_token: token, notion_page: page });

    const provRes = await fetch("/api/setup/notion/provision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: _userId }),
    });
    const provData = await provRes.json();

    if (!provRes.ok) throw new Error(provData.error || "Provisioning failed");

    const dbs = provData.databases || {};
    const names = {
      content: "Content Articles",
      social: "Social Posts",
      agency_log: "Agency Activity Log",
      video: "Video Briefs",
      on_page: "On-Page Optimisations",
    };

    const lines = Object.entries(names).map(([k, label]) => {
      const ok = !!dbs[k];
      return `<div class="ob-db-row ${ok ? "ob-db-ok" : "ob-db-err"}">
        <span class="ob-db-icon">${ok ? "✓" : "✗"}</span>
        <span>${label}</span>
      </div>`;
    });
    getProvisionStatus().innerHTML = lines.join("");

    if (provData.errors && provData.errors.length > 0) {
      getStep2Error().textContent = "Some databases could not be created: " + provData.errors[0];
    }

  } catch (e) {
    getStep2Error().textContent = `Error: ${e.message}`;
  } finally {
    getProvisionBtn().disabled = false;
    getProvisionBtn().textContent = "Create databases";
  }
}

async function handleStep2Save() {
  const token = getNotionInput().value.trim();
  const page  = getPageInput().value.trim();

  if (token && page) {
    try {
      const res = await fetch("/api/setup/user", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: _userId || getUserId(),
          notion_token: token,
          notion_parent_page_id: page,
        }),
      });
      const data = await res.json();
      if (data.user_id) {
        _userId = data.user_id;
        saveUserId(_userId);
      }
    } catch {}
    _saveStoredCreds({ ..._loadStoredCreds(), notion_token: token, notion_page: page });
  }

  hideModal();
  updateSettingsIndicator();
}

async function handleSkip() {
  // Ensure a user session exists even when Notion is skipped
  if (!_userId) {
    try {
      const res = await fetch("/api/setup/user", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: "", notion_token: "", notion_parent_page_id: "" }),
      });
      const data = await res.json();
      if (data.user_id) {
        _userId = data.user_id;
        saveUserId(_userId);
      }
    } catch {}
  }
  hideModal();
  updateSettingsIndicator();
}

async function handleBillingPortal() {
  const btn = document.getElementById("ob-billing-portal-btn");
  btn.textContent = "Loading…";
  btn.disabled = true;
  try {
    const res = await fetch("/api/checkout/portal", { method: "POST" });
    const data = await res.json();
    if (!res.ok || !data.url) {
      showError(data.error || "Could not open billing portal. Please contact support.");
      return;
    }
    window.location.href = data.url;
  } catch {
    showError("Network error — please try again.");
  } finally {
    btn.textContent = "Manage subscription →";
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Settings indicator (dot on the gear when Notion is not configured)
// ---------------------------------------------------------------------------

function updateSettingsIndicator() {
  const btn = document.getElementById("btn-settings");
  if (!btn) return;
  const creds = _loadStoredCreds();
  btn.classList.toggle("settings-unconfigured", !creds.notion_token);
}

// ---------------------------------------------------------------------------
// Boot — check if onboarding is needed
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  // Fetch current user info for plan/team display
  try {
    const meRes = await fetch("/api/auth/me");
    if (meRes.ok) window._currentUser = await meRes.json();
  } catch {}

  _userId = getUserId();

  const step2Btn = getStep2Btn();
  const skipBtn  = getSkipBtn();
  const provBtn  = getProvisionBtn();

  if (step2Btn) step2Btn.addEventListener("click", handleStep2Save);
  if (skipBtn)  skipBtn.addEventListener("click",  handleSkip);
  if (provBtn)  provBtn.addEventListener("click",  handleProvision);

  const billingBtn = document.getElementById("ob-billing-portal-btn");
  if (billingBtn) billingBtn.addEventListener("click", handleBillingPortal);

  const settingsBtn = document.getElementById("btn-settings");
  if (settingsBtn) settingsBtn.addEventListener("click", () => showModal());

  window.showSettings = showModal;

  // Show onboarding if no user session exists yet
  if (!_userId) {
    showModal();
  } else if (!_loadStoredCreds().notion_token) {
    // Has a session but Notion isn't set up — nudge once per session
    setTimeout(() => {
      if (typeof showNotionConfigPrompt === "function") showNotionConfigPrompt();
    }, 2500);
  }

  updateSettingsIndicator();
});
