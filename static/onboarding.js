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

let _step = 1; // 1 = Gemini key, 2 = Notion setup
let _userId = "";

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

function getModal()      { return document.getElementById("onboarding-modal"); }
function getOverlay()    { return document.getElementById("onboarding-overlay"); }
function getStep1()      { return document.getElementById("ob-step-1"); }
function getStep2()      { return document.getElementById("ob-step-2"); }
function getGeminiInput(){ return document.getElementById("ob-gemini-key"); }
function getNotionInput(){ return document.getElementById("ob-notion-token"); }
function getPageInput()  { return document.getElementById("ob-notion-page"); }
function getStep1Btn()   { return document.getElementById("ob-step1-next"); }
function getStep2Btn()   { return document.getElementById("ob-step2-save"); }
function getSkipBtn()    { return document.getElementById("ob-step2-skip"); }
function getProvisionBtn(){ return document.getElementById("ob-provision-btn"); }
function getProvisionStatus(){ return document.getElementById("ob-provision-status"); }
function getStep1Error() { return document.getElementById("ob-step1-error"); }
function getStep2Error() { return document.getElementById("ob-step2-error"); }

// ---------------------------------------------------------------------------
// Show / hide
// ---------------------------------------------------------------------------

function showModal() {
  getModal().style.display = "flex";
  getOverlay().style.display = "block";

  // Pre-populate if re-opening from settings
  const existing = _loadStoredCreds();
  if (existing.gemini_api_key) getGeminiInput().value = existing.gemini_api_key;
  if (existing.notion_token)   getNotionInput().value  = existing.notion_token;
  if (existing.notion_page)    getPageInput().value    = existing.notion_page;

  goToStep(1);
}

function hideModal() {
  getModal().style.display = "none";
  getOverlay().style.display = "none";
}

function goToStep(n) {
  _step = n;
  getStep1().style.display = n === 1 ? "block" : "none";
  getStep2().style.display = n === 2 ? "block" : "none";
  clearErrors();
}

function clearErrors() {
  const e1 = getStep1Error();
  const e2 = getStep2Error();
  if (e1) e1.textContent = "";
  if (e2) e2.textContent = "";
}

function showStep1Error(msg) {
  getStep1Error().textContent = msg;
}

function showStep2Error(msg) {
  getStep2Error().textContent = msg;
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
// Step 1 — Gemini API key
// ---------------------------------------------------------------------------

async function handleStep1Next() {
  const key = getGeminiInput().value.trim();
  if (!key) {
    showStep1Error("Please enter your Gemini API key.");
    return;
  }
  if (!key.startsWith("AIza")) {
    showStep1Error("That doesn't look like a valid Gemini API key (should start with AIza…).");
    return;
  }

  clearErrors();
  getStep1Btn().disabled = true;
  getStep1Btn().textContent = "Saving…";

  try {
    const existing = _loadStoredCreds();
    const res = await fetch("/api/setup/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: getUserId(),
        gemini_api_key: key,
        notion_token: existing.notion_token || "",
        notion_parent_page_id: existing.notion_page || "",
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to save");

    _userId = data.user_id;
    saveUserId(_userId);
    _saveStoredCreds({ ...existing, gemini_api_key: key });

    goToStep(2);
  } catch (e) {
    showStep1Error(`Error: ${e.message}`);
  } finally {
    getStep1Btn().disabled = false;
    getStep1Btn().textContent = "Continue →";
  }
}

// ---------------------------------------------------------------------------
// Step 2 — Notion setup (optional)
// ---------------------------------------------------------------------------

async function handleProvision() {
  const token = getNotionInput().value.trim();
  const page  = getPageInput().value.trim();

  if (!token) { showStep2Error("Please enter your Notion integration token."); return; }
  if (!page)  { showStep2Error("Please enter the Notion page URL."); return; }

  clearErrors();
  getProvisionBtn().disabled = true;
  getProvisionBtn().textContent = "Creating databases…";
  getProvisionStatus().innerHTML = "";

  try {
    // Save token + page first
    const existing = _loadStoredCreds();
    const saveRes = await fetch("/api/setup/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: _userId || getUserId(),
        gemini_api_key: existing.gemini_api_key || "",
        notion_token: token,
        notion_parent_page_id: page,
      }),
    });
    if (!saveRes.ok) {
      const d = await saveRes.json();
      throw new Error(d.error || "Failed to save Notion credentials");
    }
    _saveStoredCreds({ ...existing, notion_token: token, notion_page: page });

    // Provision databases
    const provRes = await fetch("/api/setup/notion/provision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: _userId || getUserId() }),
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
      showStep2Error("Some databases could not be created: " + provData.errors[0]);
    }

  } catch (e) {
    showStep2Error(`Error: ${e.message}`);
  } finally {
    getProvisionBtn().disabled = false;
    getProvisionBtn().textContent = "Create databases";
  }
}

async function handleStep2Save() {
  const token = getNotionInput().value.trim();
  const page  = getPageInput().value.trim();

  if (token && page) {
    const existing = _loadStoredCreds();
    await fetch("/api/setup/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: _userId || getUserId(),
        gemini_api_key: existing.gemini_api_key || "",
        notion_token: token,
        notion_parent_page_id: page,
      }),
    }).catch(() => {});
    _saveStoredCreds({ ..._loadStoredCreds(), notion_token: token, notion_page: page });
  }

  hideModal();
  updateSettingsIndicator();
}

function handleSkip() {
  hideModal();
  updateSettingsIndicator();
}

// ---------------------------------------------------------------------------
// Settings indicator (small dot on the gear if not configured)
// ---------------------------------------------------------------------------

function updateSettingsIndicator() {
  const btn = document.getElementById("btn-settings");
  if (!btn) return;
  const creds = _loadStoredCreds();
  const configured = !!(creds.gemini_api_key);
  btn.classList.toggle("settings-unconfigured", !configured);
}

// ---------------------------------------------------------------------------
// Boot — check if onboarding is needed
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  _userId = getUserId();

  // Wire step buttons
  const step1Btn = getStep1Btn();
  const step2Btn = getStep2Btn();
  const skipBtn  = getSkipBtn();
  const provBtn  = getProvisionBtn();

  if (step1Btn) step1Btn.addEventListener("click", handleStep1Next);
  if (step2Btn) step2Btn.addEventListener("click", handleStep2Save);
  if (skipBtn)  skipBtn.addEventListener("click",  handleSkip);
  if (provBtn)  provBtn.addEventListener("click",  handleProvision);

  // Settings gear button in sidebar
  const settingsBtn = document.getElementById("btn-settings");
  if (settingsBtn) settingsBtn.addEventListener("click", () => showModal());

  // Expose showSettings globally
  window.showSettings = showModal;

  // Show onboarding if not yet configured
  const creds = _loadStoredCreds();
  if (!_userId || !creds.gemini_api_key) {
    showModal();
  }

  updateSettingsIndicator();
});
