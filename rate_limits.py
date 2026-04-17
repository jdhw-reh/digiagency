"""
AI rate limiting — enforces per-user burst and sustained limits on Gemini routes.

Limits by plan:
  Starter — 20 requests/minute, 200 requests/hour
  Pro     — 60 requests/minute, 600 requests/hour

Applied as a FastAPI dependency via Depends(AIRateLimit()).
Existing subscribers without a stored plan default to Pro limits.
"""

import logging
from datetime import datetime, timezone

from fastapi import Cookie, HTTPException, Request
from slowapi.util import get_remote_address

from state import get_account, get_token_email, redis_client

logger = logging.getLogger(__name__)

LIMITS: dict[str, dict[str, int]] = {
    "starter": {"minute": 20,  "hour": 200},
    "pro":     {"minute": 60,  "hour": 600},
    "agency":  {"minute": 60,  "hour": 600},
}


async def _resolve(token: str | None) -> tuple[str, str]:
    """Return (user_identifier, plan) for the given auth token.
    Team members inherit the plan from their team owner.
    """
    if not token:
        return ("anonymous", "starter")
    email = await get_token_email(token)
    if not email:
        return (token[:16], "starter")
    account = await get_account(email)
    if not account:
        return (email, "starter")

    # Team members inherit the owner's plan
    if account.get("team_role") == "member" and account.get("team_id"):
        from state import get_team
        team = await get_team(account["team_id"])
        if team:
            owner_account = await get_account(team["owner_email"])
            if owner_account and owner_account.get("subscription_status") == "active":
                owner_plan = owner_account.get("plan", "starter")
                return (email, owner_plan if owner_plan in LIMITS else "starter")
        return (email, "starter")

    plan = account.get("plan", "pro")
    if plan not in LIMITS:
        plan = "pro"
    return (email, plan)


class AIRateLimit:
    """
    FastAPI dependency that gates AI routes with a fixed-window rate limit.

    Two windows are checked on every request:
      - Per-minute (burst):    tracked with a 60s Redis key
      - Per-hour (sustained):  tracked with a 3600s Redis key

    The key is the session token when present, falling back to client IP.
    """

    async def __call__(
        self,
        request: Request,
        agency_token: str | None = Cookie(default=None),
    ) -> None:
        rl_key   = agency_token or get_remote_address(request)
        user_id, plan = await _resolve(agency_token)
        limits   = LIMITS[plan]
        ts       = datetime.now(timezone.utc).isoformat()

        min_key  = f"rl:ai:min:{rl_key}"
        hour_key = f"rl:ai:hour:{rl_key}"

        min_count  = await redis_client.incr(min_key)
        if min_count == 1:
            await redis_client.expire(min_key, 60)

        hour_count = await redis_client.incr(hour_key)
        if hour_count == 1:
            await redis_client.expire(hour_key, 3600)

        if min_count > limits["minute"]:
            logger.warning(
                "AI rate limit hit (per-minute) | user=%s plan=%s count=%d/%d ts=%s",
                user_id, plan, min_count, limits["minute"], ts,
            )
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please wait before trying again",
            )

        if hour_count > limits["hour"]:
            logger.warning(
                "AI rate limit hit (per-hour) | user=%s plan=%s count=%d/%d ts=%s",
                user_id, plan, hour_count, limits["hour"], ts,
            )
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please wait before trying again",
            )
