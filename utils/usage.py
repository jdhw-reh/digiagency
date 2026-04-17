"""
Monthly per-tool usage caps and counters for Starter plan users.

MONTHLY_CAPS defines the maximum number of completed outputs per tool per calendar
month for each plan.  None = unlimited.  0 = tool locked regardless of count.

Counters are stored in Redis under the key:
    usage:{email}:{tool}:{YYYY-MM}

Each key expires at 00:00 UTC on the first day of the following month so
counters always reset on a calendar boundary, not on a rolling 30-day window.
"""

from datetime import datetime, timezone

from fastapi import Cookie, HTTPException, Request

from state import get_account, get_token_email, redis_client

_TOOLS = ["content", "social", "seo_audit", "video", "on_page_opt", "assistant"]

MONTHLY_CAPS: dict[str, dict[str, int | None]] = {
    "starter": {
        "content":     8,
        "social":      5,
        "seo_audit":   3,
        "video":       0,    # 0 = locked entirely — no access on Starter
        "on_page_opt": 5,
        "assistant":   50,
    },
    "pro":    {k: None for k in _TOOLS},
    "agency": {k: None for k in _TOOLS},
}


def get_usage_key(email: str, tool: str) -> str:
    """Return the Redis key for this user/tool in the current calendar month."""
    return f"usage:{email.lower()}:{tool}:{datetime.utcnow().strftime('%Y-%m')}"


async def get_current_usage(redis, email: str, tool: str) -> int:
    """Return the number of completed outputs for this user/tool this month."""
    val = await redis.get(get_usage_key(email, tool))
    return int(val) if val else 0


async def increment_usage(redis, email: str, tool: str) -> int:
    """
    Increment the monthly counter and set it to expire at the start of next month.

    Returns the new count.
    """
    key = get_usage_key(email, tool)
    new_count = await redis.incr(key)

    # Expire at 00:00 UTC on the first day of the next calendar month.
    now = datetime.now(timezone.utc)
    if now.month == 12:
        reset = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        reset = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

    await redis.expireat(key, reset)
    return new_count


class ToolAccess:
    """
    FastAPI dependency that enforces monthly per-tool caps for Starter plan users.

    Usage::

        @router.post("/session")
        async def create_session(
            payload: CreateSessionPayload,
            _: None = Depends(ToolAccess("content")),
        ):
            ...

    Raises:
        403  if cap == 0  (tool locked on this plan)
        429  if cap > 0 and the user has already reached their monthly limit
    """

    def __init__(self, tool: str) -> None:
        self.tool = tool

    async def __call__(
        self,
        request: Request,
        agency_token: str | None = Cookie(default=None),
    ) -> None:
        email = await get_token_email(agency_token) if agency_token else None
        if not email:
            # Auth middleware already rejects unauthenticated requests before
            # we get here.  If email can't be resolved, allow through silently
            # so the existing 401 path handles it cleanly.
            return

        account = await get_account(email)
        plan = (account or {}).get("plan", "pro")

        # Team members inherit the owner's plan
        if (account or {}).get("team_role") == "member":
            team_id = (account or {}).get("team_id")
            if team_id:
                from state import get_team
                team = await get_team(team_id)
                if team:
                    owner_account = await get_account(team["owner_email"])
                    if owner_account and owner_account.get("subscription_status") == "active":
                        plan = owner_account.get("plan", "starter") or "starter"

        if plan not in MONTHLY_CAPS:
            plan = "pro"

        cap = MONTHLY_CAPS[plan].get(self.tool)

        if cap == 0:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "tool_locked",
                    "message": "The Video Director is available on Pro and Agency plans.",
                    "upgrade_required": True,
                },
            )

        if cap is None:
            # Unlimited plan — allow through.
            return

        used = await get_current_usage(redis_client, email, self.tool)
        if used >= cap:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "monthly_limit_reached",
                    "tool": self.tool,
                    "limit": cap,
                    "used": used,
                    "message": (
                        f"You've used all {cap} of your monthly {self.tool} outputs. "
                        "Resets on the 1st."
                    ),
                    "upgrade_required": True,
                },
            )
