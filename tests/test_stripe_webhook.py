"""
Tests for POST /api/stripe/webhook

Events actually handled by the app:
  checkout.session.completed   → activates account (by client_reference_id = email)
  customer.subscription.deleted → cancels account (by stripe_customer_id)
  invoice.payment_failed        → cancels account (same lookup)

Note on idempotency: the handler doesn't deduplicate by event ID — receiving the
same checkout.session.completed twice just sets status=active twice.  That is safe
by design; we verify no crash and status stays active.
"""

import json

import pytest
import stripe

from tests.conftest import make_stripe_event, register_user


WEBHOOK_URL = "/api/stripe/webhook"
_FAKE_SIG = "t=1,v1=fakesig"


def _post_webhook(client, event_mock, mock_stripe_fixtures, event):
    """
    Helper: configure construct_event to return `event`, then POST to webhook.
    """
    mock_stripe_fixtures["construct_event"].side_effect = None
    mock_stripe_fixtures["construct_event"].return_value = event
    return client.post(
        WEBHOOK_URL,
        content=b"fake-body",
        headers={
            "stripe-signature": _FAKE_SIG,
            "content-type": "application/json",
        },
    )


# ---------------------------------------------------------------------------
# checkout.session.completed → account activated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_completed_activates_account(client, mock_stripe):
    await register_user(client, "stripe_user@example.com")

    event = make_stripe_event(
        "checkout.session.completed",
        {
            "client_reference_id": "stripe_user@example.com",
            "customer": "cus_test123",
            "subscription": "sub_test123",
            "metadata_plan": "starter",
        },
    )
    coro = _post_webhook(client, None, mock_stripe, event)
    resp = await coro
    assert resp.status_code == 200

    import state
    account = await state.get_account("stripe_user@example.com")
    assert account["subscription_status"] == "active"
    assert account["stripe_customer_id"] == "cus_test123"
    assert account["stripe_subscription_id"] == "sub_test123"
    assert account["plan"] == "starter"


@pytest.mark.asyncio
async def test_checkout_completed_unknown_email_is_noop(client, mock_stripe):
    """If client_reference_id doesn't match any account, webhook returns 200 silently."""
    event = make_stripe_event(
        "checkout.session.completed",
        {
            "client_reference_id": "ghost@example.com",
            "customer": "cus_ghost",
            "subscription": "sub_ghost",
        },
    )
    mock_stripe["construct_event"].side_effect = None
    mock_stripe["construct_event"].return_value = event
    resp = await client.post(
        WEBHOOK_URL,
        content=b"fake-body",
        headers={"stripe-signature": _FAKE_SIG, "content-type": "application/json"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# customer.subscription.deleted → account cancelled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_deleted_cancels_account(client, mock_stripe):
    await register_user(client, "cancel_user@example.com")

    # First activate via checkout
    import state
    account = await state.get_account("cancel_user@example.com")
    account["subscription_status"] = "active"
    account["stripe_customer_id"] = "cus_cancel123"
    account["plan"] = "pro"
    await state.save_account("cancel_user@example.com", account)

    event = make_stripe_event(
        "customer.subscription.deleted",
        {"customer": "cus_cancel123"},
    )
    mock_stripe["construct_event"].side_effect = None
    mock_stripe["construct_event"].return_value = event
    resp = await client.post(
        WEBHOOK_URL,
        content=b"fake-body",
        headers={"stripe-signature": _FAKE_SIG, "content-type": "application/json"},
    )
    assert resp.status_code == 200

    account = await state.get_account("cancel_user@example.com")
    assert account["subscription_status"] == "cancelled"


# ---------------------------------------------------------------------------
# invoice.payment_failed → account cancelled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_failed_cancels_account(client, mock_stripe):
    await register_user(client, "failed_pay@example.com")

    import state
    account = await state.get_account("failed_pay@example.com")
    account["subscription_status"] = "active"
    account["stripe_customer_id"] = "cus_failedpay"
    account["plan"] = "starter"
    await state.save_account("failed_pay@example.com", account)

    event = make_stripe_event(
        "invoice.payment_failed",
        {"customer": "cus_failedpay"},
    )
    mock_stripe["construct_event"].side_effect = None
    mock_stripe["construct_event"].return_value = event
    resp = await client.post(
        WEBHOOK_URL,
        content=b"fake-body",
        headers={"stripe-signature": _FAKE_SIG, "content-type": "application/json"},
    )
    assert resp.status_code == 200

    account = await state.get_account("failed_pay@example.com")
    assert account["subscription_status"] == "cancelled"


# ---------------------------------------------------------------------------
# Invalid Stripe signature → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_stripe_signature_rejected(client, mock_stripe):
    # mock_stripe default side_effect is SignatureVerificationError
    resp = await client.post(
        WEBHOOK_URL,
        content=b"tampered-body",
        headers={"stripe-signature": "bad", "content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert "signature" in resp.json()["error"].lower()


# ---------------------------------------------------------------------------
# Unknown event type → 200, no state change
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_event_type_is_noop(client, mock_stripe):
    await register_user(client, "ignored_event@example.com")

    event = make_stripe_event(
        "customer.updated",  # not handled by the app
        {"customer": "cus_ignored"},
    )
    mock_stripe["construct_event"].side_effect = None
    mock_stripe["construct_event"].return_value = event
    resp = await client.post(
        WEBHOOK_URL,
        content=b"fake-body",
        headers={"stripe-signature": _FAKE_SIG, "content-type": "application/json"},
    )
    assert resp.status_code == 200

    import state
    account = await state.get_account("ignored_event@example.com")
    assert account["subscription_status"] == "inactive"  # unchanged


# ---------------------------------------------------------------------------
# Duplicate event (idempotency)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_checkout_event_is_idempotent(client, mock_stripe):
    """Same checkout.session.completed twice — no crash, status stays active."""
    await register_user(client, "idem_user@example.com")

    event = make_stripe_event(
        "checkout.session.completed",
        {
            "client_reference_id": "idem_user@example.com",
            "customer": "cus_idem",
            "subscription": "sub_idem",
        },
        event_id="evt_duplicate",
    )

    for _ in range(2):
        mock_stripe["construct_event"].side_effect = None
        mock_stripe["construct_event"].return_value = event
        resp = await client.post(
            WEBHOOK_URL,
            content=b"fake-body",
            headers={"stripe-signature": _FAKE_SIG, "content-type": "application/json"},
        )
        assert resp.status_code == 200

    import state
    account = await state.get_account("idem_user@example.com")
    assert account["subscription_status"] == "active"
