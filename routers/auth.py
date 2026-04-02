"""
Auth router — email/password registration and login.

POST /api/auth/register   — create account (status: inactive until manually activated or Stripe webhook)
POST /api/auth/login      — returns auth token
POST /api/auth/logout     — deletes auth token
GET  /api/auth/me         — returns account info for the current token
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import (
    create_auth_token,
    delete_auth_token,
    get_account,
    get_token_email,
    hash_password,
    save_account,
    verify_password,
)

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
        secure=False,  # set to True once on HTTPS (Railway handles TLS)
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AuthPayload(BaseModel):
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

    return {
        "ok": True,
        "email": email,
        "subscription_status": account.get("subscription_status", "inactive"),
    }


@router.post("/logout")
async def logout(response: Response, agency_token: str | None = Cookie(default=None)):
    if agency_token:
        await delete_auth_token(agency_token)
    response.delete_cookie(_COOKIE)
    return {"ok": True}


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
        "created_at": account.get("created_at"),
    }
