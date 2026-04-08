"""
Setup router — user onboarding and Notion workspace provisioning.

POST /api/setup/user
    Create or update a user session (stores Gemini API key + Notion credentials).

POST /api/setup/notion/provision
    Auto-create all required Notion databases in the user's workspace.

GET  /api/setup/status?user_id=...
    Check whether a user is fully configured.
"""

import asyncio
import uuid

import httpx
from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_token_email, get_user, redis_client, save_user

router = APIRouter()

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SaveUserPayload(BaseModel):
    user_id: str = ""
    notion_token: str = ""
    notion_parent_page_id: str = ""


class ProvisionPayload(BaseModel):
    user_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _extract_page_id(url_or_id: str) -> str:
    """Extract the raw Notion page ID from a URL or bare ID string."""
    raw = url_or_id.strip().rstrip("/")
    # URL format: https://www.notion.so/Page-Title-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    # or: https://www.notion.so/workspace/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    part = raw.split("/")[-1]
    # Strip any query params
    part = part.split("?")[0]
    # Strip any anchor
    part = part.split("#")[0]
    # Remove dashes if it looks like a formatted UUID
    if "-" in part:
        return part.replace("-", "")
    return part


async def _create_database(
    client: httpx.AsyncClient,
    token: str,
    parent_page_id: str,
    title: str,
    properties: dict,
) -> str:
    """Create a Notion database and return its ID."""
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }
    r = await client.post(
        f"{_NOTION_BASE}/databases",
        headers=_notion_headers(token),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"].replace("-", "")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/user")
async def save_user_route(payload: SaveUserPayload, agency_token: str | None = Cookie(default=None)):
    """Create or update user credentials in Redis."""
    user_id = payload.user_id.strip() or str(uuid.uuid4())

    existing = await get_user(user_id) or {}
    existing.update({
        "notion_token": payload.notion_token.strip(),
        "notion_parent_page_id": _extract_page_id(payload.notion_parent_page_id) if payload.notion_parent_page_id else existing.get("notion_parent_page_id", ""),
    })
    await save_user(user_id, existing)

    # Link email → user_id so admin can check setup completion
    if agency_token:
        email = await get_token_email(agency_token)
        if email:
            await redis_client.set(f"account_user_id:{email}", user_id)

    return {
        "user_id": user_id,
        "notion_configured": bool(
            existing.get("notion_content_db_id")
            and existing.get("notion_token")
        ),
    }


