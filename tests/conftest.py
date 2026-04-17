"""
Shared pytest fixtures for the Digi Agency test suite.

Key design decisions:
- fakeredis replaces the real Redis client everywhere before the app is imported.
  state.redis_client is patched at module level so all helpers (auth, CSRF, rate limits)
  share the same in-memory store per test.
- ENVIRONMENT=development disables secure=True on cookies so TestClient (plain HTTP) can
  read and send them.
- Stripe and Gemini are mocked at conftest scope so no real API calls are ever made.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Environment — must be set BEFORE the app modules are imported
# ---------------------------------------------------------------------------

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")
os.environ.setdefault("STRIPE_PRICE_ID_STARTER", "price_starter_fake")
os.environ.setdefault("STRIPE_PRICE_ID_PRO", "price_pro_fake")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")  # won't be used; patched below


# ---------------------------------------------------------------------------
# fakeredis fixture — single shared instance per test function
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_redis():
    """A fresh fakeredis instance, reset between every test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


# ---------------------------------------------------------------------------
# Patch state.redis_client with fakeredis before the app is touched
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def patch_redis(fake_redis):
    """
    Replace the module-level redis_client everywhere it is held as a direct
    reference (each module that does `from state import redis_client` gets its
    own binding that must be patched independently).
    """
    import state
    import utils.csrf as csrf_module
    import rate_limits as rl_module
    import routers.stripe_webhook as webhook_module

    original = state.redis_client
    state.redis_client = fake_redis
    csrf_module.redis_client = fake_redis
    rl_module.redis_client = fake_redis
    webhook_module.redis_client = fake_redis

    yield

    state.redis_client = original
    csrf_module.redis_client = original
    rl_module.redis_client = original
    webhook_module.redis_client = original


# ---------------------------------------------------------------------------
# FastAPI AsyncClient
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(patch_redis):
    """httpx AsyncClient wired to the FastAPI app — no real network."""
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Stripe mock
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_stripe():
    """
    Patch stripe.Webhook.construct_event and stripe.checkout.Session.create
    so no real Stripe calls are made.  Individual tests that need specific
    event payloads should override stripe.Webhook.construct_event directly.
    """
    with patch("stripe.Webhook.construct_event") as mock_construct, \
         patch("stripe.checkout.Session.create") as mock_session_create, \
         patch("stripe.billing_portal.Session.create") as mock_portal_create:

        # Default: construct_event raises SignatureVerificationError (safe default)
        mock_construct.side_effect = stripe_sig_error()

        # Default checkout session response
        fake_session = MagicMock()
        fake_session.url = "https://checkout.stripe.com/fake"
        mock_session_create.return_value = fake_session

        fake_portal = MagicMock()
        fake_portal.url = "https://billing.stripe.com/fake"
        mock_portal_create.return_value = fake_portal

        yield {
            "construct_event": mock_construct,
            "session_create": mock_session_create,
            "portal_create": mock_portal_create,
        }


def stripe_sig_error():
    """Return a side_effect that raises stripe.SignatureVerificationError."""
    import stripe
    return stripe.SignatureVerificationError("bad sig", "fake-header")


def make_stripe_event(event_type: str, data_object: dict, event_id: str = "evt_test") -> MagicMock:
    """
    Build a mock Stripe event object that mimics stripe.Event structure.
    stripe.Webhook.construct_event returns this when patched to succeed.
    """
    obj = MagicMock()
    for key, value in data_object.items():
        setattr(obj, key, value)
    # metadata as an attribute-accessible mock
    metadata_mock = MagicMock()
    metadata_mock.plan = data_object.get("metadata_plan", "pro")
    obj.metadata = metadata_mock

    event = MagicMock()
    event.id = event_id
    event.type = event_type
    event.data = MagicMock()
    event.data.object = obj
    return event


# ---------------------------------------------------------------------------
# Gemini mock
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_gemini():
    """
    Patch google.genai so no AI calls are made.
    Returns a simple string response from generate_content.
    """
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        fake_response = MagicMock()
        fake_response.text = "Mocked AI response."
        mock_client.models.generate_content.return_value = fake_response

        yield mock_client


# ---------------------------------------------------------------------------
# Resend / email mock — prevent HTTP calls from stripe_webhook._send_email
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_resend(monkeypatch):
    """Patch httpx.AsyncClient.post so _send_email never makes real calls."""
    with patch("routers.stripe_webhook._send_email", new_callable=AsyncMock) as mock_email:
        yield mock_email


# ---------------------------------------------------------------------------
# Helpers reused across test modules
# ---------------------------------------------------------------------------

async def register_user(client: AsyncClient, email: str, password: str = "password123") -> dict:
    """Register a user and return the response."""
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    return resp


async def login_user(client: AsyncClient, email: str, password: str = "password123") -> dict:
    """Log in and return the response."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    return resp


async def activate_account(email: str) -> None:
    """Directly flip subscription_status to active in fakeredis."""
    import state
    account = await state.get_account(email)
    if account:
        account["subscription_status"] = "active"
        await state.save_account(email, account)


def get_csrf_from_response(response) -> str:
    """Extract the csrf_token cookie value from an httpx response."""
    return response.cookies.get("csrf_token", "")
