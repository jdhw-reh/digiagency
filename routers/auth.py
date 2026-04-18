"""
Auth router — email/password registration and login.

POST /api/auth/register   — create account (status: inactive until manually activated or Stripe webhook)
POST /api/auth/login      — returns auth token
POST /api/auth/logout     — deletes auth token
GET  /api/auth/me         — returns account info for the current token
"""

import asyncio
import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from utils.csrf import (
    create_csrf_token,
    delete_csrf_cookie,
    delete_csrf_token,
    set_csrf_cookie,
    verify_csrf_token,
)

# Cookies must be sent over HTTPS only.  Railway enforces TLS in production, so
# secure=True is always correct there.  Local dev can set ENVIRONMENT=development
# to allow the cookie over plain HTTP (e.g. http://localhost:8000).
_SECURE_COOKIES = os.getenv("ENVIRONMENT", "production") != "development"

from state import (
    create_auth_token,
    create_join_request,
    delete_auth_token,
    get_account,
    get_join_request,
    get_member_count,
    get_team,
    get_token_email,
    hash_password,
    redis_client,
    save_account,
    verify_password,
)
from services.email import send_join_request_email, send_password_reset_email, send_welcome_email

_PWD_RESET_TTL = 3600  # 1 hour

router = APIRouter()

_COOKIE = "agency_token"
_COOKIE_MAX_AGE = 86400 * 30  # 30 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_token_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_SECURE_COOKIES,  # True in production (Railway enforces HTTPS); False only when ENVIRONMENT=development
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AuthPayload(BaseModel):
    email: str
    password: str


class ForgotPasswordPayload(BaseModel):
    email: str


class ResetPasswordPayload(BaseModel):
    token: str
    new_password: str


class TeamMemberRegisterPayload(BaseModel):
    workspace_code: str
    name: str
    email: str
    password: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/register")
async def register(payload: AuthPayload, response: Response):
    email = payload.email.lower().strip()
    password = payload.password.strip()

    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters."}, status_code=400)

    existing = await get_account(email)
    if existing:
        return JSONResponse({"error": "An account with that email already exists."}, status_code=409)

    account = {
        "email": email,
        "password_hash": hash_password(password),
        "subscription_status": "inactive",  # activated manually or via Stripe webhook
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await save_account(email, account)

    token = await create_auth_token(email)
    _set_token_cookie(response, token)
    csrf_token = await create_csrf_token(token)
    set_csrf_cookie(response, csrf_token)

    asyncio.create_task(send_welcome_email(email))

    return {"ok": True, "email": email, "subscription_status": "inactive"}


@router.post("/login")
async def login(payload: AuthPayload, response: Response):
    email = payload.email.lower().strip()

    account = await get_account(email)
    if not account or not verify_password(payload.password.strip(), account["password_hash"]):
        return JSONResponse({"error": "Incorrect email or password."}, status_code=401)

    account["last_login_at"] = datetime.now(timezone.utc).isoformat()
    await save_account(email, account)

    token = await create_auth_token(email)
    _set_token_cookie(response, token)
    csrf_token = await create_csrf_token(token)
    set_csrf_cookie(response, csrf_token)

    return {
        "ok": True,
        "email": email,
        "subscription_status": account.get("subscription_status", "inactive"),
    }


@router.post("/logout")
async def logout(response: Response, agency_token: str | None = Cookie(default=None)):
    if agency_token:
        await delete_auth_token(agency_token)
        await delete_csrf_token(agency_token)
    response.delete_cookie(_COOKIE)
    delete_csrf_cookie(response)
    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordPayload):
    email = payload.email.lower().strip()
    account = await get_account(email)
    if account:
        token = secrets.token_urlsafe(32)
        await redis_client.setex(f"pwd_reset:{token}", _PWD_RESET_TTL, email)
        asyncio.create_task(send_password_reset_email(email, token))
    # Always return 200 — never reveal whether the email exists.
    return {"ok": True, "message": "If that email is registered, a reset link is on its way."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordPayload):
    token = payload.token.strip()
    new_password = payload.new_password.strip()

    if len(new_password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters."}, status_code=400)

    email = await redis_client.get(f"pwd_reset:{token}")
    if not email:
        return JSONResponse({"error": "Invalid or expired reset link."}, status_code=400)

    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Invalid or expired reset link."}, status_code=400)

    account["password_hash"] = hash_password(new_password)
    await save_account(email, account)
    await redis_client.delete(f"pwd_reset:{token}")

    return {"ok": True, "message": "Password updated. You can now sign in with your new password."}


@router.post("/register-team-member")
async def register_team_member(payload: TeamMemberRegisterPayload):
    email = payload.email.lower().strip()
    password = payload.password.strip()
    workspace_code = payload.workspace_code.strip().upper()

    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters."}, status_code=400)

    owner_email = await redis_client.get(f"workspace_code:{workspace_code}")
    if not owner_email:
        return JSONResponse({"error": "Workspace code not found."}, status_code=404)

    existing = await get_account(email)
    if existing:
        return JSONResponse({"error": "An account with that email already exists."}, status_code=409)

    owner_account = await get_account(owner_email)
    if not owner_account:
        return JSONResponse({"error": "Workspace not found."}, status_code=404)

    team_id = owner_account.get("team_id")
    if not team_id:
        return JSONResponse({"error": "Workspace not found."}, status_code=404)

    seats = await get_member_count(team_id)
    if seats >= 5:
        return JSONResponse({"error": "Team is full."}, status_code=400)

    account = {
        "email": email,
        "password_hash": hash_password(password),
        "subscription_status": "pending_team",
        "plan": None,
        "team_id": None,
        "team_role": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await save_account(email, account)

    token = await create_join_request(workspace_code, owner_email, team_id, email, payload.name)

    jr = await get_join_request(token) or {}
    eat = jr.get("email_action_token", "")
    canonical = os.getenv("APP_URL", "https://digiagency.up.railway.app").rstrip("/")
    approve_url = f"{canonical}/api/team/approve/{token}?auth=email_action&eat={eat}"
    deny_url = f"{canonical}/api/team/deny/{token}?auth=email_action&eat={eat}"

    asyncio.create_task(send_join_request_email(
        owner_email, email, payload.name,
        approve_url, deny_url, seats,
    ))

    return JSONResponse(
        {"message": "Request submitted", "owner_email": owner_email},
        status_code=201,
    )


@router.get("/me")
async def me(agency_token: str | None = Cookie(default=None)):
    if not agency_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    email = await get_token_email(agency_token)
    if not email:
        return JSONResponse({"error": "Session expired"}, status_code=401)

    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    return {
        "email": account["email"],
        "subscription_status": account.get("subscription_status", "inactive"),
        "plan": account.get("plan"),
        "team_id": account.get("team_id"),
        "team_role": account.get("team_role"),
        "workspace_code": account.get("workspace_code"),
        "created_at": account.get("created_at"),
    }
