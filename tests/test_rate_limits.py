"""
Tests for AIRateLimit (rate_limits.py).

Strategy: call AIRateLimit.__call__() directly with a minimal mocked Request
rather than routing through real AI endpoints (which also need active subscription,
CSRF tokens, and a working Gemini client).  This keeps tests focused on the Redis
counter logic.

Limits under test:
  Starter — 20 req/min, 200 req/hour
  Pro     — 60 req/min, 600 req/hour
  Anonymous — defaults to Starter limits
"""

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from rate_limits import AIRateLimit, LIMITS
from tests.conftest import register_user


def _make_request(token: str | None = None, ip: str = "127.0.0.1") -> MagicMock:
    """Build a minimal Request-like mock for AIRateLimit.__call__."""
    req = MagicMock()
    req.cookies = {"agency_token": token} if token else {}
    # slowapi.util.get_remote_address reads request.client.host
    req.client = MagicMock()
    req.client.host = ip
    return req


# ---------------------------------------------------------------------------
# Starter plan — per-minute limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_starter_per_minute_limit(client, fake_redis):
    """Request 21 from a Starter user should raise 429."""
    # Register and get a real token stored in fakeredis
    reg = await register_user(client, "rl_starter@example.com")
    token = reg.cookies.get("agency_token")
    assert token, "Expected agency_token cookie from register"

    # Set plan to starter on the account
    import state
    account = await state.get_account("rl_starter@example.com")
    account["plan"] = "starter"
    account["subscription_status"] = "active"
    await state.save_account("rl_starter@example.com", account)

    rl = AIRateLimit()
    req = _make_request(token=token)
    limit = LIMITS["starter"]["minute"]  # 20

    # Requests 1..limit should all pass
    for i in range(limit):
        await rl(req, agency_token=token)

    # Request limit+1 must be rejected
    with pytest.raises(HTTPException) as exc_info:
        await rl(req, agency_token=token)
    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Pro plan — per-minute limit is higher
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pro_per_minute_limit(client, fake_redis):
    """Pro user should survive 60 req/min but be blocked on request 61."""
    reg = await register_user(client, "rl_pro@example.com")
    token = reg.cookies.get("agency_token")

    import state
    account = await state.get_account("rl_pro@example.com")
    account["plan"] = "pro"
    account["subscription_status"] = "active"
    await state.save_account("rl_pro@example.com", account)

    rl = AIRateLimit()
    req = _make_request(token=token)
    limit = LIMITS["pro"]["minute"]  # 60

    for i in range(limit):
        await rl(req, agency_token=token)

    with pytest.raises(HTTPException) as exc_info:
        await rl(req, agency_token=token)
    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Counter resets after the window expires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_resets_after_window(client, fake_redis):
    """
    Exhaust the per-minute limit, then delete the Redis key (simulating TTL
    expiry), and verify requests are accepted again.
    """
    reg = await register_user(client, "rl_reset@example.com")
    token = reg.cookies.get("agency_token")

    import state
    account = await state.get_account("rl_reset@example.com")
    account["plan"] = "starter"
    account["subscription_status"] = "active"
    await state.save_account("rl_reset@example.com", account)

    rl = AIRateLimit()
    req = _make_request(token=token)
    limit = LIMITS["starter"]["minute"]

    # Exhaust
    for _ in range(limit):
        await rl(req, agency_token=token)

    # Confirm blocked
    with pytest.raises(HTTPException):
        await rl(req, agency_token=token)

    # Simulate window expiry by deleting the minute key from fakeredis
    min_key = f"rl:ai:min:{token}"
    await fake_redis.delete(min_key)

    # Should pass again after reset
    await rl(req, agency_token=token)  # no exception expected


# ---------------------------------------------------------------------------
# Anonymous user gets Starter-level limits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anonymous_user_gets_starter_limits(fake_redis):
    """An unauthenticated request (no token) should use the Starter limit."""
    rl = AIRateLimit()
    req = _make_request(token=None, ip="10.0.0.1")
    limit = LIMITS["starter"]["minute"]  # 20

    for _ in range(limit):
        await rl(req, agency_token=None)

    with pytest.raises(HTTPException) as exc_info:
        await rl(req, agency_token=None)
    assert exc_info.value.status_code == 429
