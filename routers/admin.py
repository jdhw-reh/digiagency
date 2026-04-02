"""
Admin router — password-protected panel to manage user accounts.

GET  /admin                      — HTML admin panel (requires ADMIN_PASSWORD cookie)
POST /admin/login                — set admin session cookie
POST /admin/logout               — clear admin session cookie
GET  /api/admin/users            — list all accounts (JSON)
POST /api/admin/users/activate   — set subscription_status = active
POST /api/admin/users/revoke     — set subscription_status = cancelled
"""

import os
import secrets

from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from state import get_account, list_accounts, save_account

router = APIRouter()

_ADMIN_COOKIE = "agency_admin"
_ADMIN_TOKEN_TTL = 86400 * 7  # 7 days

# In-memory set of valid admin session tokens (small enough; server restarts = re-login)
_admin_sessions: set[str] = set()


def _get_admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "")


def _is_admin(cookie: str | None) -> bool:
    return bool(cookie and cookie in _admin_sessions)


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
    if not _is_admin(agency_admin):
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
    _admin_sessions.add(token)
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
        _admin_sessions.discard(agency_admin)
    response.delete_cookie(_ADMIN_COOKIE)
    return RedirectResponse("/admin", status_code=303)


# ---------------------------------------------------------------------------
# JSON API (used by the admin panel via fetch)
# ---------------------------------------------------------------------------

@router.get("/api/admin/users")
async def admin_list_users(agency_admin: str | None = Cookie(default=None)):
    if not _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    accounts = await list_accounts()
    return {"users": accounts}


@router.post("/api/admin/users/activate")
async def admin_activate(payload: UserEmailPayload, agency_admin: str | None = Cookie(default=None)):
    if not _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    account = await get_account(payload.email)
    if not account:
        return JSONResponse({"error": "User not found"}, status_code=404)
    account["subscription_status"] = "active"
    await save_account(payload.email, account)
    return {"ok": True, "email": payload.email, "subscription_status": "active"}


@router.post("/api/admin/users/revoke")
async def admin_revoke(payload: UserEmailPayload, agency_admin: str | None = Cookie(default=None)):
    if not _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    account = await get_account(payload.email)
    if not account:
        return JSONResponse({"error": "User not found"}, status_code=404)
    account["subscription_status"] = "cancelled"
    await save_account(payload.email, account)
    return {"ok": True, "email": payload.email, "subscription_status": "cancelled"}


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
  body { font-family: system-ui, sans-serif; background: #0f0f0f; color: #e5e5e5; padding: 40px; }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; }
  h1 { font-size: 22px; }
  .logout-btn { background: none; border: 1px solid #444; border-radius: 8px;
                color: #aaa; padding: 7px 16px; cursor: pointer; font-size: 13px; }
  .logout-btn:hover { border-color: #888; color: #fff; }
  table { width: 100%; border-collapse: collapse; background: #1a1a1a;
          border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden; }
  th { text-align: left; padding: 12px 16px; font-size: 12px; color: #888;
       text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #2a2a2a; }
  td { padding: 13px 16px; font-size: 14px; border-bottom: 1px solid #1f1f1f; }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 20px;
           font-size: 12px; font-weight: 600; }
  .badge-active   { background: #14532d; color: #4ade80; }
  .badge-inactive { background: #292524; color: #a8a29e; }
  .badge-cancelled{ background: #450a0a; color: #f87171; }
  .action-btn { padding: 5px 14px; border-radius: 6px; border: none; font-size: 13px;
                font-weight: 500; cursor: pointer; margin-right: 6px; }
  .btn-activate { background: #166534; color: #4ade80; }
  .btn-activate:hover { background: #14532d; }
  .btn-revoke   { background: #7f1d1d; color: #f87171; }
  .btn-revoke:hover { background: #450a0a; }
  .toast { position: fixed; bottom: 24px; right: 24px; background: #1a1a1a;
           border: 1px solid #333; border-radius: 10px; padding: 12px 20px;
           font-size: 14px; opacity: 0; transition: opacity 0.2s; pointer-events: none; }
  .toast.show { opacity: 1; }
  .empty { text-align: center; padding: 48px; color: #555; font-size: 15px; }
</style>
</head>
<body>
<header>
  <h1>✦ Digi Agency — Admin</h1>
  <form method="POST" action="/admin/logout">
    <button class="logout-btn" type="submit">Sign out</button>
  </form>
</header>

<table id="users-table">
  <thead>
    <tr>
      <th>Email</th>
      <th>Status</th>
      <th>Signed up</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody id="users-body">
    <tr><td colspan="4" class="empty">Loading…</td></tr>
  </tbody>
</table>

<div class="toast" id="toast"></div>

<script>
async function loadUsers() {
  const res = await fetch('/api/admin/users');
  const data = await res.json();
  const tbody = document.getElementById('users-body');
  if (!data.users || data.users.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">No accounts yet.</td></tr>';
    return;
  }
  tbody.innerHTML = data.users.map(u => {
    const status = u.subscription_status || 'inactive';
    const badgeClass = status === 'active' ? 'badge-active' : status === 'cancelled' ? 'badge-cancelled' : 'badge-inactive';
    const date = u.created_at ? new Date(u.created_at).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'}) : '—';
    return `<tr>
      <td>${escHtml(u.email)}</td>
      <td><span class="badge ${badgeClass}">${status}</span></td>
      <td>${date}</td>
      <td>
        <button class="action-btn btn-activate" onclick="activate('${escHtml(u.email)}')">Activate</button>
        <button class="action-btn btn-revoke"   onclick="revoke('${escHtml(u.email)}')">Revoke</button>
      </td>
    </tr>`;
  }).join('');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

async function activate(email) {
  const res = await fetch('/api/admin/users/activate', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email}),
  });
  if (res.ok) { showToast(email + ' activated'); loadUsers(); }
  else { showToast('Error activating ' + email); }
}

async function revoke(email) {
  if (!confirm('Revoke access for ' + email + '?')) return;
  const res = await fetch('/api/admin/users/revoke', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email}),
  });
  if (res.ok) { showToast(email + ' revoked'); loadUsers(); }
  else { showToast('Error revoking ' + email); }
}

loadUsers();
</script>
</body>
</html>"""
