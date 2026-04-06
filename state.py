"""Shared Redis-backed session store, activity log, and notification broadcast.
Imported by all routers."""

import asyncio
import json
import os
import secrets
from datetime import datetime

import bcrypt
import redis.asyncio as aioredis

TEAMS = ["content", "social", "video", "seo_audit", "on_page_opt"]

redis_client: aioredis.Redis = aioredis.from_url(
    os.environ.get("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True,
)

SESSION_TTL = 86400       # 24 hours — team sessions
USER_TTL = 86400 * 30     # 30 days — user credential sessions


# ---------------------------------------------------------------------------
# Team sessions
# ---------------------------------------------------------------------------

async def get_session(sid: str, team: str, defaults: dict) -> dict:
    """Fetch session from Redis; create with defaults if it doesn't exist."""
    raw = await redis_client.get(f"session:{sid}")
    if raw:
        return json.loads(raw)
    data = {"team": team, **defaults}
    await save_session(sid, data)
    return data


async def save_session(sid: str, data: dict) -> None:
    await redis_client.setex(f"session:{sid}", SESSION_TTL, json.dumps(data))


# ---------------------------------------------------------------------------
# User sessions (credentials + provisioned Notion DB IDs)
# ---------------------------------------------------------------------------

async def get_user(user_id: str) -> dict | None:
    raw = await redis_client.get(f"user:{user_id}")
    return json.loads(raw) if raw else None


async def save_user(user_id: str, data: dict) -> None:
    await redis_client.setex(f"user:{user_id}", USER_TTL, json.dumps(data))


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

async def log_activity(team: str, action: str, email: str | None = None) -> None:
    now_dt = datetime.utcnow()
    event = {
        "team": team,
        "action": action,
        "ts": now_dt.isoformat() + "Z",
    }
    if email:
        event["email"] = email
    await redis_client.lpush("activity_log", json.dumps(event))
    await redis_client.ltrim("activity_log", 0, 29)
    if email:
        await redis_client.lpush(f"user_activity:{email}", json.dumps(event))
        await redis_client.ltrim(f"user_activity:{email}", 0, 19)
    await redis_client.incr(f"analytics:team:{team}")
    await redis_client.incr(f"analytics:hour:{now_dt.hour}")
    await redis_client.incr(f"analytics:weekday:{now_dt.weekday()}")
    for q in _notification_subscribers:
        q.put_nowait(event)


async def get_activity_log(limit: int = 10) -> list[dict]:
    items = await redis_client.lrange("activity_log", 0, limit - 1)
    return [json.loads(i) for i in items]


async def get_user_activity(email: str, limit: int = 20) -> list[dict]:
    items = await redis_client.lrange(f"user_activity:{email}", 0, limit - 1)
    return [json.loads(i) for i in items]


# ---------------------------------------------------------------------------
# Admin notes (freeform per-user notes visible only in admin panel)
# ---------------------------------------------------------------------------

async def get_admin_note(email: str) -> str:
    return await redis_client.get(f"admin_note:{email.lower()}") or ""


async def save_admin_note(email: str, note: str) -> None:
    key = f"admin_note:{email.lower()}"
    if note.strip():
        await redis_client.setex(key, 86400 * 365, note)
    else:
        await redis_client.delete(key)


async def list_accounts_enriched() -> list[dict]:
    """list_accounts() enriched with last_activity_at, activity_count, setup_complete, is_churn_risk."""
    accounts = await list_accounts()
    if not accounts:
        return []

    pipe = redis_client.pipeline()
    for a in accounts:
        email = a["email"]
        pipe.lindex(f"user_activity:{email}", 0)   # most recent activity item
        pipe.llen(f"user_activity:{email}")         # total activity count
        pipe.get(f"account_user_id:{email}")        # linked user_id (set during setup)
    results = await pipe.execute()

    now = datetime.utcnow()
    for i, a in enumerate(accounts):
        raw_latest = results[i * 3]
        count = int(results[i * 3 + 1] or 0)
        user_id = results[i * 3 + 2]

        last_activity_at = None
        if raw_latest:
            try:
                last_activity_at = json.loads(raw_latest).get("ts")
            except Exception:
                pass

        a["activity_count"] = count
        a["last_activity_at"] = last_activity_at
        a["setup_complete"] = bool(user_id)

        is_churn_risk = False
        if a.get("subscription_status") == "active":
            if not last_activity_at:
                is_churn_risk = True
            else:
                try:
                    delta = now - datetime.fromisoformat(last_activity_at.rstrip("Z"))
                    is_churn_risk = delta.total_seconds() > 7 * 86400
                except Exception:
                    pass
        a["is_churn_risk"] = is_churn_risk

    return accounts


async def get_analytics_counters() -> dict:
    keys = (
        [f"analytics:team:{t}" for t in TEAMS]
        + [f"analytics:hour:{h}" for h in range(24)]
        + [f"analytics:weekday:{d}" for d in range(7)]
    )
    values = await redis_client.mget(keys)
    n = len(TEAMS)
    return {
        "team_usage": {t: int(values[i] or 0) for i, t in enumerate(TEAMS)},
        "activity_by_hour": [int(values[n + h] or 0) for h in range(24)],
        "activity_by_weekday": [int(values[n + 24 + d] or 0) for d in range(7)],
    }


# ---------------------------------------------------------------------------
# Account management (email/password auth + subscription status)
# ---------------------------------------------------------------------------

ACCOUNT_TTL = 86400 * 365  # 1 year
AUTH_TOKEN_TTL = 86400 * 30  # 30 days


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


async def get_account(email: str) -> dict | None:
    raw = await redis_client.get(f"account:{email.lower()}")
    return json.loads(raw) if raw else None


async def save_account(email: str, data: dict) -> None:
    await redis_client.setex(f"account:{email.lower()}", ACCOUNT_TTL, json.dumps(data))


async def create_auth_token(email: str) -> str:
    token = secrets.token_urlsafe(32)
    await redis_client.setex(f"auth_token:{token}", AUTH_TOKEN_TTL, email.lower())
    return token


async def get_token_email(token: str) -> str | None:
    return await redis_client.get(f"auth_token:{token}")


async def delete_auth_token(token: str) -> None:
    await redis_client.delete(f"auth_token:{token}")


async def list_accounts() -> list[dict]:
    keys = [k async for k in redis_client.scan_iter("account:*")]
    if not keys:
        return []
    values = await redis_client.mget(keys)
    accounts = []
    for v in values:
        if v:
            a = json.loads(v)
            a.pop("password_hash", None)  # never expose hashes
            accounts.append(a)
    return sorted(accounts, key=lambda a: a.get("created_at", ""), reverse=True)


# ---------------------------------------------------------------------------
# Content history (per-user log of completed tool outputs)
# ---------------------------------------------------------------------------

HISTORY_TTL = 86400 * 90  # 90 days


async def log_history_item(email: str, tool: str, title: str, output: str) -> None:
    entry = {
        "tool": tool,
        "title": title,
        "output": output,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    key = f"history:{email.lower()}"
    await redis_client.lpush(key, json.dumps(entry))
    await redis_client.ltrim(key, 0, 19)
    await redis_client.expire(key, HISTORY_TTL)


async def get_history(email: str, limit: int = 20) -> list[dict]:
    items = await redis_client.lrange(f"history:{email.lower()}", 0, limit - 1)
    return [json.loads(i) for i in items]


# ---------------------------------------------------------------------------
# SSE notification broadcast (in-memory — asyncio.Queue can't be serialised)
# ---------------------------------------------------------------------------

_notification_subscribers: list[asyncio.Queue] = []


def subscribe_notifications() -> asyncio.Queue:
    """Register a new SSE listener. Returns a queue that receives event dicts."""
    q: asyncio.Queue = asyncio.Queue()
    _notification_subscribers.append(q)
    return q


def unsubscribe_notifications(q: asyncio.Queue) -> None:
    try:
        _notification_subscribers.remove(q)
    except ValueError:
        pass
