"""
Checkout router — creates Stripe Checkout sessions for new subscribers.

POST /api/checkout/session  — create a Stripe Checkout session, return {url}

Requires a valid auth cookie but does NOT require an active subscription,
so new users can pay right after registering.
"""

import os

import stripe
from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse

from state import get_account, get_token_email

router = APIRouter()

_DEFAULT_APP_URL = "https://digiagency.up.railway.app"


@router.post("/session")
async def create_checkout_session(agency_token: str | None = Cookie(default=None)):
    if not agency_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    email = await get_token_email(agency_token)
    if not email:
        return JSONResponse({"error": "Session expired"}, status_code=401)

    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_PRICE_ID")
    app_url = os.environ.get("APP_URL", _DEFAULT_APP_URL).rstrip("/")

    if not stripe.api_key:
        return JSONResponse({"error": "Stripe not configured"}, status_code=500)
    if not price_id:
        return JSONResponse({"error": "STRIPE_PRICE_ID not configured"}, status_code=500)

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        client_reference_id=email,
        customer_email=email,
        allow_promotion_codes=True,
        success_url=f"{app_url}/login?checkout=success",
        cancel_url=f"{app_url}/login?checkout=cancelled",
    )

    return {"url": session.url}
