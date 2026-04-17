"""
Double-Submit Cookie CSRF protection.

Pattern: on login/register, generate a random token, store it in Redis keyed to the
session token, and set it as a *non-httpOnly* cookie (csrf_token) so JS can read it.
On every mutating request the frontend reads that cookie and sends it back as the
X-CSRF-Token header.  The dependency verifies header == stored Redis value.

Why this is safe:
  - A cross-origin attacker can trigger the browser to send the httpOnly agency_token
    cookie automatically, but they cannot read the csrf_token cookie value (blocked by
    the same-origin policy on document.cookie).  Without knowing the value they cannot
    set the matching header.
  - Timing-safe comparison (secrets.compare_digest) prevents timing attacks.
"""

import os
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import Response

from state import redis_client

_CSRF_COOKIE = "csrf_token"
_COOKIE_MAX_AGE = 86400 * 30  # 30 days — must match auth cookie
_SECURE_COOKIES = os.getenv("ENVIRONMENT", "production") != "development"


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def set_csrf_cookie(response: Response, csrf_token: str) -> None:
    """Set the CSRF cookie — readable by JS (httponly=False is intentional)."""
    response.set_cookie(
        key=_CSRF_COOKIE,
        value=csrf_token,
        max_age=_COOKIE_MAX_AGE,
        httponly=False,        # Must be JS-readable for the Double-Submit pattern
        samesite="strict",
        secure=_SECURE_COOKIES,
        path="/",
    )


def delete_csrf_cookie(response: Response) -> None:
    """Clear the CSRF cookie on logout."""
    response.delete_cookie(_CSRF_COOKIE, path="/")


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

async def create_csrf_token(agency_token: str) -> str:
    """Generate a CSRF token and store it in Redis tied to the session token."""
    csrf_token = secrets.token_urlsafe(32)
    await redis_client.setex(f"csrf:{agency_token}", _COOKIE_MAX_AGE, csrf_token)
    return csrf_token


async def delete_csrf_token(agency_token: str) -> None:
    """Remove the CSRF token from Redis (called on logout)."""
    await redis_client.delete(f"csrf:{agency_token}")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def verify_csrf_token(request: Request) -> None:
    """
    FastAPI dependency — enforces CSRF protection on mutating requests.

    Safe HTTP methods (GET, HEAD, OPTIONS) are passed through without a check.
    For everything else the request MUST include X-CSRF-Token whose value matches
    the token stored in Redis for the current session.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return  # Safe methods cannot carry state changes — no check needed

    csrf_header = request.headers.get("X-CSRF-Token", "")
    if not csrf_header:
        raise HTTPException(status_code=403, detail="Missing CSRF token")

    agency_token = request.cookies.get("agency_token")
    if not agency_token:
        raise HTTPException(status_code=403, detail="Missing session")

    stored = await redis_client.get(f"csrf:{agency_token}")
    if not stored:
        raise HTTPException(
            status_code=403,
            detail="CSRF token not found — please log in again",
        )

    if not secrets.compare_digest(stored, csrf_header):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
