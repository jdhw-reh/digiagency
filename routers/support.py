"""
POST /api/support — sends a support message to digi.admin.ai@gmail.com via Resend.

Requires env var:
  RESEND_API_KEY — API key from resend.com

If the env var is not set, the message is logged to stdout instead (safe fallback).
Auth is optional: authenticated users have their account email logged alongside the form email.
"""

import os

import httpx
from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_token_email

router = APIRouter()

SUPPORT_TO = "digi.admin.ai@gmail.com"
SUPPORT_FROM = "Digi Agency Support <support@digi-agency.co.uk>"

VALID_TYPES = {"Feature Request", "Bug Report", "Get Help", "Other", "Login Issue", "Billing"}


class SupportPayload(BaseModel):
    email: str
    type: str
    message: str


@router.post("")
async def send_support(payload: SupportPayload, agency_token: str | None = Cookie(default=None)):
    # Auth is optional — get account email if logged in, but don't block unauthenticated users
    token_email = None
    if agency_token:
        token_email = await get_token_email(agency_token)

    # Basic validation
    msg_type = payload.type.strip()
    message = payload.message.strip()
    sender_email = payload.email.strip()

    if not sender_email:
        return JSONResponse({"error": "Email address is required."}, status_code=400)
    if msg_type not in VALID_TYPES:
        return JSONResponse({"error": "Invalid message type."}, status_code=400)
    if not message:
        return JSONResponse({"error": "Message cannot be empty."}, status_code=400)
    if len(message) > 5000:
        return JSONResponse({"error": "Message too long (max 5000 characters)."}, status_code=400)

    account_line = f"Account: {token_email}\n" if token_email else ""
    subject = f"[Digi Agency] {msg_type} from {sender_email}"
    body = (
        f"Support Message\n"
        f"{'─' * 40}\n"
        f"From:    {sender_email}\n"
        f"{account_line}"
        f"Type:    {msg_type}\n"
        f"{'─' * 40}\n\n"
        f"{message}\n"
    )

    api_key = os.getenv("RESEND_API_KEY")

    if not api_key:
        print(f"[SUPPORT — no RESEND_API_KEY configured]\n{subject}\n{body}")
        return {"ok": True}

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "from": SUPPORT_FROM,
                    "to": [SUPPORT_TO],
                    "reply_to": sender_email,
                    "subject": subject,
                    "text": body,
                },
                timeout=10,
            )

        if res.status_code in (200, 201):
            return {"ok": True}

        print(f"[SUPPORT] Resend returned {res.status_code}: {res.text}")
        return JSONResponse(
            {"error": "Could not send message — please email digi.admin.ai@gmail.com directly."},
            status_code=500,
        )

    except Exception as exc:
        print(f"[SUPPORT] Failed to send email: {exc}")
        return JSONResponse(
            {"error": "Could not send message — please email digi.admin.ai@gmail.com directly."},
            status_code=500,
        )
