"""Video Director Team router — all routes live under /api/video/"""

import asyncio
import os
import uuid

from fastapi import APIRouter, Cookie, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import sys

from state import get_session, save_session, get_user, get_user_by_email, log_activity, get_token_email, log_history_item, get_rollback_stage, redis_client
from utils.usage import ToolAccess, increment_usage
from utils.sanitise import sanitise_user_input
from utils.sse import SSE_HEADERS, sse_chunk, sse_done, sse_event, friendly_error
from agents.video import director
from services.notion_video import save_brief
from services.agency_log import log_task

router = APIRouter()

_SESSION_DEFAULTS = {
    "stage": "idle",
    "brief": "",
    "platform": "",
    "duration": "",
    "concept": {},
    "shots": [],
    "saved_briefs": [],
    "user_id": "",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_api_key(session: dict, agency_token: str | None = None) -> str:
    user = await get_user(session.get("user_id", ""))
    key = (user or {}).get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not key and agency_token:
        email = await get_token_email(agency_token)
        if email:
            user = await get_user_by_email(email)
            key = (user or {}).get("gemini_api_key") or ""
    return key


async def _get_notion_creds(session: dict) -> tuple[str, str]:
    user = await get_user(session.get("user_id", ""))
    u = user or {}
    return u.get("notion_token", ""), u.get("notion_video_db_id", "")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionPayload(BaseModel):
    user_id: str = ""


class BriefPayload(BaseModel):
    session_id: str
    brief: str
    platform: str = "TikTok"
    duration: str = "30"


class SessionPayload(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(
    payload: CreateSessionPayload,
    _: None = Depends(ToolAccess("video")),
):
    sid = str(uuid.uuid4())
    defaults = {**_SESSION_DEFAULTS, "user_id": payload.user_id}
    await get_session(sid, "video", defaults)
    return {"session_id": sid}


@router.get("/state")
async def get_state(session_id: str):
    return await get_session(session_id, "video", _SESSION_DEFAULTS)


@router.post("/brief")
async def save_brief_context(payload: BriefPayload):
    session = await get_session(payload.session_id, "video", _SESSION_DEFAULTS)
    session["brief"] = sanitise_user_input(payload.brief, user_id=session.get("user_id"))
    session["platform"] = sanitise_user_input(payload.platform, user_id=session.get("user_id"))
    session["duration"] = sanitise_user_input(payload.duration, user_id=session.get("user_id"))
    await save_session(payload.session_id, session)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Streaming endpoint
# ---------------------------------------------------------------------------

@router.get("/stream/direct")
async def stream_direct(session_id: str, agency_token: str | None = Cookie(default=None)):
    session = await get_session(session_id, "video", _SESSION_DEFAULTS)

    if not session.get("brief"):
        return JSONResponse({"error": "No brief provided"}, status_code=400)

    session["stage"] = "directing"
    session["concept"] = {}
    session["shots"] = []
    await save_session(session_id, session)

    api_key = await _get_api_key(session, agency_token)
    if not api_key:
        async def no_key(): yield sse_event({"type": "error", "code": "gemini_not_configured", "message": "Gemini API key not set. Open Settings to configure it."})
        return StreamingResponse(no_key(), media_type="text/event-stream", headers=SSE_HEADERS)
    notion_token, database_id = await _get_notion_creds(session)
    user = await get_user(session.get("user_id", ""))
    u = user or {}
    email = await get_token_email(agency_token) if agency_token else None
    text_parts: list[str] = []

    async def event_generator():
        failed = False
        try:
            async for chunk in director.run(
                session["brief"],
                session["platform"],
                session["duration"],
                api_key=api_key,
            ):
                if isinstance(chunk, str):
                    text_parts.append(chunk)
                    yield sse_chunk(chunk)
                elif isinstance(chunk, dict):
                    if chunk.get("type") == "error":
                        session["stage"] = get_rollback_stage("video", "directing")
                        await save_session(session_id, session)
                        yield sse_event({"type": "error", "message": friendly_error(chunk["message"])})
                        failed = True
                        break
                    elif chunk.get("type") == "shots":
                        data = chunk.get("data", {})
                        session["concept"] = data.get("concept", {})
                        session["shots"] = data.get("shots", [])
                        session["stage"] = "done"
                        await save_session(session_id, session)
                        yield sse_event({"type": "shots", "data": data})

                        # Auto-save to Notion if configured
                        if notion_token and database_id:
                            try:
                                url = await save_brief(session["concept"], session["shots"], notion_token=notion_token, database_id=database_id)
                                session["saved_briefs"].append(url)
                                await save_session(session_id, session)
                                title = session["concept"].get("title") or "Video brief"
                                await log_activity("video", f"Saved video brief: {title}", email=email)
                                asyncio.ensure_future(log_task(
                                    "Video Team", "Video Brief", title,
                                    notion_token=u.get("notion_token", ""),
                                    db_id=u.get("notion_agency_log_db_id", ""),
                                ))
                                yield sse_event({"type": "saved", "url": url})
                            except Exception:
                                pass  # Notion save failure shouldn't break the stream
        except Exception as exc:
            print(f"[ERROR] video/direct session={session_id}: {exc}", file=sys.stderr)
            session["stage"] = get_rollback_stage("video", "directing")
            await save_session(session_id, session)
            yield sse_event({"type": "error", "message": "Agent failed. Please try again."})
            failed = True
        finally:
            if not failed and email and session.get("stage") == "done" and text_parts:
                title = session["concept"].get("title") or "Video brief"
                await log_history_item(email, "Video Director", title, "".join(text_parts))
                await increment_usage(redis_client, email, "video")
            yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------------------------------------------------------------------
# Save to Notion
# ---------------------------------------------------------------------------

@router.post("/save-notion")
async def save_to_notion(payload: SessionPayload, agency_token: str | None = Cookie(default=None)):
    session = await get_session(payload.session_id, "video", _SESSION_DEFAULTS)
    if not session.get("shots"):
        return JSONResponse({"error": "No shots to save"}, status_code=400)

    notion_token, database_id = await _get_notion_creds(session)
    if not notion_token or not database_id:
        return JSONResponse({"error": "Notion is not configured. Complete Notion setup in Settings."}, status_code=400)

    try:
        url = await save_brief(session["concept"], session["shots"], notion_token=notion_token, database_id=database_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    session["saved_briefs"].append(url)
    title = session["concept"].get("title") or "Video brief"
    email = await get_token_email(agency_token) if agency_token else None
    await log_activity("video", f"Saved video brief: {title}", email=email)
    await save_session(payload.session_id, session)

    user = await get_user(session.get("user_id", ""))
    u = user or {}
    asyncio.ensure_future(log_task(
        "Video Team", "Video Brief", title,
        notion_token=u.get("notion_token", ""),
        db_id=u.get("notion_agency_log_db_id", ""),
    ))

    return {"url": url}


# ---------------------------------------------------------------------------
# Reset session
# ---------------------------------------------------------------------------

@router.post("/reset")
async def reset_session(payload: SessionPayload):
    session = await get_session(payload.session_id, "video", _SESSION_DEFAULTS)
    saved = session.get("saved_briefs", [])
    new_session = {
        "team": "video",
        "user_id": session.get("user_id", ""),
        "brief": "",
        "platform": "",
        "duration": "",
        "stage": "idle",
        "concept": {},
        "shots": [],
        "saved_briefs": saved,
    }
    await save_session(payload.session_id, new_session)
    return {"ok": True}
