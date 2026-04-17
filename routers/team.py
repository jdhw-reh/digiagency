"""
Team management router.

POST   /api/team/request-access       — any authed user; submit workspace code to join
GET    /api/team/pending-requests     — owner only; list pending join requests
POST   /api/team/approve/{token}      — owner only (or email action)
POST   /api/team/deny/{token}         — owner only (or email action)
GET    /api/team                      — owner or member; get team info
DELETE /api/team/members/{email}      — owner only; remove a member
POST   /api/team/leave                — member only; leave the team
"""

import asyncio
import os

from fastapi import APIRouter, Cookie, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import (
    add_team_member,
    create_join_request,
    get_account,
    get_join_request,
    get_member_count,
    get_pending_requests_for_owner,
    get_team,
    get_token_email,
    redis_client,
    remove_team_member,
    resolve_join_request,
    save_account,
    set_account_team,
)
from services.email import send_approval_email, send_denial_email, send_join_request_email

router = APIRouter()

_CANONICAL_URL = os.environ.get("APP_URL", "https://digiagency.up.railway.app").rstrip("/")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RequestAccessPayload(BaseModel):
    workspace_code: str
    requester_name: str


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

async def _get_authed_email(agency_token: str | None) -> str | None:
    if not agency_token:
        return None
    return await get_token_email(agency_token)


# ---------------------------------------------------------------------------
# POST /api/team/request-access
# ---------------------------------------------------------------------------

@router.post("/request-access")
async def request_access(
    payload: RequestAccessPayload,
    agency_token: str | None = Cookie(default=None),
):
    email = await _get_authed_email(agency_token)
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    code = payload.workspace_code.strip().upper()
    owner_email = await redis_client.get(f"workspace_code:{code}")
    if not owner_email:
        return JSONResponse({"error": "Workspace code not found"}, status_code=404)

    if account.get("team_id"):
        return JSONResponse({"error": "You are already on a team"}, status_code=409)

    if email.lower() == owner_email.lower():
        return JSONResponse({"error": "You are the workspace owner"}, status_code=409)

    owner_account = await get_account(owner_email)
    if not owner_account:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    team_id = owner_account.get("team_id")
    if not team_id:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    seats = await get_member_count(team_id)
    if seats >= 5:
        return JSONResponse({"error": "Team is full"}, status_code=400)

    existing = await get_pending_requests_for_owner(owner_email)
    if any(r["requester_email"] == email.lower() for r in existing):
        return JSONResponse({"error": "A request is already pending"}, status_code=409)

    token = await create_join_request(code, owner_email, team_id, email, payload.requester_name)

    jr = await get_join_request(token) or {}
    eat = jr.get("email_action_token", "")
    approve_url = f"{_CANONICAL_URL}/api/team/approve/{token}?auth=email_action&eat={eat}"
    deny_url = f"{_CANONICAL_URL}/api/team/deny/{token}?auth=email_action&eat={eat}"

    asyncio.create_task(send_join_request_email(
        owner_email, email, payload.requester_name,
        approve_url, deny_url, seats,
    ))

    return {"message": "Request sent. The workspace owner will review your request."}


# ---------------------------------------------------------------------------
# GET /api/team/pending-requests
# ---------------------------------------------------------------------------

@router.get("/pending-requests")
async def list_pending_requests(agency_token: str | None = Cookie(default=None)):
    email = await _get_authed_email(agency_token)
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    account = await get_account(email)
    if not account or account.get("team_role") != "owner":
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    requests = await get_pending_requests_for_owner(email)
    return [
        {
            "token": r["token"],
            "requester_email": r["requester_email"],
            "requester_name": r["requester_name"],
            "created_at": r["created_at"],
        }
        for r in requests
    ]


# ---------------------------------------------------------------------------
# POST /api/team/approve/{token}
# ---------------------------------------------------------------------------

