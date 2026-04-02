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

import asyncio
import os
import secrets
from datetime import datetime, timedelta, timezone

import stripe as _stripe
from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from state import (
    get_account,
    get_activity_log,
    get_admin_note,
    get_analytics_counters,
    get_user_activity,
    list_accounts,
    list_accounts_enriched,
    redis_client,
    save_account,
    save_admin_note,
)

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


class NotePayload(BaseModel):
    note: str


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
    accounts = await list_accounts_enriched()
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


@router.get("/api/admin/analytics")
async def admin_analytics(agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    accounts = await list_accounts()
    counters = await get_analytics_counters()

    # Signup trend — last 8 weeks, oldest→newest
    now = datetime.now(timezone.utc)
    signup_trend = []
    for i in range(7, -1, -1):
        week_start = now - timedelta(weeks=i + 1)
        week_end = now - timedelta(weeks=i)
        count = 0
        for a in accounts:
            created = a.get("created_at", "")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if week_start <= dt < week_end:
                        count += 1
                except ValueError:
                    pass
        label = week_start.strftime("%-d %b")
        signup_trend.append({"label": label, "count": count})

    return {**counters, "signup_trend": signup_trend}


@router.get("/api/admin/billing")
async def admin_billing(agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    stripe_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_key:
        return {"available": False, "reason": "STRIPE_SECRET_KEY not set"}

    def _fetch():
        _stripe.api_key = stripe_key
        subs = _stripe.Subscription.list(status="active", limit=100, expand=["data.items.data.price"])
        mrr_cents = 0
        for sub in subs.auto_paging_iter():
            for item in sub["items"]["data"]:
                price = item.get("price") or {}
                amount = price.get("unit_amount") or 0
                interval = (price.get("recurring") or {}).get("interval", "month")
                mrr_cents += amount // 12 if interval == "year" else amount

        import time
        since = int(time.time()) - 30 * 86400
        failed = list(
            _stripe.Invoice.list(status="open", created={"gte": since}, limit=100).auto_paging_iter()
        )
        return {"mrr_cents": mrr_cents, "failed_30d": len(failed)}

    try:
        result = await asyncio.to_thread(_fetch)
        return {
            "available": True,
            "mrr": round(result["mrr_cents"] / 100, 2),
            "failed_30d": result["failed_30d"],
        }
    except Exception as exc:
        return {"available": True, "mrr": None, "failed_30d": None, "error": str(exc)}


@router.get("/api/admin/users/{email}/note")
async def admin_get_note(email: str, agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    note = await get_admin_note(email)
    return {"note": note}


@router.post("/api/admin/users/{email}/note")
async def admin_save_note(email: str, payload: NotePayload, agency_admin: str | None = Cookie(default=None)):
    if not await _is_admin(agency_admin):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    await save_admin_note(email, payload.note)
    return {"ok": True}


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
  body { font-family: system-ui, sans-serif; background: #002451; color: #ffffff;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: #00346e; border: 1px solid #0d4a8a; border-radius: 12px;
          padding: 40px; width: 360px; }
  h1 { font-size: 20px; margin-bottom: 8px; }
  p { color: #7285b7; font-size: 14px; margin-bottom: 28px; }
  label { display: block; font-size: 13px; color: #bbdaff; margin-bottom: 6px; }
  input { width: 100%; padding: 10px 14px; background: #001a40; border: 1px solid #1a5a9a;
          border-radius: 8px; color: #fff; font-size: 15px; outline: none; }
  input:focus { border-color: #5ba3ff; }
  button { margin-top: 18px; width: 100%; padding: 12px; background: #5ba3ff;
           color: #fff; border: none; border-radius: 8px; font-size: 15px;
           font-weight: 600; cursor: pointer; }
  button:hover { background: #3d8fe0; }
  #err { color: #ff9da4; font-size: 13px; margin-top: 12px; min-height: 18px; }
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
  body { font-family: system-ui, sans-serif; background: #002451; color: #ffffff; padding: 40px; max-width: 1400px; margin: 0 auto; }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; font-weight: 600; color: #e8f4ff; margin-bottom: 14px; }
  .logout-btn { background: none; border: 1px solid #2a6aaa; border-radius: 8px;
                color: #bbdaff; padding: 7px 16px; cursor: pointer; font-size: 13px; }
  .logout-btn:hover { border-color: #7285b7; color: #fff; }

  /* Stats cards */
  .stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 32px; }
  .stat-card { background: #00346e; border: 1px solid #0d4a8a; border-radius: 12px; padding: 20px 24px; }
  .stat-label { font-size: 12px; color: #4d6b9a; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .stat-value { font-size: 28px; font-weight: 700; color: #5ba3ff; }
  .stat-value.green { color: #d1f1a9; }
  .stat-value.gray  { color: #7285b7; }
  .stat-value.red   { color: #ff9da4; }

  /* Analytics charts */
  .analytics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 40px; }
  .analytics-grid-wide { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-bottom: 40px; }
  .chart-card { background: #00346e; border: 1px solid #0d4a8a; border-radius: 12px; padding: 20px 24px; }
  .chart-empty { color: #4a7aa0; font-size: 13px; padding: 16px 0; }
  /* Team usage bars */
  .bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .bar-label { font-size: 12px; color: #7285b7; width: 80px; flex-shrink: 0; }
  .bar-track { flex: 1; background: #001a40; border-radius: 4px; height: 8px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width 0.4s ease; }
  .bar-count { font-size: 12px; color: #4d6b9a; width: 28px; text-align: right; flex-shrink: 0; }
  /* Signup trend / weekday bars */
  .trend-bars { display: flex; align-items: flex-end; gap: 4px; height: 80px; }
  .trend-col { display: flex; flex-direction: column; align-items: center; flex: 1; height: 100%; }
  .trend-bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; }
  .trend-bar { width: 100%; min-height: 2px; background: #5ba3ff; border-radius: 3px 3px 0 0;
               font-size: 10px; color: #bbdaff; display: flex; align-items: flex-start;
               justify-content: center; padding-top: 2px; transition: height 0.4s ease; }
  .trend-label { font-size: 10px; color: #4a7aa0; margin-top: 4px; white-space: nowrap; }
  /* Hour heatmap */
  .heatmap-grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px; }
  .heat-cell { border-radius: 4px; padding: 4px 2px; text-align: center; cursor: default; }
  .heat-label { font-size: 9px; color: #bbdaff; display: block; }
  #chart-weekdays { display: flex; align-items: flex-end; gap: 6px; height: 80px; }
  #chart-hours { display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px; }
  .chart-section-label { font-size: 11px; color: #4a7aa0; margin-bottom: 8px; }

  /* Users table */
  .section { margin-bottom: 40px; }
  table { width: 100%; border-collapse: collapse; background: #00346e;
          border: 1px solid #0d4a8a; border-radius: 12px; overflow: hidden; }
  th { text-align: left; padding: 12px 16px; font-size: 12px; color: #7285b7;
       text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #0d4a8a; }
  .sub-id { font-size: 12px; color: #4d6b9a; font-family: monospace; }
  td { padding: 13px 16px; font-size: 14px; border-bottom: 1px solid #003060; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-active   { background: #0a2a10; color: #d1f1a9; }
  .badge-inactive { background: #00214d; color: #7285b7; }
  .badge-cancelled{ background: #3d0a10; color: #ff9da4; }
  .action-btn { padding: 5px 14px; border-radius: 6px; border: none; font-size: 13px;
                font-weight: 500; cursor: pointer; margin-right: 4px; }
  .btn-activate { background: #0a3a15; color: #d1f1a9; }
  .btn-activate:hover { background: #0a2a10; }
  .btn-revoke   { background: #4d0a10; color: #ff9da4; }
  .btn-revoke:hover { background: #3d0a10; }
  .btn-view { background: #001d3d; border: 1px solid #1a5a9a; color: #bbdaff; font-size: 12px;
              padding: 4px 12px; border-radius: 6px; cursor: pointer; }
  .btn-view:hover { background: #003060; }
  .ts-cell { font-size: 13px; color: #bbdaff; }
  .ts-cell.never { color: #4a7aa0; font-style: italic; }
  .setup-yes { color: #d1f1a9; font-size: 14px; }
  .setup-no  { color: #4a7aa0;    font-size: 14px; }
  .count-badge { display: inline-block; background: #001d3d; border: 1px solid #1a5a9a;
                 border-radius: 20px; font-size: 11px; color: #7285b7; padding: 1px 8px; }
  .churn-row td:first-child { border-left: 3px solid #ffc58f; }
  .churn-badge { display: inline-block; background: #2d1000; color: #ffc58f;
                 font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 4px;
                 margin-left: 6px; vertical-align: middle; }
  .empty { text-align: center; padding: 48px; color: #4a7aa0; font-size: 15px; }

  /* Table controls (search / filter / export) */
  .table-controls { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .table-controls input { flex: 1; max-width: 280px; padding: 8px 12px; background: #00346e;
    border: 1px solid #1a5a9a; border-radius: 8px; color: #ffffff; font-size: 13px; outline: none; }
  .table-controls input:focus { border-color: #5ba3ff; }
  .table-controls select { padding: 8px 12px; background: #00346e; border: 1px solid #1a5a9a;
    border-radius: 8px; color: #ffffff; font-size: 13px; outline: none; cursor: pointer; }
  .table-controls select:focus { border-color: #5ba3ff; }
  .export-btn { padding: 8px 16px; background: #00346e; border: 1px solid #2a6aaa;
    border-radius: 8px; color: #bbdaff; font-size: 13px; cursor: pointer; margin-left: auto; }
  .export-btn:hover { border-color: #7285b7; color: #fff; }
  .btn-stripe { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 12px;
    background: #001530; border: 1px solid #0d5a9a; color: #bbdaff; text-decoration: none; }
  .btn-stripe:hover { background: #001d4a; }

  /* Admin notes (inside modal) */
  .notes-section { padding: 16px 24px; border-top: 1px solid #0d4a8a; }
  .notes-label { font-size: 12px; color: #4d6b9a; text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 8px; }
  .notes-textarea { width: 100%; background: #001a40; border: 1px solid #1a5a9a; border-radius: 8px;
    color: #ffffff; font-size: 13px; padding: 10px 12px; resize: vertical; min-height: 72px;
    font-family: inherit; outline: none; }
  .notes-textarea:focus { border-color: #5ba3ff; }
  .notes-save { margin-top: 8px; padding: 7px 18px; background: #5ba3ff; border: none;
    border-radius: 7px; color: #002451; font-size: 13px; font-weight: 700; cursor: pointer; }
  .notes-save:hover { background: #3d8fe0; color: #ffffff; }
  .notes-saved { color: #d1f1a9; font-size: 12px; margin-left: 10px; opacity: 0;
    transition: opacity 0.3s; }

  /* Activity feed */
  .activity-list { background: #00346e; border: 1px solid #0d4a8a; border-radius: 12px; overflow: hidden; }
  .activity-item { display: flex; align-items: center; gap: 14px; padding: 12px 16px;
                   border-bottom: 1px solid #003060; font-size: 13px; }
  .activity-item:last-child { border-bottom: none; }
  .activity-team { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
                   padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
  .team-content    { background: #001d4a; color: #bbdaff; }
  .team-social     { background: #1a0040; color: #ebbbff; }
  .team-video      { background: #001a15; color: #99ffff; }
  .team-seo_audit  { background: #2a1800; color: #ffeead; }
  .team-on_page_opt{ background: #150040; color: #ebbbff; }
  .activity-action { flex: 1; color: #e8f4ff; }
  .activity-user { font-size: 12px; color: #4d6b9a; }
  .activity-time { font-size: 12px; color: #4a7aa0; white-space: nowrap; }
  .empty-activity { padding: 32px; text-align: center; color: #4a7aa0; font-size: 14px; }

  /* Modal */
  .modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
                    z-index: 100; align-items: center; justify-content: center; }
  .modal-backdrop.open { display: flex; }
  .modal { background: #00346e; border: 1px solid #0d4a8a; border-radius: 14px;
           width: 560px; max-width: 95vw; max-height: 80vh; display: flex; flex-direction: column; }
  .modal-header { display: flex; align-items: center; justify-content: space-between;
                  padding: 20px 24px; border-bottom: 1px solid #0d4a8a; }
  .modal-title { font-size: 15px; font-weight: 600; }
  .modal-email { font-size: 12px; color: #4d6b9a; margin-top: 2px; }
  .modal-close { background: none; border: none; color: #4d6b9a; font-size: 20px; cursor: pointer; line-height: 1; }
  .modal-close:hover { color: #fff; }
  .modal-body { overflow-y: auto; padding: 8px 0; }

  /* Toast */
  .toast { position: fixed; bottom: 24px; right: 24px; background: #00346e;
           border: 1px solid #1a5a9a; border-radius: 10px; padding: 12px 20px;
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
  <div class="stat-card">
    <div class="stat-label">MRR <span id="stat-failed" style="font-size:11px;color:#ff9da4;margin-left:6px;display:none"></span></div>
    <div class="stat-value green" id="stat-mrr">—</div>
  </div>
</div>

<!-- Analytics -->
<div class="analytics-grid-wide">
  <div class="chart-card">
    <h2>Feature Usage</h2>
    <div id="chart-teams"><div class="chart-empty">Loading…</div></div>
  </div>
  <div class="chart-card">
    <h2>Signups — Last 8 Weeks</h2>
    <div class="trend-bars" id="chart-trend"></div>
  </div>
</div>
<div class="analytics-grid">
  <div class="chart-card">
    <h2>Activity by Hour of Day</h2>
    <div class="chart-section-label">All time · UTC</div>
    <div id="chart-hours"></div>
  </div>
  <div class="chart-card">
    <h2>Activity by Day of Week</h2>
    <div class="chart-section-label">All time · UTC</div>
    <div id="chart-weekdays"></div>
  </div>
</div>

<!-- Users table -->
<div class="section">
  <h2>Users</h2>
  <div class="table-controls">
    <input type="text" id="search-input" placeholder="Search by email…" oninput="filterTable()">
    <select id="status-filter" onchange="filterTable()">
      <option value="">All statuses</option>
      <option value="active">Active</option>
      <option value="inactive">Inactive</option>
      <option value="cancelled">Cancelled</option>
    </select>
    <button class="export-btn" onclick="exportCSV()">Export CSV</button>
  </div>
  <table id="users-table">
    <thead>
      <tr>
        <th>Email</th>
        <th>Status</th>
        <th>Setup</th>
        <th>Signed Up</th>
        <th>Last Login</th>
        <th>Last Active</th>
        <th>Activity</th>
        <th>Manage</th>
      </tr>
    </thead>
    <tbody id="users-body">
      <tr><td colspan="8" class="empty">Loading…</td></tr>
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
    <div class="notes-section">
      <div class="notes-label">Admin Notes</div>
      <textarea class="notes-textarea" id="notes-textarea" placeholder="Private notes about this user…"></textarea>
      <div style="display:flex;align-items:center">
        <button class="notes-save" onclick="saveNote()">Save Note</button>
        <span class="notes-saved" id="notes-saved">Saved</span>
      </div>
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
      tbody.innerHTML = `<tr><td colspan="8" class="empty">Error: ${escHtml(data.error || res.status)}</td></tr>`;
      return;
    }
    if (!data.users || data.users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">No accounts yet.</td></tr>';
      return;
    }
    window._allUsers = data.users;
    renderUsers(data.users);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">Failed to load users: ${escHtml(e.message)}</td></tr>`;
  }
}

function renderUsers(users) {
  const tbody = document.getElementById('users-body');
  if (!users || users.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">No matching users.</td></tr>';
    return;
  }
  tbody.innerHTML = users.map(u => {
    const status    = u.subscription_status || 'inactive';
    const badgeCls  = status === 'active' ? 'badge-active' : status === 'cancelled' ? 'badge-cancelled' : 'badge-inactive';
    const signedUp  = formatDate(u.created_at);
    const lastLogin = u.last_login_at
      ? `<span class="ts-cell">${escHtml(relativeTime(u.last_login_at))}</span>`
      : '<span class="ts-cell never">Never</span>';
    const lastActive = u.last_activity_at
      ? `<span class="ts-cell">${escHtml(relativeTime(u.last_activity_at))}</span>`
      : '<span class="ts-cell never">Never</span>';
    const setupHtml  = u.setup_complete
      ? '<span class="setup-yes" title="API key configured">&#x2713;</span>'
      : '<span class="setup-no"  title="Not set up">&#x2717;</span>';
    const countHtml  = `<span class="count-badge">${u.activity_count || 0}</span>`;
    const churnHtml  = u.is_churn_risk ? '<span class="churn-badge">At risk</span>' : '';
    const emailSafe  = escHtml(u.email);
    const rowCls     = u.is_churn_risk ? 'churn-row' : '';
    const stripeLink = u.stripe_customer_id
      ? `<a class="btn-stripe" href="https://dashboard.stripe.com/customers/${escHtml(u.stripe_customer_id)}" target="_blank" rel="noopener">Stripe &#x2197;</a>`
      : '';
    return `<tr class="${rowCls}" data-email="${emailSafe}" data-status="${status}">
      <td>${emailSafe}${churnHtml}</td>
      <td><span class="badge ${badgeCls}">${status}</span></td>
      <td>${setupHtml}</td>
      <td>${signedUp}</td>
      <td>${lastLogin}</td>
      <td>${lastActive}</td>
      <td>${countHtml}</td>
      <td>
        <button class="action-btn btn-activate" onclick="activate('${emailSafe}')">Activate</button>
        <button class="action-btn btn-revoke"   onclick="revoke('${emailSafe}')">Revoke</button>
        <button class="btn-view"                onclick="openModal('${emailSafe}')">Activity</button>
        ${stripeLink}
      </td>
    </tr>`;
  }).join('');
}

function filterTable() {
  const query  = document.getElementById('search-input').value.toLowerCase();
  const status = document.getElementById('status-filter').value;
  const users  = (window._allUsers || []).filter(u => {
    const emailMatch  = !query  || (u.email || '').toLowerCase().includes(query);
    const statusMatch = !status || (u.subscription_status || 'inactive') === status;
    return emailMatch && statusMatch;
  });
  renderUsers(users);
}

function exportCSV() {
  const users = window._allUsers || [];
  if (!users.length) { showToast('No data to export'); return; }
  const cols = ['email','subscription_status','setup_complete','activity_count','created_at','last_login_at','last_activity_at','stripe_customer_id'];
  const header = cols.join(',');
  const rows = users.map(u =>
    cols.map(c => {
      const v = u[c] == null ? '' : String(u[c]);
      return v.includes(',') || v.includes('"') ? '"' + v.replace(/"/g, '""') + '"' : v;
    }).join(',')
  );
  const csv = [header, ...rows].join('\\n');
  const blob = new Blob([csv], {type: 'text/csv'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'users.csv'; a.click();
  URL.revokeObjectURL(url);
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

// ---- Billing ----
async function loadBilling() {
  try {
    const res = await fetch('/api/admin/billing');
    if (!res.ok) return;
    const d = await res.json();
    if (!d.available) return;
    const mrr = document.getElementById('stat-mrr');
    const failedEl = document.getElementById('stat-failed');
    if (d.mrr != null) {
      mrr.textContent = '$' + d.mrr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    } else {
      mrr.textContent = d.error ? 'Error' : '—';
    }
    if (d.failed_30d != null && d.failed_30d > 0) {
      failedEl.textContent = d.failed_30d + ' failed';
      failedEl.style.display = 'inline';
    }
  } catch(e) {}
}

// ---- Per-user activity modal ----
let _modalEmail = '';

async function openModal(email) {
  _modalEmail = email;
  document.getElementById('modal-email').textContent = email;
  document.getElementById('modal-body').innerHTML = '<div class="empty-activity">Loading…</div>';
  document.getElementById('notes-textarea').value = '';
  document.getElementById('notes-saved').style.opacity = '0';
  document.getElementById('modal').classList.add('open');
  try {
    const [actRes, noteRes] = await Promise.all([
      fetch('/api/admin/users/' + encodeURIComponent(email) + '/activity'),
      fetch('/api/admin/users/' + encodeURIComponent(email) + '/note'),
    ]);
    const actData  = await actRes.json();
    const noteData = await noteRes.json();
    if (!actData.activity || actData.activity.length === 0) {
      document.getElementById('modal-body').innerHTML = '<div class="empty-activity">No activity recorded for this user yet.</div>';
    } else {
      document.getElementById('modal-body').innerHTML = actData.activity.map(a => `
        <div class="activity-item">
          ${teamBadge(a.team)}
          <span class="activity-action">${escHtml(a.action)}</span>
          <span class="activity-time">${escHtml(relativeTime(a.ts) || a.ts)}</span>
        </div>`).join('');
    }
    document.getElementById('notes-textarea').value = noteData.note || '';
  } catch(e) {
    document.getElementById('modal-body').innerHTML = '<div class="empty-activity">Failed to load.</div>';
  }
}

async function saveNote() {
  const note = document.getElementById('notes-textarea').value;
  const savedEl = document.getElementById('notes-saved');
  try {
    const res = await fetch('/api/admin/users/' + encodeURIComponent(_modalEmail) + '/note', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note}),
    });
    if (res.ok) {
      savedEl.style.opacity = '1';
      setTimeout(() => { savedEl.style.opacity = '0'; }, 2000);
    }
  } catch(e) {}
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

function closeModalOnBackdrop(e) {
  if (e.target === document.getElementById('modal')) closeModal();
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ---- Analytics ----
async function loadAnalytics() {
  try {
    const res = await fetch('/api/admin/analytics');
    if (!res.ok) return;
    const d = await res.json();
    renderTeamUsage(d.team_usage || {});
    renderSignupTrend(d.signup_trend || []);
    renderHourHeatmap(d.activity_by_hour || []);
    renderWeekdayChart(d.activity_by_weekday || []);
  } catch(e) {}
}

const TEAM_LABELS = {
  content: 'Content', social: 'Social', video: 'Video',
  seo_audit: 'SEO Audit', on_page_opt: 'On-Page'
};
const TEAM_COLORS = {
  content: '#bbdaff', social: '#ebbbff', video: '#99ffff',
  seo_audit: '#ffeead', on_page_opt: '#ebbbff'
};

function renderTeamUsage(data) {
  const max = Math.max(...Object.values(data), 1);
  const total = Object.values(data).reduce((s, v) => s + v, 0);
  const el = document.getElementById('chart-teams');
  if (total === 0) { el.innerHTML = '<div class="chart-empty">No activity yet</div>'; return; }
  el.innerHTML = Object.entries(TEAM_LABELS).map(([key, label]) => {
    const val = data[key] || 0;
    const pct = (val / max * 100).toFixed(1);
    const color = TEAM_COLORS[key] || '#5ba3ff';
    return `<div class="bar-row">
      <div class="bar-label">${label}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <div class="bar-count">${val}</div>
    </div>`;
  }).join('');
}

function renderSignupTrend(data) {
  const max = Math.max(...data.map(d => d.count), 1);
  const el = document.getElementById('chart-trend');
  el.innerHTML = data.map(d => {
    const h = max > 0 ? (d.count / max * 100).toFixed(1) : 0;
    return `<div class="trend-col">
      <div class="trend-bar-wrap">
        <div class="trend-bar" style="height:${h}%" title="${d.count} signups">${d.count > 0 ? d.count : ''}</div>
      </div>
      <div class="trend-label">${escHtml(d.label)}</div>
    </div>`;
  }).join('');
}

function renderHourHeatmap(data) {
  const max = Math.max(...data, 1);
  const labels = [...Array(24).keys()].map(h => h === 0 ? '12am' : h < 12 ? h+'am' : h === 12 ? '12pm' : (h-12)+'pm');
  const el = document.getElementById('chart-hours');
  el.innerHTML = data.map((v, i) => {
    const alpha = max > 0 ? (0.08 + (v / max) * 0.9).toFixed(2) : 0.08;
    return `<div class="heat-cell" style="background:rgba(91,163,255,${alpha})" title="${labels[i]}: ${v} actions">
      <span class="heat-label">${labels[i]}</span>
    </div>`;
  }).join('');
}

function renderWeekdayChart(data) {
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const max = Math.max(...data, 1);
  const el = document.getElementById('chart-weekdays');
  el.innerHTML = data.map((v, i) => {
    const h = max > 0 ? (v / max * 100).toFixed(1) : 0;
    return `<div class="trend-col">
      <div class="trend-bar-wrap">
        <div class="trend-bar" style="height:${h}%;background:#5ba3ff" title="${days[i]}: ${v} actions">${v > 0 ? v : ''}</div>
      </div>
      <div class="trend-label">${days[i]}</div>
    </div>`;
  }).join('');
}

// ---- Init ----
loadStats();
loadUsers();
loadActivity();
loadAnalytics();
loadBilling();
</script>
</body>
</html>"""
