"""On-Page Optimiser Team router — all routes live under /api/on-page-opt/"""

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
from agents.on_page_opt import analyser, researcher, copywriter
from services.agency_log import log_task
from services.notion_on_page import save_optimiser_report

router = APIRouter()

_SESSION_DEFAULTS = {
    "stage": "idle",
    "mode": "review",
    "page_type": "",
    "target_keyword": "",
    "audit_context": "",
    "original_copy": "",
    "analysis": "",
    "prompt": "",
    "location": "",
    "keyword_data": {},
    "keyword_brief": "",
    "final_copy": "",
    "notion_url": None,
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
    return u.get("notion_token", ""), u.get("notion_on_page_db_id", "")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionPayload(BaseModel):
    user_id: str = ""


class StartReviewRequest(BaseModel):
    session_id: str
    copy: str
    target_keyword: str
    page_type: str
    audit_context: str = ""


class StartBuildRequest(BaseModel):
    session_id: str
    prompt: str
    page_type: str
    location: str = ""
    audit_context: str = ""


class SessionRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Routes — session management
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(
    payload: CreateSessionPayload,
    _: None = Depends(ToolAccess("on_page_opt")),
):
    sid = str(uuid.uuid4())
    defaults = {**_SESSION_DEFAULTS, "user_id": payload.user_id}
    await get_session(sid, "on_page_opt", defaults)
    return {"session_id": sid}


@router.get("/state")
async def get_state(session_id: str):
    sess = await get_session(session_id, "on_page_opt", _SESSION_DEFAULTS)
    return JSONResponse(sess)


@router.post("/reset")
async def reset_session(req: SessionRequest):
    sess = await get_session(req.session_id, "on_page_opt", _SESSION_DEFAULTS)
    sess.update({
        "mode": "review",
        "page_type": "",
        "target_keyword": "",
        "audit_context": "",
        "original_copy": "",
        "analysis": "",
        "prompt": "",
        "location": "",
        "keyword_data": {},
        "keyword_brief": "",
        "final_copy": "",
        "stage": "idle",
        "notion_url": None,
    })
    await save_session(req.session_id, sess)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Review mode — Analyse existing copy
# ---------------------------------------------------------------------------

_STUCK_STAGES_OPT = {"analysing", "researching", "rewriting", "writing"}

@router.post("/start-review")
async def start_review(req: StartReviewRequest, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(req.session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] in _STUCK_STAGES_OPT:
        # SSE connection likely dropped (common on iPad/Safari) — auto-reset and continue
        sess["stage"] = "idle"
    if sess["stage"] not in ("idle", "done"):
        return JSONResponse({"error": "Session already in progress"}, status_code=400)
    sess["mode"] = "review"
    sess["original_copy"] = sanitise_user_input(req.copy, user_id=sess.get("user_id"))
    sess["target_keyword"] = sanitise_user_input(req.target_keyword, user_id=sess.get("user_id"))
    sess["page_type"] = sanitise_user_input(req.page_type, user_id=sess.get("user_id"))
    sess["audit_context"] = sanitise_user_input(req.audit_context, user_id=sess.get("user_id"))
    sess["analysis"] = ""
    sess["final_copy"] = ""
    sess["notion_url"] = None
    sess["stage"] = "analysing"
    await save_session(req.session_id, sess)
    email = await get_token_email(agency_token) if agency_token else None
    await log_activity("on_page_opt", f"Started review: {req.page_type} — {req.target_keyword}", email=email)
    return {"ok": True}


@router.get("/stream/analysis")
async def stream_analysis(session_id: str, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "analysing":
        return JSONResponse({"error": "Not in analysing stage"}, status_code=400)

    api_key = await _get_api_key(sess, agency_token)
    if not api_key:
        async def no_key(): yield sse_event({"type": "error", "code": "gemini_not_configured", "message": "Gemini API key not set. Open Settings to configure it."})
        return StreamingResponse(no_key(), media_type="text/event-stream", headers=SSE_HEADERS)

    async def generate():
        full_text = ""
        try:
            async for kind, value in analyser.run(
                copy=sess["original_copy"],
                target_keyword=sess["target_keyword"],
                page_type=sess["page_type"],
                audit_context=sess["audit_context"],
                api_key=api_key,
            ):
                if kind == "chunk":
                    full_text += value
                    yield sse_chunk(value)
                elif kind == "done":
                    sess["analysis"] = full_text
                    sess["stage"] = "awaiting_rewrite"
                    await save_session(session_id, sess)
                    yield sse_done()
                    return
                elif kind == "error":
                    sess["stage"] = get_rollback_stage("on_page_opt", "analysing")
                    await save_session(session_id, sess)
                    yield sse_event({"type": "error", "message": friendly_error(value)})
                    yield sse_done()
                    return
        except Exception as exc:
            print(f"[ERROR] on_page_opt/analysis session={session_id}: {exc}", file=sys.stderr)
            sess["stage"] = get_rollback_stage("on_page_opt", "analysing")
            await save_session(session_id, sess)
            yield sse_event({"type": "error", "message": "Agent failed. Please try again."})
            yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/rewrite")
async def start_rewrite(req: SessionRequest):
    sess = await get_session(req.session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "awaiting_rewrite":
        return JSONResponse({"error": "Not ready to rewrite"}, status_code=400)
    sess["stage"] = "rewriting"
    await save_session(req.session_id, sess)
    return {"ok": True}


@router.get("/stream/rewrite")
async def stream_rewrite(session_id: str, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "rewriting":
        return JSONResponse({"error": "Not in rewriting stage"}, status_code=400)

    api_key = await _get_api_key(sess, agency_token)
    if not api_key:
        async def no_key(): yield sse_event({"type": "error", "code": "gemini_not_configured", "message": "Gemini API key not set. Open Settings to configure it."})
        return StreamingResponse(no_key(), media_type="text/event-stream", headers=SSE_HEADERS)
    email = await get_token_email(agency_token) if agency_token else None

    async def generate():
        full_text = ""
        try:
            async for kind, value in copywriter.run(
                mode="review",
                page_type=sess["page_type"],
                original_copy=sess["original_copy"],
                target_keyword=sess["target_keyword"],
                analysis=sess["analysis"],
                api_key=api_key,
            ):
                if kind == "chunk":
                    full_text += value
                    yield sse_chunk(value)
                elif kind == "done":
                    sess["final_copy"] = full_text
                    sess["stage"] = "done"
                    await save_session(session_id, sess)
                    await log_activity("on_page_opt", f"Optimised copy: {sess['page_type']}", email=email)
                    user = await get_user(sess.get("user_id", ""))
                    u = user or {}
                    asyncio.ensure_future(log_task(
                        "On-Page Opt", "On-Page Opt", f"Review: {sess['page_type']} — {sess['target_keyword']}",
                        notion_token=u.get("notion_token", ""),
                        db_id=u.get("notion_agency_log_db_id", ""),
                    ))
                    if email and full_text:
                        title = f"Review: {sess['page_type']} — {sess['target_keyword']}"
                        await log_history_item(email, "On-Page Optimiser", title, full_text)
                    if email:
                        await increment_usage(redis_client, email, "on_page_opt")
                    yield sse_done()
                    return
                elif kind == "error":
                    sess["stage"] = get_rollback_stage("on_page_opt", "rewriting")
                    await save_session(session_id, sess)
                    yield sse_event({"type": "error", "message": friendly_error(value)})
                    yield sse_done()
                    return
        except Exception as exc:
            print(f"[ERROR] on_page_opt/rewrite session={session_id}: {exc}", file=sys.stderr)
            sess["stage"] = get_rollback_stage("on_page_opt", "rewriting")
            await save_session(session_id, sess)
            yield sse_event({"type": "error", "message": "Agent failed. Please try again."})
            yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------------------------------------------------------------------
# Build mode — Research keywords + write new page
# ---------------------------------------------------------------------------

@router.post("/start-build")
async def start_build(req: StartBuildRequest, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(req.session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] in _STUCK_STAGES_OPT:
        # SSE connection likely dropped (common on iPad/Safari) — auto-reset and continue
        sess["stage"] = "idle"
    if sess["stage"] not in ("idle", "done"):
        return JSONResponse({"error": "Session already in progress"}, status_code=400)
    sess["mode"] = "build"
    sess["prompt"] = sanitise_user_input(req.prompt, user_id=sess.get("user_id"))
    sess["page_type"] = sanitise_user_input(req.page_type, user_id=sess.get("user_id"))
    sess["location"] = sanitise_user_input(req.location, user_id=sess.get("user_id"))
    sess["audit_context"] = sanitise_user_input(req.audit_context, user_id=sess.get("user_id"))
    sess["keyword_data"] = {}
    sess["keyword_brief"] = ""
    sess["final_copy"] = ""
    sess["notion_url"] = None
    sess["stage"] = "researching"
    await save_session(req.session_id, sess)
    email = await get_token_email(agency_token) if agency_token else None
    await log_activity("on_page_opt", f"Started build: {req.page_type}", email=email)
    return {"ok": True}


@router.get("/stream/research")
async def stream_research(session_id: str, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "researching":
        return JSONResponse({"error": "Not in researching stage"}, status_code=400)

    api_key = await _get_api_key(sess, agency_token)
    if not api_key:
        async def no_key(): yield sse_event({"type": "error", "code": "gemini_not_configured", "message": "Gemini API key not set. Open Settings to configure it."})
        return StreamingResponse(no_key(), media_type="text/event-stream", headers=SSE_HEADERS)

    async def generate():
        full_text = ""
        try:
            async for kind, value in researcher.run(
                prompt=sess["prompt"],
                page_type=sess["page_type"],
                location=sess["location"],
                audit_context=sess["audit_context"],
                api_key=api_key,
            ):
                if kind == "chunk":
                    full_text += value
                    yield sse_chunk(value)
                elif kind == "keyword_data":
                    sess["keyword_data"] = value
                    sess["keyword_brief"] = full_text
                    await save_session(session_id, sess)
                    yield sse_event({"type": "keyword_data", "data": value})
                elif kind == "done":
                    sess["stage"] = "awaiting_write"
                    await save_session(session_id, sess)
                    yield sse_done()
                    return
                elif kind == "error":
                    sess["stage"] = get_rollback_stage("on_page_opt", "researching")
                    await save_session(session_id, sess)
                    yield sse_event({"type": "error", "message": friendly_error(value)})
                    yield sse_done()
                    return
        except Exception as exc:
            print(f"[ERROR] on_page_opt/research session={session_id}: {exc}", file=sys.stderr)
            sess["stage"] = get_rollback_stage("on_page_opt", "researching")
            await save_session(session_id, sess)
            yield sse_event({"type": "error", "message": "Agent failed. Please try again."})
            yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/write")
async def start_write(req: SessionRequest):
    sess = await get_session(req.session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "awaiting_write":
        return JSONResponse({"error": "Not ready to write"}, status_code=400)
    sess["stage"] = "writing"
    await save_session(req.session_id, sess)
    return {"ok": True}


@router.get("/stream/copy")
async def stream_copy(session_id: str, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "writing":
        return JSONResponse({"error": "Not in writing stage"}, status_code=400)

    api_key = await _get_api_key(sess, agency_token)
    if not api_key:
        async def no_key(): yield sse_event({"type": "error", "code": "gemini_not_configured", "message": "Gemini API key not set. Open Settings to configure it."})
        return StreamingResponse(no_key(), media_type="text/event-stream", headers=SSE_HEADERS)
    email = await get_token_email(agency_token) if agency_token else None

    async def generate():
        full_text = ""
        try:
            async for kind, value in copywriter.run(
                mode="build",
                page_type=sess["page_type"],
                prompt=sess["prompt"],
                keyword_data=sess["keyword_data"],
                keyword_brief=sess["keyword_brief"],
                audit_context=sess["audit_context"],
                api_key=api_key,
            ):
                if kind == "chunk":
                    full_text += value
                    yield sse_chunk(value)
                elif kind == "done":
                    sess["final_copy"] = full_text
                    sess["stage"] = "done"
                    await save_session(session_id, sess)
                    await log_activity("on_page_opt", f"Built page: {sess['page_type']}", email=email)
                    user = await get_user(sess.get("user_id", ""))
                    u = user or {}
                    asyncio.ensure_future(log_task(
                        "On-Page Opt", "On-Page Opt", f"Build: {sess['page_type']} — {sess['prompt'][:60]}",
                        notion_token=u.get("notion_token", ""),
                        db_id=u.get("notion_agency_log_db_id", ""),
                    ))
                    if email and full_text:
                        title = f"Build: {sess['page_type']} — {sess['prompt'][:60]}"
                        await log_history_item(email, "On-Page Optimiser", title, full_text)
                    if email:
                        await increment_usage(redis_client, email, "on_page_opt")
                    yield sse_done()
                    return
                elif kind == "error":
                    sess["stage"] = get_rollback_stage("on_page_opt", "writing")
                    await save_session(session_id, sess)
                    yield sse_event({"type": "error", "message": friendly_error(value)})
                    yield sse_done()
                    return
        except Exception as exc:
            print(f"[ERROR] on_page_opt/copy session={session_id}: {exc}", file=sys.stderr)
            sess["stage"] = get_rollback_stage("on_page_opt", "writing")
            await save_session(session_id, sess)
            yield sse_event({"type": "error", "message": "Agent failed. Please try again."})
            yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------------------------------------------------------------------------
# Save to Notion (both modes)
# ---------------------------------------------------------------------------

@router.post("/save-to-notion")
async def save_to_notion(req: SessionRequest):
    sess = await get_session(req.session_id, "on_page_opt", _SESSION_DEFAULTS)
    if sess["stage"] != "done":
        return JSONResponse({"error": "Not complete yet"}, status_code=400)
    if sess.get("notion_url"):
        return {"notion_url": sess["notion_url"]}

    notion_token, db_id = await _get_notion_creds(sess)

    if not notion_token or not db_id:
        return JSONResponse(
            {"error": "Notion saving isn't configured for your account yet.", "code": "notion_not_configured"},
            status_code=400,
        )

    try:
        notion_url = await save_optimiser_report(
            mode=sess["mode"],
            page_type=sess["page_type"],
            target_keyword=sess.get("target_keyword", ""),
            prompt=sess.get("prompt", ""),
            analysis=sess.get("analysis", ""),
            keyword_data=sess.get("keyword_data", {}),
            keyword_brief=sess.get("keyword_brief", ""),
            final_copy=sess["final_copy"],
            notion_token=notion_token,
            db_id=db_id,
        )
        sess["notion_url"] = notion_url
        await save_session(req.session_id, sess)
        if notion_url:
            user = await get_user(sess.get("user_id", ""))
            u = user or {}
            asyncio.ensure_future(log_task(
                "On-Page Opt", "On-Page Opt", f"Saved to Notion: {sess['page_type']}", link=notion_url,
                notion_token=u.get("notion_token", ""),
                db_id=u.get("notion_agency_log_db_id", ""),
            ))
        return {"notion_url": notion_url}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
