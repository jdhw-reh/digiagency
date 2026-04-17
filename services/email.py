"""
Email service — wraps the Resend API via httpx.

All functions are async and designed for fire-and-forget use with
asyncio.create_task().  Email failures are logged but never raised,
so they cannot crash the main request flow.
"""

import os

import httpx

_RESEND_API_URL = "https://api.resend.com/emails"
_FROM_ADDRESS = "Digi Agency <hello@digi-agency.co.uk>"
_DEFAULT_APP_URL = "https://digiagency.up.railway.app"


def _app_url() -> str:
    return os.environ.get("APP_URL", _DEFAULT_APP_URL).rstrip("/")


# ---------------------------------------------------------------------------
# Core sender
# ---------------------------------------------------------------------------

async def send_email(to: str, subject: str, html_body: str, text_body: str) -> None:
    """Send an email via the Resend API.  Errors are logged, never raised."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(f"[email] RESEND_API_KEY not set — skipping '{subject}' to {to}")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                _RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": _FROM_ADDRESS,
                    "to": [to],
                    "subject": subject,
                    "html": html_body,
                    "text": text_body,
                },
            )
        if res.status_code in (200, 201):
            print(f"[email] Sent '{subject}' to {to}")
        else:
            print(f"[email] Failed '{subject}' to {to}: {res.status_code} {res.text}")
    except Exception as exc:
        print(f"[email] Error sending '{subject}' to {to}: {exc}")


# ---------------------------------------------------------------------------
# Shared layout wrapper
# ---------------------------------------------------------------------------

def _wrap_html(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:'DM Sans',system-ui,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0f0f1a;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">

          <!-- Header -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <span style="font-size:28px;color:#6366f1;">✦</span>
              <span style="display:block;font-size:20px;font-weight:700;color:#ffffff;margin-top:8px;letter-spacing:-0.02em;">Digi Agency</span>
              <span style="display:block;font-size:13px;color:#6b7280;margin-top:4px;">Your AI marketing team</span>
            </td>
          </tr>

          <!-- Card -->
          <tr>
            <td style="background:#1a1a2e;border:1px solid #2d2d44;border-radius:16px;padding:36px 40px;">
              {content}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding-top:28px;">
              <span style="font-size:12px;color:#4b5563;">© 2025 Digi Agency · <a href="{_app_url()}" style="color:#6366f1;text-decoration:none;">digi-agency.co.uk</a></span>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _btn(label: str, href: str) -> str:
    return (
        f'<a href="{href}" style="display:inline-block;background:#6366f1;color:#ffffff;'
        f"font-size:15px;font-weight:600;text-decoration:none;padding:13px 28px;"
        f'border-radius:10px;margin-top:24px;">{label}</a>'
    )


def _h1(text: str) -> str:
    return f'<h1 style="margin:0 0 16px;font-size:22px;font-weight:700;color:#ffffff;letter-spacing:-0.02em;">{text}</h1>'


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#c0c0d0;">{text}</p>'


def _divider() -> str:
    return '<hr style="border:none;border-top:1px solid #2d2d44;margin:24px 0;">'


# ---------------------------------------------------------------------------
# 1. Welcome / registration email
# ---------------------------------------------------------------------------

async def send_welcome_email(to: str) -> None:
    app = _app_url()
    subject = "Welcome to Digi Agency"
    content = (
        _h1("Welcome aboard! 🎉")
        + _p("Your Digi Agency account has been created. You're one step away from having a full AI marketing team working for you 24/7.")
        + _p("To access the platform, complete your subscription by choosing a plan:")
        + _btn("Choose a plan →", f"{app}/login")
        + _divider()
        + _p(
            '<strong style="color:#ffffff;">What happens next?</strong><br>'
            "After subscribing, you'll connect your Notion workspace and your AI team — "
            "content writers, social strategists, SEO auditors — will be ready to run."
        )
        + _p(f'Questions? Reply to this email or visit <a href="{app}/support" style="color:#6366f1;">our support page</a>.')
    )
    html_body = _wrap_html(subject, content)
    text_body = (
        "Welcome to Digi Agency!\n\n"
        "Your account has been created. To access the platform, complete your subscription:\n"
        f"{app}/login\n\n"
        "After subscribing, connect your Notion workspace and your AI marketing team will be ready to run.\n\n"
        "Questions? Just reply to this email."
    )
    await send_email(to, subject, html_body, text_body)


# ---------------------------------------------------------------------------
# 2. Subscription activated email
# ---------------------------------------------------------------------------

_PLAN_LABELS = {
    "starter": ("Starter", "£29/month"),
    "pro": ("Pro", "£49/month"),
}


async def send_subscription_activated_email(to: str, plan: str) -> None:
    app = _app_url()
    plan_name, plan_price = _PLAN_LABELS.get(plan.lower(), (plan.capitalize(), ""))
    price_line = f" ({plan_price})" if plan_price else ""
    subject = "Your Digi Agency subscription is active"
    content = (
        _h1("Your subscription is active ✦")
        + _p(f"You're now on the <strong style=\"color:#ffffff;\">{plan_name} plan{price_line}</strong>. Your AI marketing team is ready.")
        + _btn("Go to the app →", f"{app}/")
        + _divider()
        + _p('<strong style="color:#ffffff;">Getting started</strong>')
        + _p(
            "1. <strong style=\"color:#e5e7eb;\">Connect Notion</strong> — head to the Setup tab and paste your Notion integration token.<br>"
            "2. <strong style=\"color:#e5e7eb;\">Pick a team</strong> — start with the Content Team or SEO Audit to see Digi Agency in action.<br>"
            "3. <strong style=\"color:#e5e7eb;\">Run your first agent</strong> — enter a topic and let your AI team do the work."
        )
        + _p(f'Need help? Visit <a href="{app}/support" style="color:#6366f1;">our support page</a> any time.')
    )
    html_body = _wrap_html(subject, content)
    text_body = (
        f"Your Digi Agency subscription is active!\n\n"
        f"Plan: {plan_name}{price_line}\n\n"
        "Getting started:\n"
        "1. Connect Notion — go to the Setup tab and paste your integration token.\n"
        "2. Pick a team — try the Content Team or SEO Audit first.\n"
        "3. Run your first agent.\n\n"
        f"Open the app: {app}/\n\n"
        f"Need help? {app}/support"
    )
    await send_email(to, subject, html_body, text_body)


# ---------------------------------------------------------------------------
# 3. Subscription cancelled email
# ---------------------------------------------------------------------------

async def send_subscription_cancelled_email(to: str, plan: str, access_end: str | None = None) -> None:
    app = _app_url()
    plan_name, _ = _PLAN_LABELS.get(plan.lower(), (plan.capitalize(), ""))
    access_line = (
        f'Your access continues until <strong style="color:#ffffff;">{access_end}</strong>.'
        if access_end
        else "Your access has ended."
    )
    subject = "Your Digi Agency subscription has been cancelled"
    content = (
        _h1("Subscription cancelled")
        + _p(f"We've cancelled your <strong style=\"color:#ffffff;\">{plan_name}</strong> subscription.")
        + _p(access_line)
        + _p("We're sorry to see you go. If this was a mistake or you'd like to resubscribe, you can do so any time:")
        + _btn("Resubscribe →", f"{app}/login")
        + _divider()
        + _p("If you have feedback on why you cancelled, we'd genuinely love to hear it — just reply to this email.")
    )
    html_body = _wrap_html(subject, content)
    text_body = (
        f"Your Digi Agency {plan_name} subscription has been cancelled.\n\n"
        + (f"Your access continues until {access_end}.\n\n" if access_end else "Your access has ended.\n\n")
        + f"To resubscribe, visit: {app}/login\n\n"
        "Got feedback? Just reply to this email — we'd love to hear it."
    )
    await send_email(to, subject, html_body, text_body)


# ---------------------------------------------------------------------------
# 4. Password reset email
# ---------------------------------------------------------------------------

async def send_password_reset_email(to: str, reset_token: str) -> None:
    app = _app_url()
    reset_url = f"{app}/reset-password?token={reset_token}"
    subject = "Reset your Digi Agency password"
    content = (
        _h1("Reset your password")
        + _p("We received a request to reset the password for your Digi Agency account.")
        + _p("Click the button below to choose a new password. This link expires in <strong style=\"color:#ffffff;\">1 hour</strong>.")
        + _btn("Reset password →", reset_url)
        + _divider()
        + _p("If you didn't request a password reset, you can safely ignore this email — your password won't change.")
        + _p(f'Or copy this link into your browser:<br><span style="color:#6366f1;font-size:13px;">{reset_url}</span>')
    )
    html_body = _wrap_html(subject, content)
    text_body = (
        "Reset your Digi Agency password\n\n"
        "We received a request to reset your password. Use the link below — it expires in 1 hour:\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, ignore this email and your password will remain unchanged."
    )
    await send_email(to, subject, html_body, text_body)
