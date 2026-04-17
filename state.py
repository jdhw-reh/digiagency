"""Shared Redis-backed session store, activity log, and notification broadcast.
Imported by all routers."""

import asyncio
import json
import os
import secrets
import uuid
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


async def get_user_by_email(email: str) -> dict | None:
    """Look up user data via account_user_id:{email} — fallback when session user_id is stale."""
    user_id = await redis_client.get(f"account_user_id:{email.lower()}")
    if not user_id:
        return None
    return await get_user(user_id)


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
# Agency teams
# ---------------------------------------------------------------------------

TEAM_TTL = 86400 * 400  # 400 days


async def create_team(owner_email: str) -> str:
    """Create a team record and reverse-lookup key. Returns team_id."""
    team_id = str(uuid.uuid4())
    record = {
        "team_id": team_id,
        "owner_email": owner_email,
        "members": [],
        "max_seats": 5,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    await redis_client.setex(f"team:{team_id}", TEAM_TTL, json.dumps(record))
    await redis_client.setex(f"team_owner:{owner_email.lower()}", TEAM_TTL, team_id)
    return team_id


async def get_team(team_id: str) -> dict | None:
    raw = await redis_client.get(f"team:{team_id}")
    return json.loads(raw) if raw else None


async def get_team_by_owner(owner_email: str) -> dict | None:
    team_id = await redis_client.get(f"team_owner:{owner_email.lower()}")
    if not team_id:
        return None
    return await get_team(team_id)


async def add_team_member(team_id: str, member_email: str) -> bool:
    """Append member. Returns False if already at max_seats (owner counts as 1)."""
    raw = await redis_client.get(f"team:{team_id}")
    if not raw:
        return False
    team = json.loads(raw)
    occupied = 1 + len(team["members"])
    if occupied >= team["max_seats"]:
        return False
    team["members"].append({
        "email": member_email.lower(),
        "joined_at": datetime.utcnow().isoformat() + "Z",
    })
    await redis_client.setex(f"team:{team_id}", TEAM_TTL, json.dumps(team))
    return True


async def remove_team_member(team_id: str, member_email: str) -> None:
    raw = await redis_client.get(f"team:{team_id}")
    if not raw:
        return
    team = json.loads(raw)
    team["members"] = [m for m in team["members"] if m["email"] != member_email.lower()]
    await redis_client.setex(f"team:{team_id}", TEAM_TTL, json.dumps(team))


async def get_member_count(team_id: str) -> int:
    """Owner counts as 1 seat."""
    raw = await redis_client.get(f"team:{team_id}")
    if not raw:
        return 0
    team = json.loads(raw)
    return 1 + len(team["members"])


async def set_account_team(email: str, team_id: str, role: str) -> None:
    """Update account record with team_id and team_role, preserving all other fields."""
    account = await get_account(email)
    if not account:
        return
    account["team_id"] = team_id
    account["team_role"] = role
    await save_account(email, account)


async def get_account_team(email: str) -> tuple[str, str] | None:
    """Return (team_id, team_role) or None if not on a team."""
    account = await get_account(email)
    if not account:
        return None
    team_id = account.get("team_id")
    team_role = account.get("team_role")
    if team_id and team_role:
        return (team_id, team_role)
    return None


# ---------------------------------------------------------------------------
# Pending join requests
# ---------------------------------------------------------------------------

JOIN_REQUEST_TTL = 72 * 3600  # 72 hours


async def create_join_request(
    workspace_code: str,
    owner_email: str,
    team_id: str,
    requester_email: str,
    requester_name: str,
) -> str:
    """Create a join request. Returns the request token."""
    token = secrets.token_urlsafe(32)
    email_action_token = secrets.token_urlsafe(16)
    record = {
        "token": token,
        "workspace_code": workspace_code,
        "owner_email": owner_email,
        "team_id": team_id,
        "requester_email": requester_email.lower(),
        "requester_name": requester_name,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "pending",
        "email_action_token": email_action_token,
    }
    await redis_client.setex(f"join_request:{token}", JOIN_REQUEST_TTL, json.dumps(record))
    await redis_client.sadd(f"pending_requests:{owner_email.lower()}", token)
    return token


async def get_join_request(token: str) -> dict | None:
    raw = await redis_client.get(f"join_request:{token}")
    return json.loads(raw) if raw else None


async def get_pending_requests_for_owner(owner_email: str) -> list[dict]:
    """Return all non-expired pending join requests for this owner."""
    tokens = await redis_client.smembers(f"pending_requests:{owner_email.lower()}")
    if not tokens:
        return []
    requests = []
    for token in tokens:
        req = await get_join_request(token)
        if req and req.get("status") == "pending":
            requests.append(req)
        elif not req:
            await redis_client.srem(f"pending_requests:{owner_email.lower()}", token)
    return requests


async def resolve_join_request(token: str, status: str) -> None:
    """Update status to 'approved' or 'denied'; remove from owner's pending set."""
    raw = await redis_client.get(f"join_request:{token}")
    if not raw:
        return
    record = json.loads(raw)
    record["status"] = status
    await redis_client.setex(f"join_request:{token}", JOIN_REQUEST_TTL, json.dumps(record))
    owner_email = record.get("owner_email", "")
    if owner_email:
        await redis_client.srem(f"pending_requests:{owner_email.lower()}", token)


# ---------------------------------------------------------------------------
# Content history (per-user log of completed tool outputs)
# ---------------------------------------------------------------------------

HISTORY_TTL = 86400 * 90  # 90 days


async def log_history_item(email: str, tool: str, title: str, output: str) -> None:
    entry = {
        "id": str(uuid.uuid4()),
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


async def delete_history_item(email: str, item_id: str) -> bool:
    key = f"history:{email.lower()}"
    items = await redis_client.lrange(key, 0, -1)
    for raw in items:
        entry = json.loads(raw)
        if entry.get("id") == item_id:
            await redis_client.lrem(key, 1, raw)
            return True
    return False


# ---------------------------------------------------------------------------
# Admin audit log
# ---------------------------------------------------------------------------

async def log_admin_action(admin_email: str, action: str, target: str, details: str = "") -> None:
    """Append an admin action to the audit log (capped at 500 entries)."""
    entry = {
        "admin": admin_email,
        "action": action,
        "target": target,
        "details": details,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    await redis_client.lpush("admin_audit_log", json.dumps(entry))
    await redis_client.ltrim("admin_audit_log", 0, 499)


async def get_admin_audit_log(limit: int = 100) -> list[dict]:
    items = await redis_client.lrange("admin_audit_log", 0, limit - 1)
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


# ---------------------------------------------------------------------------
# Stage rollback map — returns the stage to revert to on agent error
# ---------------------------------------------------------------------------

_ROLLBACK_STAGES: dict[str, dict[str, str]] = {
    "content": {
        "researching": "idle",
        "planning": "awaiting_topic",
        "writing": "awaiting_write",
    },
    "social": {
        "scouting": "idle",
        "strategising": "awaiting_idea",
        "writing_posts": "awaiting_copy",
    },
    "seo_audit": {
        "auditing": "idle",
        "analysing": "awaiting_analyse",
        "recommending": "awaiting_recommend",
        "implementing": "awaiting_implement",
    },
    "on_page_opt": {
        "analysing": "idle",
        "rewriting": "awaiting_rewrite",
        "researching": "idle",
        "writing": "awaiting_write",
    },
    "video": {
        "directing": "idle",
    },
}


def get_rollback_stage(team: str, current_stage: str) -> str:
    """Return the stage to revert to when an agent errors mid-run."""
    return _ROLLBACK_STAGES.get(team, {}).get(current_stage, "idle")
