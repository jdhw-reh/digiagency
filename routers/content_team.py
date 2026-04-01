"""Content Team router — all routes live under /api/content/"""

import asyncio
import os
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from state import get_session, save_session, get_user, log_activity
from utils.sse import SSE_HEADERS, sse_chunk, sse_done, sse_event
from agents.content import researcher, planner, writer
from services.notion import create_article_page
from services.agency_log import log_task

router = APIRouter()

_SESSION_DEFAULTS = {
    "stage": "idle",
    "business_context": "",
    "topics": [],
    "selected_topic": None,
    "brief": "",
    "article": "",
    "notion_url": None,
    "saved_articles": [],
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
    return u.get("notion_token", ""), u.get("notion_content_db_id", "")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionPayload(BaseModel):
    user_id: str = ""


class ContextPayload(BaseModel):
    session_id: str
    context: str


class SelectTopicPayload(BaseModel):
    session_id: str
    topic_index: int


class SessionPayload(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(payload: CreateSessionPayload):
    sid = str(uuid.uuid4())
    defaults = {**_SESSION_DEFAULTS, "user_id": payload.user_id}
    await get_session(sid, "content", defaults)
    return {"session_id": sid}


@router.get("/state")
async def get_state(session_id: str):
    return await get_session(session_id, "content", _SESSION_DEFAULTS)


@router.post("/context")
async def save_context(payload: ContextPayload):
    session = await get_session(payload.session_id, "content", _SESSION_DEFAULTS)
    session["business_context"] = payload.context
    await save_session(payload.session_id, session)
    return {"ok": True}


@router.post("/select-topic")
async def select_topic(payload: SelectTopicPayload):
    session = await get_session(payload.session_id, "content", _SESSION_DEFAULTS)
    topics = session.get("topics", [])
    if payload.topic_index < 0 or payload.topic_index >= len(topics):
        return JSONResponse({"error": "Invalid topic index"}, status_code=400)
    session["selected_topic"] = topics[payload.topic_index]
    session["stage"] = "awaiting_write"
    await save_session(payload.session_id, session)
    return {"ok": True, "topic": session["selected_topic"]}


# ---------------------------------------------------------------------------
# Streaming endpoints (GET — EventSource only supports GET)
# ---------------------------------------------------------------------------

@router.get("/stream/research")
async def stream_research(session_id: str):
    session = await get_session(session_id, "content", _SESSION_DEFAULTS)
    if session["stage"] not in ("idle",):
        return JSONResponse({"error": "Session not in idle stage"}, status_code=400)

    session["stage"] = "researching"
    session["topics"] = []
    session["selected_topic"] = None
    session["brief"] = ""
    session["article"] = ""
    session["notion_url"] = None
    await save_session(session_id, session)

    api_key = await _get_api_key(session)

    async def event_generator():
        async for chunk in researcher.run(session["business_context"], api_key=api_key):
            if isinstance(chunk, str):
                yield sse_chunk(chunk)
            elif isinstance(chunk, dict):
                if chunk.get("type") == "topics":
                    session["topics"] = chunk.get("data", [])
                    session["stage"] = "awaiting_topic"
                    await save_session(session_id, session)
                    yield sse_event({"type": "topics", "data": session["topics"]})
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/stream/plan")
async def stream_plan(session_id: str):
    session = await get_session(session_id, "content", _SESSION_DEFAULTS)
    if session.get("selected_topic") is None:
        return JSONResponse({"error": "No topic selected"}, status_code=400)

    session["stage"] = "planning"
    await save_session(session_id, session)
    brief_parts: list[str] = []
    api_key = await _get_api_key(session)

    async def event_generator():
        async for chunk in planner.run(session["selected_topic"], session["business_context"], api_key=api_key):
            brief_parts.append(chunk)
            yield sse_chunk(chunk)
        session["brief"] = "".join(brief_parts)
        session["stage"] = "awaiting_write"
        await save_session(session_id, session)
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/stream/write")
async def stream_write(session_id: str):
    session = await get_session(session_id, "content", _SESSION_DEFAULTS)
    if not session.get("brief"):
        return JSONResponse({"error": "No content brief available"}, status_code=400)

    session["stage"] = "writing"
    await save_session(session_id, session)
    article_parts: list[str] = []
    api_key = await _get_api_key(session)

    async def event_generator():
        async for chunk in writer.run(
            session["brief"], session["selected_topic"], session["business_context"], api_key=api_key
        ):
            article_parts.append(chunk)
            yield sse_chunk(chunk)
        session["article"] = "".join(article_parts)
        session["stage"] = "done"
        await save_session(session_id, session)
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------------------------------------------------------------------
# Save to Notion
# ---------------------------------------------------------------------------

@router.post("/save-notion")
async def save_notion(payload: SessionPayload):
    session = await get_session(payload.session_id, "content", _SESSION_DEFAULTS)
    if not session.get("article"):
        return JSONResponse({"error": "No article to save"}, status_code=400)
    if not session.get("selected_topic"):
        return JSONResponse({"error": "No topic selected"}, status_code=400)

    notion_token, database_id = await _get_notion_creds(session)
    if not notion_token or not database_id:
        return JSONResponse({"error": "Notion is not configured. Complete Notion setup in Settings."}, status_code=400)

    title = session["selected_topic"]["title"]
    url = await create_article_page(title, session["article"], session["selected_topic"], notion_token, database_id)
    session["notion_url"] = url
    await log_activity("content", f"Saved article: {title}")

    entry = {"title": title, "url": url}
    session["saved_articles"].append(entry)
    await save_session(payload.session_id, session)

    user = await get_user(session.get("user_id", ""))
    u = user or {}
    asyncio.ensure_future(log_task(
        "Content Team", "Article", title, link=url,
        notion_token=u.get("notion_token", ""),
        db_id=u.get("notion_agency_log_db_id", ""),
    ))

    return {"url": url, "title": title}


# ---------------------------------------------------------------------------
# Reset session (start a new article)
# ---------------------------------------------------------------------------

@router.post("/reset")
async def reset_session(payload: SessionPayload):
    session = await get_session(payload.session_id, "content", _SESSION_DEFAULTS)
    saved = session.get("saved_articles", [])
    new_session = {
        "team": "content",
        "user_id": session.get("user_id", ""),
        "business_context": session.get("business_context", ""),
        "stage": "idle",
        "topics": [],
        "selected_topic": None,
        "brief": "",
        "article": "",
        "notion_url": None,
        "saved_articles": saved,
    }
    await save_session(payload.session_id, new_session)
    return {"ok": True}
