"""Social Media Team router — all routes live under /api/social/"""

import asyncio
import os
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from state import get_session, save_session, get_user, log_activity
from utils.sse import SSE_HEADERS, sse_chunk, sse_done, sse_event
from agents.social import scout, strategist, copywriter
from services.notion_social import save_posts
from services.agency_log import log_task

router = APIRouter()

_SESSION_DEFAULTS = {
    "stage": "idle",
    "profile_url": "",
    "description": "",
    "detected_platform": "",
    "opportunities": [],
    "selected_opportunity": None,
    "calendar": "",
    "posts": [],
    "saved_posts": [],
    "user_id": "",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_api_key(session: dict) -> str:
    user = await get_user(session.get("user_id", ""))
    return (user or {}).get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")


async def _get_notion_creds(session: dict) -> tuple[str, str]:
    user = await get_user(session.get("user_id", ""))
    u = user or {}
    return u.get("notion_token", ""), u.get("notion_social_db_id", "")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionPayload(BaseModel):
    user_id: str = ""


class ContextPayload(BaseModel):
    session_id: str
    profile_url: str
    description: str = ""
    detected_platform: str


class SelectOpportunityPayload(BaseModel):
    session_id: str
    opportunity_index: int


class SessionPayload(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(payload: CreateSessionPayload):
    sid = str(uuid.uuid4())
    defaults = {**_SESSION_DEFAULTS, "user_id": payload.user_id}
    await get_session(sid, "social", defaults)
    return {"session_id": sid}


@router.get("/state")
async def get_state(session_id: str):
    return await get_session(session_id, "social", _SESSION_DEFAULTS)


@router.post("/context")
async def save_context(payload: ContextPayload):
    session = await get_session(payload.session_id, "social", _SESSION_DEFAULTS)
    session["profile_url"] = payload.profile_url
    session["description"] = payload.description
    session["detected_platform"] = payload.detected_platform
    await save_session(payload.session_id, session)
    return {"ok": True}


@router.post("/select-opportunity")
async def select_opportunity(payload: SelectOpportunityPayload):
    session = await get_session(payload.session_id, "social", _SESSION_DEFAULTS)
    opps = session.get("opportunities", [])
    if payload.opportunity_index < 0 or payload.opportunity_index >= len(opps):
        return JSONResponse({"error": "Invalid opportunity index"}, status_code=400)
    session["selected_opportunity"] = opps[payload.opportunity_index]
    session["stage"] = "awaiting_copy"
    await save_session(payload.session_id, session)
    return {"ok": True, "opportunity": session["selected_opportunity"]}


# ---------------------------------------------------------------------------
# Streaming endpoints
# ---------------------------------------------------------------------------

@router.get("/stream/scout")
async def stream_scout(session_id: str):
    session = await get_session(session_id, "social", _SESSION_DEFAULTS)
    if session["stage"] not in ("idle",):
        return JSONResponse({"error": "Session not in idle stage"}, status_code=400)
    if not session.get("profile_url"):
        return JSONResponse({"error": "No profile URL provided"}, status_code=400)

    session["stage"] = "scouting"
    session["opportunities"] = []
    session["selected_opportunity"] = None
    session["calendar"] = ""
    session["posts"] = []
    await save_session(session_id, session)
    api_key = await _get_api_key(session)

    async def event_generator():
        async for chunk in scout.run(
            session["profile_url"],
            session["description"],
            session["detected_platform"],
            api_key=api_key,
        ):
            if isinstance(chunk, str):
                yield sse_chunk(chunk)
            elif isinstance(chunk, dict):
                if chunk.get("type") == "opportunities":
                    session["opportunities"] = chunk.get("data", [])
                    session["stage"] = "awaiting_idea"
                    await save_session(session_id, session)
                    yield sse_event({"type": "opportunities", "data": session["opportunities"]})
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/stream/strategise")
async def stream_strategise(session_id: str):
    session = await get_session(session_id, "social", _SESSION_DEFAULTS)
    if session.get("selected_opportunity") is None:
        return JSONResponse({"error": "No opportunity selected"}, status_code=400)

    session["stage"] = "strategising"
    await save_session(session_id, session)
    calendar_parts: list[str] = []
    api_key = await _get_api_key(session)

    async def event_generator():
        async for chunk in strategist.run(
            session["selected_opportunity"],
            session["profile_url"],
            session["description"],
            session["detected_platform"],
            api_key=api_key,
        ):
            calendar_parts.append(chunk)
            yield sse_chunk(chunk)
        session["calendar"] = "".join(calendar_parts)
        session["stage"] = "awaiting_copy"
        await save_session(session_id, session)
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/stream/write-posts")
async def stream_write_posts(session_id: str):
    session = await get_session(session_id, "social", _SESSION_DEFAULTS)
    if not session.get("calendar"):
        return JSONResponse({"error": "No content calendar available"}, status_code=400)

    session["stage"] = "writing_posts"
    await save_session(session_id, session)
    post_text_parts: list[str] = []
    api_key = await _get_api_key(session)

    async def event_generator():
        async for chunk in copywriter.run(
            session["calendar"],
            session["profile_url"],
            session["description"],
            session["detected_platform"],
            api_key=api_key,
        ):
            if isinstance(chunk, str):
                post_text_parts.append(chunk)
                yield sse_chunk(chunk)
            elif isinstance(chunk, dict):
                if chunk.get("type") == "posts":
                    session["posts"] = chunk.get("data", [])
                    session["stage"] = "done"
                    await save_session(session_id, session)
                    yield sse_event({"type": "posts", "data": session["posts"]})
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------------------------------------------------------------------
# Save to Notion
# ---------------------------------------------------------------------------

@router.post("/save-notion")
async def save_to_notion(payload: SessionPayload):
    session = await get_session(payload.session_id, "social", _SESSION_DEFAULTS)
    if not session.get("posts"):
        return JSONResponse({"error": "No posts to save"}, status_code=400)

    notion_token, database_id = await _get_notion_creds(session)
    if not notion_token or not database_id:
        return JSONResponse({"error": "Notion is not configured. Complete Notion setup in Settings."}, status_code=400)

    try:
        saved = await save_posts(session["posts"], notion_token=notion_token, database_id=database_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    session["saved_posts"].extend(saved)
    post_count = len(session.get("posts", []))
    await log_activity("social", f"Saved {post_count} posts to Notion")
    await save_session(payload.session_id, session)

    opp = session.get("selected_opportunity") or {}
    title = opp.get("angle") or f"{post_count} social posts"
    user = await get_user(session.get("user_id", ""))
    u = user or {}
    asyncio.ensure_future(log_task(
        "Social Team", "Social Posts", title,
        notion_token=u.get("notion_token", ""),
        db_id=u.get("notion_agency_log_db_id", ""),
    ))

    return {"saved": saved}


# ---------------------------------------------------------------------------
# Reset session
# ---------------------------------------------------------------------------

@router.post("/reset")
async def reset_session(payload: SessionPayload):
    session = await get_session(payload.session_id, "social", _SESSION_DEFAULTS)
    saved = session.get("saved_posts", [])
    new_session = {
        "team": "social",
        "user_id": session.get("user_id", ""),
        "profile_url": session.get("profile_url", ""),
        "description": session.get("description", ""),
        "detected_platform": session.get("detected_platform", ""),
        "stage": "idle",
        "opportunities": [],
        "selected_opportunity": None,
        "calendar": "",
        "posts": [],
        "saved_posts": saved,
    }
    await save_session(payload.session_id, new_session)
    return {"ok": True}
