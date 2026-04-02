"""
Admin router — password-protected panel to manage user accounts.

GET  /admin                           — HTML admin panel (requires ADMIN_PASSWORD cookie)
POST /admin/login                     — set admin session cookie
POST /admin/logout                    — clear admin session cookie
GET  /api/admin/users                 — list all accounts (JSON)
GET  /api/admin/stats                 — aggregate user stats
GET  /api/admin/activity              — recent global activity log
GET  /api/admin/users/{email}/activity — per-user activity log
POST /api/admin/users/activate        — set subscription_status = active
POST /api/admin/users/revoke          — set subscription_status = cancelled
"""

import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from state import get_account, get_activity_log, get_user_activity, list_accounts, redis_client, save_account

router = APIRouter()

_ADMIN_COOKIE = "agency_admin"
_ADMIN_TOKEN_TTL = 86400 * 7  # 7 days


def _get_admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "")


async def _is_admin(cookie: str | None) -> bool:
    if not cookie:
        return False
    return bool(await redis_client.get(f"admin_session:{cookie}"))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AdminLoginPayload(BaseModel):
    password: str


class UserEmailPayload(BaseModel):
    email: str


# ---------------------------------------------------------------------------
# Admin HTML panel
# ---------------------------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return HTMLResponse(_login_page(), status_code=200)
    return HTMLResponse(_admin_page())