@router.post("/notion/provision")
async def provision_notion(payload: ProvisionPayload):
    """
    Auto-create all 5 required Notion databases in the user's workspace.
    Stores the resulting database IDs in the user's Redis record.
    """
    user = await get_user(payload.user_id)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    token = user.get("notion_token", "")
    parent_page_id = user.get("notion_parent_page_id", "")

    if not token:
        return JSONResponse({"error": "No Notion token configured"}, status_code=400)
    if not parent_page_id:
        return JSONResponse({"error": "No Notion parent page configured"}, status_code=400)

    # Database schemas
    databases = {
        "notion_content_db_id": {
            "title": "Content Articles",
            "properties": {
                "Name": {"title": {}},
                "Status": {"select": {"options": [
                    {"name": "Draft", "color": "gray"},
                    {"name": "Ready", "color": "green"},
                ]}},
                "Primary Keyword": {"rich_text": {}},
                "Search Intent": {"select": {"options": [
                    {"name": "Informational", "color": "blue"},
                    {"name": "Commercial", "color": "yellow"},
                    {"name": "Transactional", "color": "red"},
                ]}},
                "Date Created": {"date": {}},
            },
        },
        "notion_social_db_id": {
            "title": "Social Posts",
            "properties": {
                "Name": {"title": {}},
                "Platform": {"select": {"options": [
                    {"name": "LinkedIn", "color": "blue"},
                    {"name": "X", "color": "gray"},
                    {"name": "Instagram", "color": "pink"},
                    {"name": "TikTok", "color": "purple"},
                    {"name": "YouTube", "color": "red"},
                    {"name": "Facebook", "color": "blue"},
                ]}},
                "Status": {"select": {"options": [
                    {"name": "Draft", "color": "gray"},
                    {"name": "Scheduled", "color": "yellow"},
                    {"name": "Posted", "color": "green"},
                ]}},
                "Date Created": {"date": {}},
            },
        },
        "notion_agency_log_db_id": {
            "title": "Agency Activity Log",
            "properties": {
                "Name": {"title": {}},
                "Team": {"select": {"options": [
                    {"name": "Content Team", "color": "blue"},
                    {"name": "Social Team", "color": "pink"},
                    {"name": "SEO Audit", "color": "orange"},
                    {"name": "Video Team", "color": "red"},
                    {"name": "On-Page Opt", "color": "green"},
                    {"name": "Assistant", "color": "purple"},
                ]}},
                "Type": {"select": {"options": [
                    {"name": "Article", "color": "blue"},
                    {"name": "Social Posts", "color": "pink"},
                    {"name": "SEO Audit", "color": "orange"},
                    {"name": "Video Brief", "color": "red"},
                    {"name": "On-Page Opt", "color": "green"},
                    {"name": "Note", "color": "gray"},
                ]}},
                "Status": {"select": {"options": [
                    {"name": "Completed", "color": "green"},
                ]}},
                "Date": {"date": {}},
                "Link": {"url": {}},
            },
        },
        "notion_video_db_id": {
            "title": "Video Briefs",
            "properties": {
                "Name": {"title": {}},
                "Platform": {"select": {"options": [
                    {"name": "TikTok", "color": "purple"},
                    {"name": "Instagram", "color": "pink"},
                    {"name": "YouTube", "color": "red"},
                    {"name": "Other", "color": "gray"},
                ]}},
                "Duration": {"rich_text": {}},
                "Visual Style": {"rich_text": {}},
                "Audio Mood": {"rich_text": {}},
                "Hook Strategy": {"rich_text": {}},
                "Status": {"select": {"options": [
                    {"name": "Draft", "color": "gray"},
                    {"name": "In Production", "color": "yellow"},
                    {"name": "Published", "color": "green"},
                ]}},
                "Date Created": {"date": {}},
            },
        },
        "notion_on_page_db_id": {
            "title": "On-Page Optimisations",
            "properties": {
                "Name": {"title": {}},
                "Status": {"select": {"options": [
                    {"name": "Done", "color": "green"},
                    {"name": "Draft", "color": "gray"},
                ]}},
                "Mode": {"select": {"options": [
                    {"name": "Review", "color": "blue"},
                    {"name": "Build", "color": "orange"},
                ]}},
                "Page Type": {"select": {"options": [
                    {"name": "Service Page", "color": "blue"},
                    {"name": "Blog Post", "color": "green"},
                    {"name": "Home Page", "color": "purple"},
                    {"name": "Landing Page", "color": "orange"},
                ]}},
                "Target Keyword": {"rich_text": {}},
                "Date": {"date": {}},
            },
        },
    }

    created: dict[str, str] = {}
    errors: list[str] = []

    async with httpx.AsyncClient() as client:
        for field, spec in databases.items():
            # Skip if already provisioned
            if user.get(field):
                created[field] = user[field]
                continue
            try:
                db_id = await _create_database(
                    client, token, parent_page_id, spec["title"], spec["properties"]
                )
                created[field] = db_id
            except httpx.HTTPStatusError as e:
                errors.append(f"{spec['title']}: {e.response.text}")
            except Exception as e:
                errors.append(f"{spec['title']}: {str(e)}")

    # Persist the IDs we successfully created
    user.update(created)
    await save_user(payload.user_id, user)

    return {
        "ok": len(errors) == 0,
        "databases": {
            "content": created.get("notion_content_db_id"),
            "social": created.get("notion_social_db_id"),
            "agency_log": created.get("notion_agency_log_db_id"),
            "video": created.get("notion_video_db_id"),
            "on_page": created.get("notion_on_page_db_id"),
        },
        "errors": errors,
    }


@router.get("/status")
async def setup_status(user_id: str):
    """Return setup completion status for the given user."""
    if not user_id:
        return {"configured": False, "notion_configured": False}

    user = await get_user(user_id)
    if not user:
        return {"configured": False, "notion_configured": False}

    notion_configured = bool(
        user.get("notion_token")
        and user.get("notion_content_db_id")
    )

    return {
        "configured": True,
        "notion_configured": notion_configured,
        "has_notion": bool(user.get("notion_token")),
        "databases_provisioned": notion_configured,
    }
