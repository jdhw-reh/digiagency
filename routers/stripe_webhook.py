"""
Stripe webhook router — handles subscription lifecycle events.

POST /api/stripe/webhook

Events handled:
  checkout.session.completed   → activate user, store customer/sub IDs
  customer.subscription.deleted → cancel user
  invoice.payment_failed        → cancel user
"""

import os

import stripe
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from state import get_account, list_accounts, save_account

router = APIRouter()


async def _find_account_by_customer_id(customer_id: str) -> dict | None:
    """Scan all accounts for one matching stripe_customer_id."""
    accounts = await list_accounts()  # strips password_hash, fine for lookup
    for a in accounts:
        if a.get("stripe_customer_id") == customer_id:
            return await get_account(a["email"])  # reload with password_hash intact
    return None


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        return JSONResponse({"error": "STRIPE_WEBHOOK_SECRET not configured"}, status_code=500)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.SignatureVerificationError:
        return JSONResponse({"error": "Invalid signature"}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Invalid payload"}, status_code=400)

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        email = obj.get("client_reference_id")
        if email:
            account = await get_account(email)
            if account:
                account["subscription_status"] = "active"
                account["stripe_customer_id"] = obj.get("customer")
                account["stripe_subscription_id"] = obj.get("subscription")
                await save_account(email, account)

    elif event_type in ("customer.subscription.deleted", "invoice.payment_failed"):
        customer_id = obj.get("customer")
        if customer_id:
            account = await _find_account_by_customer_id(customer_id)
            if account:
                account["subscription_status"] = "cancelled"
                await save_account(account["email"], account)

    # Return 200 for all other event types so Stripe doesn't retry
    return {"ok": True}
