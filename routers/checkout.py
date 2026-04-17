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

from state import get_account, get_token_email, save_account

router = APIRouter()

_DEFAULT_APP_URL = "https://digiagency.up.railway.app"


@router.post("/session")
async def create_checkout_session(
    plan: str = "pro",
    agency_token: str | None = Cookie(default=None),
):
    if not agency_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    email = await get_token_email(agency_token)
    if not email:
        return JSONResponse({"error": "Session expired"}, status_code=401)

    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    if plan not in ("starter", "pro", "agency"):
        return JSONResponse({"error": f"Invalid plan: {plan!r}"}, status_code=400)

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    app_url = os.environ.get("APP_URL", _DEFAULT_APP_URL).rstrip("/")

    if plan == "starter":
        price_id = os.environ.get("STRIPE_PRICE_ID_STARTER")
    elif plan == "agency":
        price_id = os.environ.get("STRIPE_PRICE_ID_AGENCY")
        if not price_id:
            return JSONResponse({"error": "STRIPE_PRICE_ID_AGENCY is not configured — set this env var in Railway"}, status_code=500)
    else:
        price_id = os.environ.get("STRIPE_PRICE_ID_PRO")

    if not stripe.api_key:
        return JSONResponse({"error": "Stripe not configured"}, status_code=500)
    if not price_id:
        return JSONResponse({"error": f"STRIPE_PRICE_ID_{plan.upper()} not configured"}, status_code=500)

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        client_reference_id=email,
        customer_email=email,
        allow_promotion_codes=True,
        metadata={"plan": plan},
        success_url=f"{app_url}/login?checkout=success",
        cancel_url=f"{app_url}/login?checkout=cancelled",
    )

    return {"url": session.url}


@router.post("/portal")
async def create_portal_session(agency_token: str | None = Cookie(default=None)):
    if not agency_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    email = await get_token_email(agency_token)
    if not email:
        return JSONResponse({"error": "Session expired"}, status_code=401)

    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        return JSONResponse({"error": "Stripe not configured"}, status_code=500)

    customer_id = account.get("stripe_customer_id")

    if not customer_id:
        # Webhook may have missed storing the customer ID — look it up by email
        customers = stripe.Customer.list(email=email, limit=1)
        if customers.data:
            customer_id = customers.data[0].id
            account["stripe_customer_id"] = customer_id
            await save_account(email, account)
        else:
            return JSONResponse(
                {"error": "No billing record found. If you signed up recently, please contact support."},
                status_code=404,
            )

    app_url = os.environ.get("APP_URL", _DEFAULT_APP_URL).rstrip("/")

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{app_url}/",
    )

    return {"url": portal.url}