@router.post("/approve/{token}")
async def approve_member(
    token: str,
    auth: str | None = Query(default=None),
    eat: str | None = Query(default=None),
    agency_token: str | None = Cookie(default=None),
):
    join_req = await get_join_request(token)
    if not join_req:
        return JSONResponse({"error": "Request not found"}, status_code=404)
    if join_req.get("status") != "pending":
        return JSONResponse({"error": "Request already resolved"}, status_code=409)

    if auth == "email_action":
        if not eat or eat != join_req.get("email_action_token"):
            return JSONResponse({"error": "Invalid action token"}, status_code=403)
    else:
        email = await _get_authed_email(agency_token)
        if not email:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        account = await get_account(email)
        if not account or account.get("team_role") != "owner":
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        if account.get("team_id") != join_req.get("team_id"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

    team_id = join_req["team_id"]
    seats = await get_member_count(team_id)
    if seats >= 5:
        return JSONResponse({"error": "Team is full"}, status_code=400)

    requester_email = join_req["requester_email"]
    ok = await add_team_member(team_id, requester_email)
    if not ok:
        return JSONResponse({"error": "Team is full"}, status_code=400)

    await set_account_team(requester_email, team_id, "member")

    requester_account = await get_account(requester_email)
    if requester_account:
        requester_account["subscription_status"] = "active"
        await save_account(requester_email, requester_account)

    await resolve_join_request(token, "approved")

    asyncio.create_task(
        send_approval_email(requester_email, join_req["owner_email"])
    )

    return {"message": "Member approved"}


# ---------------------------------------------------------------------------
# POST /api/team/deny/{token}
# ---------------------------------------------------------------------------

@router.post("/deny/{token}")
async def deny_member(
    token: str,
    auth: str | None = Query(default=None),
    eat: str | None = Query(default=None),
    agency_token: str | None = Cookie(default=None),
):
    join_req = await get_join_request(token)
    if not join_req:
        return JSONResponse({"error": "Request not found"}, status_code=404)
    if join_req.get("status") != "pending":
        return JSONResponse({"error": "Request already resolved"}, status_code=409)

    if auth == "email_action":
        if not eat or eat != join_req.get("email_action_token"):
            return JSONResponse({"error": "Invalid action token"}, status_code=403)
    else:
        email = await _get_authed_email(agency_token)
        if not email:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        account = await get_account(email)
        if not account or account.get("team_role") != "owner":
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        if account.get("team_id") != join_req.get("team_id"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

    requester_email = join_req["requester_email"]
    requester_account = await get_account(requester_email)
    if requester_account:
        requester_account["subscription_status"] = "inactive"
        await save_account(requester_email, requester_account)

    await resolve_join_request(token, "denied")

    asyncio.create_task(
        send_denial_email(requester_email, join_req["owner_email"])
    )

    return {"message": "Request denied"}


# ---------------------------------------------------------------------------
# GET /api/team
# ---------------------------------------------------------------------------

@router.get("")
async def get_team_info(agency_token: str | None = Cookie(default=None)):
    email = await _get_authed_email(agency_token)
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)

    team_id = account.get("team_id")
    team_role = account.get("team_role")
    if not team_id or not team_role:
        return JSONResponse({"error": "Not on a team"}, status_code=404)

    team = await get_team(team_id)
    if not team:
        return JSONResponse({"error": "Team not found"}, status_code=404)

    seats_used = await get_member_count(team_id)
    response = {
        "team_id": team_id,
        "owner_email": team["owner_email"],
        "your_role": team_role,
        "members": team.get("members", []),
        "seats_used": seats_used,
        "max_seats": team.get("max_seats", 5),
    }
    if team_role == "owner":
        response["workspace_code"] = account.get("workspace_code", "")

    return response


# ---------------------------------------------------------------------------
# DELETE /api/team/members/{member_email}
# ---------------------------------------------------------------------------

@router.delete("/members/{member_email}")
async def remove_member(
    member_email: str,
    agency_token: str | None = Cookie(default=None),
):
    email = await _get_authed_email(agency_token)
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    account = await get_account(email)
    if not account or account.get("team_role") != "owner":
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    team_id = account.get("team_id")
    await remove_team_member(team_id, member_email)

    member_account = await get_account(member_email)
    if member_account:
        member_account.pop("team_id", None)
        member_account.pop("team_role", None)
        member_account["subscription_status"] = "inactive"
        await save_account(member_email, member_account)

    return {"message": "Member removed"}


# ---------------------------------------------------------------------------
# POST /api/team/leave
# ---------------------------------------------------------------------------

@router.post("/leave")
async def leave_team(agency_token: str | None = Cookie(default=None)):
    email = await _get_authed_email(agency_token)
    if not email:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    account = await get_account(email)
    if not account:
        return JSONResponse({"error": "Account not found"}, status_code=404)
    if account.get("team_role") == "owner":
        return JSONResponse({"error": "Owner cannot leave the team"}, status_code=403)

    team_id = account.get("team_id")
    if team_id:
        await remove_team_member(team_id, email)

    account.pop("team_id", None)
    account.pop("team_role", None)
    account["subscription_status"] = "inactive"
    await save_account(email, account)

    return {"message": "You have left the team"}
