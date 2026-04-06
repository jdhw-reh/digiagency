"""
The Agency — FastAPI backend

Run with: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from routers.content_team import router as content_router
from routers.social_team import router as social_router
from routers.assistant import router as assistant_router
from routers.seo_audit import router as seo_audit_router
from routers.agency import router as agency_router
from routers.video_team import router as video_router
from routers.on_page_opt import router as on_page_opt_router
from routers.setup import router as setup_router
from routers.auth import router as auth_router
from routers.admin import router as admin_router
from routers.checkout import router as checkout_router
from routers.stripe_webhook import router as stripe_webhook_router
from routers.support import router as support_router

app = FastAPI(title="The Agency")

# ---------------------------------------------------------------------------
# Auth middleware — protect all /api/* and / routes
# ---------------------------------------------------------------------------

# Paths that are always public (no subscription check)
_PUBLIC_PATHS = {"/login", "/static", "/api/auth/register", "/api/auth/login"}

@app.middleware("http")
async def require_active_subscription(request: Request, call_next):
    path = request.url.path

    # Always allow: login page, static assets, auth endpoints, admin endpoints, health check
    if (
        path == "/login"
        or path == "/health"
        or path.startswith("/static/")
        or path.startswith("/api/auth/")
        or path.startswith("/admin")
        or path == "/"
        or path.startswith("/api/admin/")
        or path.startswith("/api/checkout/")
        or path.startswith("/api/stripe/")
    ):
        return await call_next(request)

    # For all other routes, require a valid token with active subscription
    from state import get_token_email, get_account
    token = request.cookies.get("agency_token")
    if not token:
        if path.startswith("/api/"):
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        return RedirectResponse("/login")

    email = await get_token_email(token)
    if not email:
        if path.startswith("/api/"):
            return JSONResponse({"error": "Session expired"}, status_code=401)
        return RedirectResponse("/login")

    account = await get_account(email)
    if not account or account.get("subscription_status") != "active":
        if path.startswith("/api/"):
            return JSONResponse({"error": "No active subscription"}, status_code=402)
        return RedirectResponse("/login")

    return await call_next(request)

# ---------------------------------------------------------------------------
# Static files + root
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
async def health():
    return JSONResponse({"ok": True})


@app.get("/")
async def root(request: Request):
    from state import get_token_email, get_account
    token = request.cookies.get("agency_token")
    if token:
        email = await get_token_email(token)
        if email:
            account = await get_account(email)
            if account and account.get("subscription_status") == "active":
                return RedirectResponse("/app")
    return FileResponse(str(static_dir / "landing.html"))


@app.get("/app")
async def app_page():
    return FileResponse(str(static_dir / "index.html"))


@app.get("/login")
async def login_page():
    return FileResponse(str(static_dir / "login.html"))


# ---------------------------------------------------------------------------
# Director summary — powers the home dashboard
# ---------------------------------------------------------------------------

@app.get("/api/director/summary")
async def director_summary():
    from state import redis_client, get_activity_log

    # Scan all team session keys and aggregate counts
    keys = [k async for k in redis_client.scan_iter("session:*")]
    raw_values = await redis_client.mget(keys) if keys else []
    sessions = [json.loads(v) for v in raw_values if v]

    content_saved = sum(
        len(s.get("saved_articles", []))
        for s in sessions
        if s.get("team") == "content"
    )
    social_saved = sum(
        len(s.get("saved_posts", []))
        for s in sessions
        if s.get("team") == "social"
    )
    audits_done = sum(
        1
        for s in sessions
        if s.get("team") == "seo_audit" and s.get("stage") == "done"
    )
    video_saved = sum(
        len(s.get("saved_briefs", []))
        for s in sessions
        if s.get("team") == "video"
    )
    opt_done = sum(
        1
        for s in sessions
        if s.get("team") == "on_page_opt" and s.get("stage") == "done"
    )

    activity = await get_activity_log(limit=10)

    return JSONResponse({
        "content_saved": content_saved,
        "social_saved": social_saved,
        "audits_done": audits_done,
        "video_saved": video_saved,
        "opt_done": opt_done,
        "activity": activity,
    })


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router, prefix="/api/auth")
app.include_router(admin_router)
app.include_router(content_router, prefix="/api/content")
app.include_router(social_router, prefix="/api/social")
app.include_router(assistant_router, prefix="/api/assistant")
app.include_router(seo_audit_router, prefix="/api/seo-audit")
app.include_router(agency_router, prefix="/api/agency")
app.include_router(video_router, prefix="/api/video")
app.include_router(on_page_opt_router, prefix="/api/on-page-opt")
app.include_router(setup_router, prefix="/api/setup")
app.include_router(checkout_router, prefix="/api/checkout")
app.include_router(stripe_webhook_router, prefix="/api/stripe")
app.include_router(support_router, prefix="/api/support")
