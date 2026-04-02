"""SEO Audit Team router — all routes live under /api/seo-audit/"""

import asyncio
import os
import uuid

from fastapi import APIRouter, Cookie
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from state import get_session, save_session, get_user, log_activity, get_token_email
from utils.sse import SSE_HEADERS, sse_chunk, sse_done, sse_event
from agents.seo_audit import auditor, analyser, recommender, implementer
from services.agency_log import log_task
from services.notion_seo_audit import save_audit_report

router = APIRouter()

_SESSION_DEFAULTS = {
    "stage": "idle",
    "url": "",
    "audit_context": "",
    "audit_data": {},
    "audit_text": "",
    "analysis": "",
    "recommendations": "",
    "implementation": "",
    "notion_url": None,
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
    return u.get("notion_token", ""), u.get("notion_on_page_db_id", "") or u.get("notion_seo_audit_db_id", "")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionPayload(BaseModel):
    user_id: str = ""


class StartAuditRequest(BaseModel):
    session_id: str
    url: str
    context: str


class SessionRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(payload: CreateSessionPayload):
    sid = str(uuid.uuid4())
    defaults = {**_SESSION_DEFAULTS, "user_id": payload.user_id}
    await get_session(sid, "seo_audit", defaults)
    return {"session_id": sid}


@router.get("/state")
async def get_state(session_id: str):
    sess = await get_session(session_id, "seo_audit", _SESSION_DEFAULTS)
    return JSONResponse(sess)


@router.post("/start")
async def start_audit(req: StartAuditRequest, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(req.session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] not in ("idle", "done"):
        return JSONResponse({"error": "Audit already in progress"}, status_code=400)
    sess["url"] = req.url
    sess["audit_context"] = req.context
    sess["stage"] = "auditing"
    sess["audit_data"] = {}
    sess["audit_text"] = ""
    sess["analysis"] = ""
    sess["recommendations"] = ""
    sess["implementation"] = ""
    sess["notion_url"] = None
    await save_session(req.session_id, sess)
    email = await get_token_email(agency_token) if agency_token else None
    await log_activity("seo_audit", f"Started audit: {req.url}", email=email)
    return {"ok": True}


@router.get("/stream/audit")
async def stream_audit(session_id: str):
    sess = await get_session(session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "auditing":
        return JSONResponse({"error": "Not in auditing stage"}, status_code=400)

    api_key = await _get_api_key(sess)

    async def generate():
        full_text = ""
        async for kind, value in auditor.run(sess["url"], sess["audit_context"], api_key=api_key):
            if kind == "technical_signals":
                yield sse_event({"type": "technical_signals", "data": value})
            elif kind == "chunk":
                full_text += value
                yield sse_chunk(value)
            elif kind == "audit_data":
                sess["audit_data"] = value
                sess["audit_text"] = full_text
                sess["stage"] = "awaiting_analyse"
                await save_session(session_id, sess)
                yield sse_event({"type": "audit_data", "data": value})
                yield sse_done()
            elif kind == "error":
                sess["stage"] = "idle"
                await save_session(session_id, sess)
                yield sse_event({"type": "error", "message": value})
                yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/analyse")
async def start_analyse(req: SessionRequest):
    sess = await get_session(req.session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "awaiting_analyse":
        return JSONResponse({"error": "Not ready to analyse"}, status_code=400)
    sess["stage"] = "analysing"
    await save_session(req.session_id, sess)
    return {"ok": True}


@router.get("/stream/analysis")
async def stream_analysis(session_id: str):
    sess = await get_session(session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "analysing":
        return JSONResponse({"error": "Not in analysing stage"}, status_code=400)

    api_key = await _get_api_key(sess)

    async def generate():
        full_text = ""
        async for kind, value in analyser.run(
            sess["url"], sess["audit_context"], sess["audit_data"], api_key=api_key
        ):
            if kind == "chunk":
                full_text += value
                yield sse_chunk(value)
            elif kind == "done":
                sess["analysis"] = full_text
                sess["stage"] = "awaiting_recommend"
                await save_session(session_id, sess)
                yield sse_done()
            elif kind == "error":
                sess["stage"] = "awaiting_analyse"
                await save_session(session_id, sess)
                yield sse_event({"type": "error", "message": value})
                yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/recommend")
async def start_recommend(req: SessionRequest):
    sess = await get_session(req.session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "awaiting_recommend":
        return JSONResponse({"error": "Not ready to recommend"}, status_code=400)
    sess["stage"] = "recommending"
    await save_session(req.session_id, sess)
    return {"ok": True}


@router.get("/stream/recommendations")
async def stream_recommendations(session_id: str):
    sess = await get_session(session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "recommending":
        return JSONResponse({"error": "Not in recommending stage"}, status_code=400)

    api_key = await _get_api_key(sess)

    async def generate():
        full_text = ""
        async for kind, value in recommender.run(
            sess["url"], sess["audit_context"], sess["audit_data"], sess["analysis"], api_key=api_key
        ):
            if kind == "chunk":
                full_text += value
                yield sse_chunk(value)
            elif kind == "done":
                sess["recommendations"] = full_text
                sess["stage"] = "awaiting_implement"
                await save_session(session_id, sess)
                yield sse_done()
            elif kind == "error":
                sess["stage"] = "awaiting_recommend"
                await save_session(session_id, sess)
                yield sse_event({"type": "error", "message": value})
                yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/implement")
async def start_implement(req: SessionRequest):
    sess = await get_session(req.session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "awaiting_implement":
        return JSONResponse({"error": "Not ready to implement"}, status_code=400)
    sess["stage"] = "implementing"
    await save_session(req.session_id, sess)
    return {"ok": True}


@router.get("/stream/implementation")
async def stream_implementation(session_id: str, agency_token: str | None = Cookie(default=None)):
    sess = await get_session(session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "implementing":
        return JSONResponse({"error": "Not in implementing stage"}, status_code=400)

    api_key = await _get_api_key(sess)
    email = await get_token_email(agency_token) if agency_token else None

    async def generate():
        full_text = ""
        cms = sess["audit_data"].get("cms", "WordPress")
        async for kind, value in implementer.run(
            sess["url"],
            sess["audit_context"],
            cms,
            sess["audit_data"],
            sess["analysis"],
            sess["recommendations"],
            api_key=api_key,
        ):
            if kind == "chunk":
                full_text += value
                yield sse_chunk(value)
            elif kind == "done":
                sess["implementation"] = full_text
                sess["stage"] = "done"
                await save_session(session_id, sess)
                await log_activity("seo_audit", f"Completed audit: {sess['url']}", email=email)
                user = await get_user(sess.get("user_id", ""))
                u = user or {}
                asyncio.ensure_future(log_task(
                    "SEO Audit", "SEO Audit", f"Audit: {sess['url']}",
                    notion_token=u.get("notion_token", ""),
                    db_id=u.get("notion_agency_log_db_id", ""),
                ))
                yield sse_done()
            elif kind == "error":
                sess["stage"] = "awaiting_implement"
                await save_session(session_id, sess)
                yield sse_event({"type": "error", "message": value})
                yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/save-to-notion")
async def save_to_notion(req: SessionRequest):
    sess = await get_session(req.session_id, "seo_audit", _SESSION_DEFAULTS)
    if sess["stage"] != "done":
        return JSONResponse({"error": "Audit not complete"}, status_code=400)
    if sess.get("notion_url"):
        return {"notion_url": sess["notion_url"]}

    user = await get_user(sess.get("user_id", ""))
    u = user or {}
    notion_token = u.get("notion_token", "")
    db_id = u.get("notion_seo_audit_db_id", "")

    try:
        notion_url = await save_audit_report(
            url=sess["url"],
            audit_data=sess["audit_data"],
            audit_text=sess["audit_text"],
            analysis=sess["analysis"],
            recommendations=sess["recommendations"],
            implementation=sess["implementation"],
            notion_token=notion_token,
            db_id=db_id,
        )
        sess["notion_url"] = notion_url
        await save_session(req.session_id, sess)
        if notion_url:
            asyncio.ensure_future(log_task(
                "SEO Audit", "SEO Audit", f"Saved to Notion: {sess['url']}", link=notion_url,
                notion_token=u.get("notion_token", ""),
                db_id=u.get("notion_agency_log_db_id", ""),
            ))
        return {"notion_url": notion_url}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/reset")
async def reset_audit(req: SessionRequest):
    sess = await get_session(req.session_id, "seo_audit", _SESSION_DEFAULTS)
    sess.update({
        "url": "",
        "audit_context": "",
        "stage": "idle",
        "audit_data": {},
        "audit_text": "",
        "analysis": "",
        "recommendations": "",
        "implementation": "",
        "notion_url": None,
    })
    await save_session(req.session_id, sess)
    return {"ok": True}
