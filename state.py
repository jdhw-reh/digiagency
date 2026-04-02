"""Shared Redis-backed session store, activity log, and notification broadcast.
Imported by all routers."""

import asyncio
import json
import os
import secrets
from datetime import datetime

import bcrypt
import redis.asyncio as aioredis

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

async def log_activity(team: str, action: str) -> None:
    event = {
        "team": team,
        "action": action,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    await redis_client.lpush("activity_log", json.dumps(event))
    await redis_client.ltrim("activity_log", 0, 29)
    for q in _notification_subscribers:
        q.put_nowait(event)


async def get_activity_log(limit: int = 10) -> list[dict]:
    items = await redis_client.lrange("activity_log", 0, limit - 1)
    return [json.loads(i) for i in items]


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
