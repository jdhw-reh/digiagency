"""
Tests for auth endpoints:
  POST /api/auth/register
  POST /api/auth/login
  GET  /api/auth/me
  POST /api/auth/logout
"""

import pytest
from tests.conftest import (
    activate_account,
    get_csrf_from_response,
    login_user,
    register_user,
)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_happy_path(client):
    resp = await register_user(client, "alice@example.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["email"] == "alice@example.com"
    assert body["subscription_status"] == "inactive"
    # Cookie must be set
    assert "agency_token" in resp.cookies


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await register_user(client, "bob@example.com")
    resp = await register_user(client, "bob@example.com")
    assert resp.status_code == 409
    assert "already exists" in resp.json()["error"]


@pytest.mark.asyncio
async def test_register_weak_password(client):
    resp = await register_user(client, "charlie@example.com", password="short")
    assert resp.status_code == 400
    assert "8 characters" in resp.json()["error"]


@pytest.mark.asyncio
async def test_register_stores_account_in_redis(client, fake_redis):
    await register_user(client, "diana@example.com", password="securepass")
    raw = await fake_redis.get("account:diana@example.com")
    assert raw is not None
    import json
    account = json.loads(raw)
    assert account["email"] == "diana@example.com"
    assert account["subscription_status"] == "inactive"
    # Password must be stored as a bcrypt hash, never plain text
    assert account["password_hash"] != "securepass"
    assert account["password_hash"].startswith("$2b$")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_valid_credentials(client):
    await register_user(client, "eve@example.com")
    resp = await login_user(client, "eve@example.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["email"] == "eve@example.com"
    assert "agency_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await register_user(client, "frank@example.com")
    resp = await login_user(client, "frank@example.com", password="wrongpassword")
    assert resp.status_code == 401
    assert "Incorrect" in resp.json()["error"]


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    resp = await login_user(client, "nobody@example.com")
    assert resp.status_code == 401
    assert "Incorrect" in resp.json()["error"]


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_valid_token(client):
    await register_user(client, "grace@example.com")
    # The register call sets the agency_token cookie on the client session
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "grace@example.com"
    assert "subscription_status" in body


@pytest.mark.asyncio
async def test_me_missing_token(client):
    # Fresh client with no cookie
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert "authenticated" in resp.json()["error"].lower()


@pytest.mark.asyncio
async def test_me_invalid_token(client):
    # Manually send a bogus cookie
    resp = await client.get(
        "/api/auth/me",
        cookies={"agency_token": "totally_invalid_token_xyz"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logout_clears_cookie(client):
    reg = await register_user(client, "henry@example.com")
    csrf = get_csrf_from_response(reg)

    resp = await client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Token must be gone from Redis — /me should now return 401
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_logout_without_csrf_is_rejected(client):
    await register_user(client, "ivan@example.com")
    resp = await client.post("/api/auth/logout")
    # CSRF dependency rejects the request with 403
    assert resp.status_code == 403
