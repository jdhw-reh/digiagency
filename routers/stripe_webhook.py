"""
Stripe webhook router — handles subscription lifecycle events.

POST /api/stripe/webhook

Events handled:
  checkout.session.completed   → activate user, store customer/sub IDs
  customer.subscription.deleted → cancel user
  invoice.payment_failed        → cancel user
"""

import asyncio
import json
import os
import smtplib
import time
from email.mime.text import MIMEText

import httpx
import stripe
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from state import get_account, list_accounts, redis_client, save_account

_ADMIN_EMAIL = "digi.admin.ai@gmail.com"

router = APIRouter()


def _send_email(subject: str, body: str) -> None:
    """Send a plain-text email to the admin Gmail account."""
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        print("[email] GMAIL_APP_PASSWORD not set — skipping email")
        return
    print(f"[email] Attempting to send: {subject}")
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = _ADMIN_EMAIL
    msg["To"] = _ADMIN_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(_ADMIN_EMAIL, password)
            server.send_message(msg)
        print("[email] Sent successfully")
    except Exception as exc:
        print(f"[email] Failed (SSL/465): {exc}")
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
                server.starttls()
                server.login(_ADMIN_EMAIL, password)
                server.send_message(msg)
            print("[email] Sent successfully via STARTTLS/587")
        except Exception as exc2:
            print(f"[email] Failed (STARTTLS/587): {exc2}")


async def _notify_admin_new_signup(email: str, plan: str) -> None:
    """Push signup to Redis notification queue, send email, and fire optional webhook."""
    record = json.dumps({"email": email, "plan": plan, "at": time.time()})
    await redis_client.lpush("admin:new_signups", record)
    await redis_client.ltrim("admin:new_signups", 0, 99)

    plan_label = plan.capitalize()
    subject = f"New Digi Agency signup — {email}"
    body = (
        f"A new user has signed up for Digi Agency.\n\n"
        f"Email: {email}\n"
        f"Plan:  {plan_label}\n\n"
        f"Review at: https://digiagency.up.railway.app/admin"
    )
    asyncio.create_task(asyncio.to_thread(_send_email, subject, body))

    webhook_url = os.environ.get("ADMIN_WEBHOOK_URL")
    if webhook_url:
        message = f"New Digi Agency signup: {email} ({plan_label} plan)"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    webhook_url,
                    json={"content": message, "text": message},
                    headers={"Content-Type": "application/json"},
                )
        except Exception:
            pass


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

    event_type = event.type
    obj = event.data.object

    if event_type == "checkout.session.completed":
        email = getattr(obj, "client_reference_id", None)
        if email:
            account = await get_account(email)
            if account:
                metadata = getattr(obj, "metadata", None)
                plan = getattr(metadata, "plan", None) or "pro"
                account["subscription_status"] = "active"
                account["stripe_customer_id"] = getattr(obj, "customer", None)
                account["stripe_subscription_id"] = getattr(obj, "subscription", None)
                account["plan"] = plan
                await save_account(email, account)
                await _notify_admin_new_signup(email, plan)

    elif event_type in ("customer.subscription.deleted", "invoice.payment_failed"):
        customer_id = getattr(obj, "customer", None)
        if customer_id:
            account = await _find_account_by_customer_id(customer_id)
            if account:
                account["subscription_status"] = "cancelled"
                await save_account(account["email"], account)
                email = account["email"]
                plan = account.get("plan", "pro")
                reason = "subscription cancelled" if event_type == "customer.subscription.deleted" else "payment failed"
                subject = f"Digi Agency cancellation — {email}"
                body = (
                    f"A user has left Digi Agency.\n\n"
                    f"Email:  {email}\n"
                    f"Plan:   {plan.capitalize()}\n"
                    f"Reason: {reason}\n\n"
                    f"Review at: https://digiagency.up.railway.app/admin"
                )
                asyncio.create_task(asyncio.to_thread(_send_email, subject, body))

    # Return 200 for all other event types so Stripe doesn't retry
    return {"ok": True}