@router.post("/admin/login")
async def admin_login(payload: AdminLoginPayload, response: Response):
    expected = _get_admin_password()
    if not expected:
        return JSONResponse({"error": "ADMIN_PASSWORD env variable not set."}, status_code=500)
    if not secrets.compare_digest(payload.password, expected):
        return JSONResponse({"error": "Wrong password."}, status_code=401)

    token = secrets.token_urlsafe(32)
    await redis_client.setex(f"admin_session:{token}", _ADMIN_TOKEN_TTL, "1")
    response.set_cookie(
        key=_ADMIN_COOKIE,
        value=token,
        max_age=_ADMIN_TOKEN_TTL,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return {"ok": True}


@router.post("/admin/logout")
async def admin_logout(response: Response, agency_admin: str | None = Cookie(default=None)):
    if agency_admin:
        await redis_client.delete(f"admin_session:{agency_admin}")
    response.delete_cookie(_ADMIN_COOKIE)
    return RedirectResponse("/admin", status_code=303)


# ---------------------------------------------------------------------------
# JSON API (used by the admin panel via fetch)
# ---------------------------------------------------------------------------

@router.get("/api/admin/users")
async def admin_list_users(agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    accounts = await list_accounts()
    return {"users": accounts}


@router.post("/api/admin/users/activate")
async def admin_activate(payload: UserEmailPayload, agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    account = await get_account(payload.email)
    if not account:
        return JSONResponse({"error": "User not found"}, status_code=404)
    account["subscription_status"] = "active"
    await save_account(payload.email, account)
    return {"ok": True, "email": payload.email, "subscription_status": "active"}


@router.post("/api/admin/users/revoke")
async def admin_revoke(payload: UserEmailPayload, agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    account = await get_account(payload.email)
    if not account:
        return JSONResponse({"error": "User not found"}, status_code=404)
    account["subscription_status"] = "cancelled"
    await save_account(payload.email, account)
    return {"ok": True, "email": payload.email, "subscription_status": "cancelled"}


@router.get("/api/admin/stats")
async def admin_stats(agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    accounts = await list_accounts()
    now = datetime.now(timezone.utc)
    total = len(accounts)
    active = sum(1 for a in accounts if a.get("subscription_status") == "active")
    inactive = sum(1 for a in accounts if a.get("subscription_status") == "inactive")
    cancelled = sum(1 for a in accounts if a.get("subscription_status") == "cancelled")
    new_this_month = 0
    for a in accounts:
        created = a.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if dt.year == now.year and dt.month == now.month:
                    new_this_month += 1
            except ValueError:
                pass
    return {"total": total, "active": active, "inactive": inactive, "cancelled": cancelled, "new_this_month": new_this_month}


@router.get("/api/admin/activity")
async def admin_activity(agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    log = await get_activity_log(limit=20)
    return {"activity": log}


@router.get("/api/admin/users/{email}/activity")
async def admin_user_activity(email: str, agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    activity = await get_user_activity(email)
    return {"activity": activity}


# ---------------------------------------------------------------------------
# HTML templates (inline — no extra files needed)
# ---------------------------------------------------------------------------

def _login_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin — Digi Agency</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f0f0f; color: #e5e5e5;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
          padding: 40px; width: 360px; }
  h1 { font-size: 20px; margin-bottom: 8px; }
  p { color: #888; font-size: 14px; margin-bottom: 28px; }
  label { display: block; font-size: 13px; color: #aaa; margin-bottom: 6px; }
  input { width: 100%; padding: 10px 14px; background: #111; border: 1px solid #333;
          border-radius: 8px; color: #fff; font-size: 15px; outline: none; }
  input:focus { border-color: #6366f1; }
  button { margin-top: 18px; width: 100%; padding: 12px; background: #6366f1;
           color: #fff; border: none; border-radius: 8px; font-size: 15px;
           font-weight: 600; cursor: pointer; }
  button:hover { background: #4f52d6; }
  #err { color: #f87171; font-size: 13px; margin-top: 12px; min-height: 18px; }
</style>
</head>
<body>
<div class="card">
  <h1>Admin Login</h1>
  <p>Digi Agency admin panel</p>
  <label for="pw">Password</label>
  <input type="password" id="pw" placeholder="Enter admin password" autofocus>
  <button onclick="doLogin()">Sign in</button>
  <div id="err"></div>
</div>
<script>
async function doLogin() {
  const pw = document.getElementById('pw').value;
  const res = await fetch('/admin/login', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: pw}),
  });
  const data = await res.json();
  if (res.ok) { location.reload(); }
  else { document.getElementById('err').textContent = data.error || 'Login failed'; }
}
document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
</script>
</body>
</html>"""


def _admin_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin — Digi Agency</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0f0f0f; color: #e5e5e5; padding: 40px; max-width: 1400px; margin: 0 auto; }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; font-weight: 600; color: #ccc; margin-bottom: 14px; }
  .logout-btn { background: none; border: 1px solid #444; border-radius: 8px;
                color: #aaa; padding: 7px 16px; cursor: pointer; font-size: 13px; }
  .logout-btn:hover { border-color: #888; color: #fff; }

  /* Stats cards */
  .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
  .stat-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 20px 24px; }
  .stat-label { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .stat-value { font-size: 28px; font-weight: 700; color: #6366f1; }
  .stat-value.green { color: #4ade80; }
  .stat-value.gray  { color: #a8a29e; }
  .stat-value.red   { color: #f87171; }

  /* Users table */
  .section { margin-bottom: 40px; }
  table { width: 100%; border-collapse: collapse; background: #1a1a1a;
          border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden; }
  th { text-align: left; padding: 12px 16px; font-size: 12px; color: #888;
       text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #2a2a2a; }
  .sub-id { font-size: 12px; color: #666; font-family: monospace; }
  td { padding: 13px 16px; font-size: 14px; border-bottom: 1px solid #1f1f1f; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-active   { background: #14532d; color: #4ade80; }
  .badge-inactive { background: #292524; color: #a8a29e; }
  .badge-cancelled{ background: #450a0a; color: #f87171; }
  .action-btn { padding: 5px 14px; border-radius: 6px; border: none; font-size: 13px;
                font-weight: 500; cursor: pointer; margin-right: 4px; }
  .btn-activate { background: #166534; color: #4ade80; }
  .btn-activate:hover { background: #14532d; }
  .btn-revoke   { background: #7f1d1d; color: #f87171; }
  .btn-revoke:hover { background: #450a0a; }
  .btn-view { background: #1e1e2e; border: 1px solid #3a3a5c; color: #a5b4fc; font-size: 12px;
              padding: 4px 12px; border-radius: 6px; cursor: pointer; }
  .btn-view:hover { background: #2a2a4a; }
  .last-login { font-size: 13px; color: #aaa; }
  .last-login.never { color: #555; font-style: italic; }
  .empty { text-align: center; padding: 48px; color: #555; font-size: 15px; }

  /* Activity feed */
  .activity-list { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden; }
  .activity-item { display: flex; align-items: center; gap: 14px; padding: 12px 16px;
                   border-bottom: 1px solid #1f1f1f; font-size: 13px; }
  .activity-item:last-child { border-bottom: none; }
  .activity-team { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
                   padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
  .team-content    { background: #1e3a5f; color: #60a5fa; }
  .team-social     { background: #3b1d5e; color: #c084fc; }
  .team-video      { background: #1c3a2e; color: #34d399; }
  .team-seo_audit  { background: #3b2e1a; color: #fbbf24; }
  .team-on_page_opt{ background: #2a1f3d; color: #e879f9; }
  .activity-action { flex: 1; color: #ccc; }
  .activity-user { font-size: 12px; color: #666; }
  .activity-time { font-size: 12px; color: #555; white-space: nowrap; }
  .empty-activity { padding: 32px; text-align: center; color: #555; font-size: 14px; }

  /* Modal */
  .modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
                    z-index: 100; align-items: center; justify-content: center; }
  .modal-backdrop.open { display: flex; }
  .modal { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px;
           width: 560px; max-width: 95vw; max-height: 80vh; display: flex; flex-direction: column; }
  .modal-header { display: flex; align-items: center; justify-content: space-between;
                  padding: 20px 24px; border-bottom: 1px solid #2a2a2a; }
  .modal-title { font-size: 15px; font-weight: 600; }
  .modal-email { font-size: 12px; color: #666; margin-top: 2px; }
  .modal-close { background: none; border: none; color: #666; font-size: 20px; cursor: pointer; line-height: 1; }
  .modal-close:hover { color: #fff; }
  .modal-body { overflow-y: auto; padding: 8px 0; }

  /* Toast */
  .toast { position: fixed; bottom: 24px; right: 24px; background: #1a1a1a;
           border: 1px solid #333; border-radius: 10px; padding: 12px 20px;
           font-size: 14px; opacity: 0; transition: opacity 0.2s; pointer-events: none; z-index: 200; }
  .toast.show { opacity: 1; }
</style>
</head>
<body>
<header>
  <h1>✦ Digi Agency — Admin</h1>
  <form method="POST" action="/admin/logout">
    <button class="logout-btn" type="submit">Sign out</button>
  </form>
</header>

<!-- Stats cards -->
<div class="stats-row">
  <div class="stat-card">
    <div class="stat-label">Total Users</div>
    <div class="stat-value" id="stat-total">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Active</div>
    <div class="stat-value green" id="stat-active">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Inactive</div>
    <div class="stat-value gray" id="stat-inactive">—</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">New This Month</div>
    <div class="stat-value" id="stat-new">—</div>
  </div>
</div>

<!-- Users table -->
<div class="section">
  <h2>Users</h2>
  <table id="users-table">
    <thead>
      <tr>
        <th>Email</th>
        <th>Status</th>
        <th>Last Login</th>
        <th>Signed Up</th>
        <th>Stripe Sub ID</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="users-body">
      <tr><td colspan="6" class="empty">Loading…</td></tr>
    </tbody>
  </table>
</div>

<!-- Activity feed -->
<div class="section">
  <h2>Recent Activity</h2>
  <div class="activity-list" id="activity-list">
    <div class="empty-activity">Loading…</div>
  </div>
</div>

<!-- Per-user activity modal -->
<div class="modal-backdrop" id="modal" onclick="closeModalOnBackdrop(event)">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title">User Activity</div>
        <div class="modal-email" id="modal-email"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body" id="modal-body">
      <div class="empty-activity">Loading…</div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function relativeTime(isoStr) {
  if (!isoStr) return null;
  const diff = Date.now() - new Date(isoStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60)  return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60)  return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24)  return h + 'h ago';
  const d = Math.floor(h / 24);
  if (d < 30)  return d + 'd ago';
  return new Date(isoStr).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'});
}

function formatDate(isoStr) {
  if (!isoStr) return '—';
  return new Date(isoStr).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'});
}

function teamBadge(team) {
  const safe = escHtml(team || '');
  const cls = 'team-' + (team || '').replace(/[^a-z_]/gi,'');
  return `<span class="activity-team ${cls}">${safe}</span>`;
}

// ---- Stats ----
async function loadStats() {
  try {
    const res = await fetch('/api/admin/stats');
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('stat-total').textContent   = d.total;
    document.getElementById('stat-active').textContent  = d.active;
    document.getElementById('stat-inactive').textContent= d.inactive;
    document.getElementById('stat-new').textContent     = d.new_this_month;
  } catch(e) {}
}

// ---- Users ----
async function loadUsers() {
  const tbody = document.getElementById('users-body');
  try {
    const res = await fetch('/api/admin/users');
    const data = await res.json();
    if (!res.ok) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty">Error: ${escHtml(data.error || res.status)}</td></tr>`;
      return;
    }
    if (!data.users || data.users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No accounts yet.</td></tr>';
      return;
    }
    tbody.innerHTML = data.users.map(u => {
      const status   = u.subscription_status || 'inactive';
      const badgeCls = status === 'active' ? 'badge-active' : status === 'cancelled' ? 'badge-cancelled' : 'badge-inactive';
      const signedUp = formatDate(u.created_at);
      const lastLogin = u.last_login_at
        ? `<span class="last-login">${escHtml(relativeTime(u.last_login_at))}</span>`
        : '<span class="last-login never">Never</span>';
      const subId = u.stripe_subscription_id
        ? `<span class="sub-id">${escHtml(u.stripe_subscription_id)}</span>`
        : '<span style="color:#444">—</span>';
      const emailSafe = escHtml(u.email);
      return `<tr>
        <td>${emailSafe}</td>
        <td><span class="badge ${badgeCls}">${status}</span></td>
        <td>${lastLogin}</td>
        <td>${signedUp}</td>
        <td>${subId}</td>
        <td>
          <button class="action-btn btn-activate" onclick="activate('${emailSafe}')">Activate</button>
          <button class="action-btn btn-revoke"   onclick="revoke('${emailSafe}')">Revoke</button>
          <button class="btn-view"                onclick="openModal('${emailSafe}')">Activity</button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">Failed to load users: ${escHtml(e.message)}</td></tr>`;
  }
}

// ---- Activity feed ----
async function loadActivity() {
  const container = document.getElementById('activity-list');
  try {
    const res = await fetch('/api/admin/activity');
    if (!res.ok) { container.innerHTML = '<div class="empty-activity">Failed to load.</div>'; return; }
    const data = await res.json();
    if (!data.activity || data.activity.length === 0) {
      container.innerHTML = '<div class="empty-activity">No activity recorded yet.</div>';
      return;
    }
    container.innerHTML = data.activity.map(a => {
      const userHtml = a.email ? `<span class="activity-user">${escHtml(a.email)}</span>` : '';
      return `<div class="activity-item">
        ${teamBadge(a.team)}
        <span class="activity-action">${escHtml(a.action)}</span>
        ${userHtml}
        <span class="activity-time">${escHtml(relativeTime(a.ts) || a.ts)}</span>
      </div>`;
    }).join('');
  } catch(e) {
    container.innerHTML = '<div class="empty-activity">Failed to load activity.</div>';
  }
}

// ---- Toast ----
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ---- Activate / Revoke ----
async function activate(email) {
  const res = await fetch('/api/admin/users/activate', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email}),
  });
  if (res.ok) { showToast(email + ' activated'); loadUsers(); loadStats(); }
  else { showToast('Error activating ' + email); }
}

async function revoke(email) {
  if (!confirm('Revoke access for ' + email + '?')) return;
  const res = await fetch('/api/admin/users/revoke', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email}),
  });
  if (res.ok) { showToast(email + ' revoked'); loadUsers(); loadStats(); }
  else { showToast('Error revoking ' + email); }
}

// ---- Per-user activity modal ----
async function openModal(email) {
  document.getElementById('modal-email').textContent = email;
  document.getElementById('modal-body').innerHTML = '<div class="empty-activity">Loading…</div>';
  document.getElementById('modal').classList.add('open');
  try {
    const res = await fetch('/api/admin/users/' + encodeURIComponent(email) + '/activity');
    const data = await res.json();
    if (!data.activity || data.activity.length === 0) {
      document.getElementById('modal-body').innerHTML = '<div class="empty-activity">No activity recorded for this user yet.</div>';
      return;
    }
    document.getElementById('modal-body').innerHTML = data.activity.map(a => `
      <div class="activity-item">
        ${teamBadge(a.team)}
        <span class="activity-action">${escHtml(a.action)}</span>
        <span class="activity-time">${escHtml(relativeTime(a.ts) || a.ts)}</span>
      </div>`).join('');
  } catch(e) {
    document.getElementById('modal-body').innerHTML = '<div class="empty-activity">Failed to load.</div>';
  }
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

function closeModalOnBackdrop(e) {
  if (e.target === document.getElementById('modal')) closeModal();
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ---- Init ----
loadStats();
loadUsers();
loadActivity();
</script>
</body>
</html>"""
