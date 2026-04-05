"""
POST /api/support — sends a support message to digi.admin.ai@gmail.com

Requires env vars:
  SUPPORT_SMTP_USER     — Gmail address to send FROM (e.g. digi.admin.ai@gmail.com)
  SUPPORT_SMTP_PASSWORD — Gmail App Password (16-char, not the account password)

If the env vars are not set, the message is logged to stdout instead (safe fallback).
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_token_email

router = APIRouter()

SUPPORT_TO = "digi.admin.ai@gmail.com"

VALID_TYPES = {"Feature Request", "Bug Report", "Get Help", "Other"}


class SupportPayload(BaseModel):
    email: str
    type: str
    message: str


@router.post("")
async def send_support(payload: SupportPayload, agency_token: str | None = Cookie(default=None)):
    # Must be authenticated
    if not agency_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    token_email = await get_token_email(agency_token)
    if not token_email:
        return JSONResponse({"error": "Session expired"}, status_code=401)

    # Basic validation
    msg_type = payload.type.strip()
    message = payload.message.strip()
    sender_email = payload.email.strip()

    if msg_type not in VALID_TYPES:
        return JSONResponse({"error": "Invalid message type."}, status_code=400)
    if not message:
        return JSONResponse({"error": "Message cannot be empty."}, status_code=400)
    if len(message) > 5000:
        return JSONResponse({"error": "Message too long (max 5000 characters)."}, status_code=400)

    subject = f"[Digi Agency] {msg_type} from {sender_email}"
    body = (
        f"Support Message\n"
        f"{'─' * 40}\n"
        f"From:    {sender_email}\n"
        f"Account: {token_email}\n"
        f"Type:    {msg_type}\n"
        f"{'─' * 40}\n\n"
        f"{message}\n"
    )

    smtp_user = os.getenv("SUPPORT_SMTP_USER")
    smtp_pass = os.getenv("SUPPORT_SMTP_PASSWORD")

    if not smtp_user or not smtp_pass:
        # Fallback: print to logs so nothing is silently lost
        print(f"[SUPPORT — no SMTP configured]\n{subject}\n{body}")
        return {"ok": True}

    try:
        mime = MIMEMultipart()
        mime["From"] = smtp_user
        mime["To"] = SUPPORT_TO
        mime["Subject"] = subject
        mime["Reply-To"] = sender_email
        mime.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(mime)

        return {"ok": True}

    except Exception as exc:
        print(f"[SUPPORT] Failed to send email: {exc}")
        return JSONResponse(
            {"error": "Could not send message — please email digi.admin.ai@gmail.com directly."},
            status_code=500,
        )
