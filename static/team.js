"use strict";

// ---------------------------------------------------------------------------
// Team management UI — renders inside #ob-team-section in the settings modal.
// Loaded after onboarding.js. Hooks into window.onSettingsOpen.
// ---------------------------------------------------------------------------

let _teamData = null;
let _pendingData = [];

window.onSettingsOpen = async function () {
  await loadTeamSection();
};

async function loadTeamSection() {
  const user = window._currentUser;
  const section = document.getElementById("ob-team-section");
  if (!section) return;

  const isAgency = user?.plan === "agency";
  const hasTeamRole = !!user?.team_role;

  if (!isAgency && !hasTeamRole) {
    section.style.display = "none";
    return;
  }

  section.style.display = "block";

  try {
    const teamRes = await fetch("/api/team");
    if (!teamRes.ok) {
      section.style.display = "none";
      return;
    }
    _teamData = await teamRes.json();
  } catch {
    section.style.display = "none";
    return;
  }

  if (_teamData.your_role === "owner") {
    await renderOwnerView();
  } else {
    renderMemberView();
  }
}

async function renderOwnerView() {
  document.getElementById("ob-team-owner-view").style.display = "block";
  document.getElementById("ob-team-member-view").style.display = "none";

  document.getElementById("ob-workspace-code").textContent = _teamData.workspace_code || "";
  document.getElementById("ob-seats-label").textContent =
    `${_teamData.seats_used} / ${_teamData.max_seats} seats in use`;

  renderMembersList(_teamData.members || []);

  try {
    const pendRes = await fetch("/api/team/pending-requests");
    if (pendRes.ok) {
      _pendingData = await pendRes.json();
      renderPendingRequests(_pendingData);
    }
  } catch {}
}

function renderMembersList(members) {
  const container = document.getElementById("ob-members-list");
  if (!container) return;
  if (!members.length) {
    container.innerHTML = '<p style="font-size:13px;color:#898780;">No members yet.</p>';
    return;
  }
  container.innerHTML = members.map(m => {
    const joined = m.joined_at
      ? new Date(m.joined_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
      : "";
    return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #F0EFEB;">
      <div>
        <span style="font-size:14px;color:#1C1B18;">${escHtml(m.email)}</span>
        ${joined ? `<span style="font-size:12px;color:#898780;margin-left:8px;">Joined ${escHtml(joined)}</span>` : ""}
      </div>
      <button class="btn-ghost" style="padding:4px 10px;font-size:12px;color:#dc2626;border-color:#fca5a5;"
              onclick="confirmRemoveMember('${escAttr(m.email)}')">Remove</button>
    </div>`;
  }).join("");
}

function renderPendingRequests(requests) {
  const section = document.getElementById("ob-pending-section");
  const list = document.getElementById("ob-pending-list");
  if (!section || !list) return;
  if (!requests.length) {
    section.style.display = "none";
    return;
  }
  section.style.display = "block";
  list.innerHTML = requests.map(r => {
    const date = r.created_at
      ? new Date(r.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
      : "";
    return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #F0EFEB;flex-wrap:wrap;gap:8px;">
      <div>
        <span style="font-size:14px;color:#1C1B18;">${escHtml(r.requester_name)}</span>
        <span style="font-size:12px;color:#898780;margin-left:6px;">${escHtml(r.requester_email)}</span>
        ${date ? `<span style="font-size:11px;color:#B0AFA9;margin-left:6px;">${escHtml(date)}</span>` : ""}
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn-ghost" style="padding:4px 12px;font-size:12px;background:#dcfce7;border-color:#86efac;color:#166534;"
                onclick="approveRequest('${escAttr(r.token)}')">Approve</button>
        <button class="btn-ghost" style="padding:4px 12px;font-size:12px;color:#dc2626;border-color:#fca5a5;"
                onclick="denyRequest('${escAttr(r.token)}')">Deny</button>
      </div>
    </div>`;
  }).join("");
}

function renderMemberView() {
  document.getElementById("ob-team-owner-view").style.display = "none";
  document.getElementById("ob-team-member-view").style.display = "block";
  const infoEl = document.getElementById("ob-member-info");
  if (infoEl && _teamData) {
    infoEl.textContent = `You're a member of ${_teamData.owner_email}'s workspace`;
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function copyWorkspaceCode() {
  const code = document.getElementById("ob-workspace-code").textContent;
  navigator.clipboard.writeText(code).catch(() => {});
  const btn = document.getElementById("ob-copy-code-btn");
  const orig = btn.textContent;
  btn.textContent = "Copied!";
  setTimeout(() => { btn.textContent = orig; }, 1800);
}

async function approveRequest(token) {
  try {
    const res = await fetch(`/api/team/approve/${token}`, { method: "POST" });
    if (res.ok) await loadTeamSection();
  } catch {}
}

async function denyRequest(token) {
  try {
    const res = await fetch(`/api/team/deny/${token}`, { method: "POST" });
    if (res.ok) await loadTeamSection();
  } catch {}
}

async function confirmRemoveMember(memberEmail) {
  if (!confirm(`Remove ${memberEmail} from the team? They will lose access.`)) return;
  try {
    const res = await fetch(`/api/team/members/${encodeURIComponent(memberEmail)}`, { method: "DELETE" });
    if (res.ok) await loadTeamSection();
  } catch {}
}

async function confirmLeaveTeam() {
  if (!confirm("Leave this team? You will lose access to Digi Agency.")) return;
  try {
    const res = await fetch("/api/team/leave", { method: "POST" });
    if (res.ok) window.location.href = "/login";
  } catch {}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escAttr(s) {
  return String(s || "").replace(/'/g, "&#39;").replace(/"/g, "&quot;");
}
