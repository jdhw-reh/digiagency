"""Personal Assistant router — all routes live under /api/assistant/"""

import os
import tempfile
import uuid

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from fastapi import Cookie
from state import get_session, save_session, get_user, get_activity_log, get_token_email, log_history_item
from utils.sse import SSE_HEADERS, sse_chunk, sse_done
from agents.assistant import assistant

router = APIRouter()

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}

_SESSION_DEFAULTS = {
    "stage": "idle",
    "conversation_history": [],
    "pending_message": "",
    "pending_files": [],
    "user_id": "",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionPayload(BaseModel):
    user_id: str = ""


class MessagePayload(BaseModel):
    session_id: str
    message: str
    file_refs: list[dict] = []


class SessionPayload(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(payload: CreateSessionPayload):
    sid = str(uuid.uuid4())
    defaults = {**_SESSION_DEFAULTS, "user_id": payload.user_id}
    await get_session(sid, "assistant", defaults)
    return {"session_id": sid}


@router.get("/state")
async def get_state(session_id: str):
    return await get_session(session_id, "assistant", _SESSION_DEFAULTS)


@router.post("/clear")
async def clear_conversation(payload: SessionPayload):
    """Clear conversation history, keep session ID."""
    session = await get_session(payload.session_id, "assistant", _SESSION_DEFAULTS)
    session["conversation_history"] = []
    session["pending_message"] = ""
    session["pending_files"] = []
    session["stage"] = "idle"
    await save_session(payload.session_id, session)
    return {"ok": True}


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_file(session_id: str = "", file: UploadFile = File(...)):
    """
    Upload a file to the Gemini File API and return its URI.
    Supports images, PDFs, plain text, and Word documents.
    """
    from google import genai
    from google.genai import types as gtypes

    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        return JSONResponse(
            {"error": f"Unsupported file type: {mime_type}"},
            status_code=415,
        )

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20 MB limit
        return JSONResponse({"error": "File too large (max 20 MB)"}, status_code=413)

    # Resolve API key from user session or env fallback
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if session_id:
        session = await get_session(session_id, "assistant", _SESSION_DEFAULTS)
        user = await get_user(session.get("user_id", ""))
        api_key = (user or {}).get("gemini_api_key") or api_key

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
    }
    suffix = ext_map.get(mime_type, "")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        client = genai.Client(api_key=api_key)
        uploaded = client.files.upload(
            file=tmp_path,
            config=gtypes.UploadFileConfig(
                display_name=file.filename or "attachment",
                mime_type=mime_type,
            ),
        )
        return {
            "uri": uploaded.uri,
            "mime_type": mime_type,
            "display_name": file.filename or "attachment",
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@router.post("/message")
async def post_message(payload: MessagePayload):
    """
    Store the user's message (and any file refs) in the session.
    The frontend then opens a GET /stream/response EventSource to receive the reply.
    """
    if not payload.message.strip():
        return JSONResponse({"error": "Message cannot be empty"}, status_code=400)

    session = await get_session(payload.session_id, "assistant", _SESSION_DEFAULTS)
    if session["stage"] == "responding":
        return JSONResponse({"error": "Assistant is currently responding"}, status_code=409)

    session["pending_message"] = payload.message.strip()
    session["pending_files"] = payload.file_refs[:3]  # enforce max 3
    session["stage"] = "responding"
    await save_session(payload.session_id, session)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Streaming response
# ---------------------------------------------------------------------------

@router.get("/stream/response")
async def stream_response(session_id: str, agency_token: str | None = Cookie(default=None)):
    session = await get_session(session_id, "assistant", _SESSION_DEFAULTS)

    if session["stage"] != "responding" or not session.get("pending_message"):
        return JSONResponse({"error": "No pending message"}, status_code=400)

    email = await get_token_email(agency_token) if agency_token else None
    user_message = session["pending_message"]
    file_refs = session.pop("pending_files", [])
    session["pending_message"] = ""
    session["conversation_history"].append({
        "role": "user",
        "content": user_message,
    })
    await save_session(session_id, session)

    # Resolve API key
    user = await get_user(session.get("user_id", ""))
    api_key = (user or {}).get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")

    # Build a compact activity snapshot for the assistant
    recent = await get_activity_log(limit=15)
    if recent:
        lines = "\n".join(
            f"- [{e['team']}] {e['action']} ({e['ts'][:10]})" for e in recent
        )
        activity_context = f"Recent agency activity (newest first):\n{lines}"
    else:
        activity_context = None

    response_parts: list[str] = []

    async def event_generator():
        async for chunk in assistant.run(
            session["conversation_history"],
            activity_context,
            file_refs if file_refs else None,
            api_key=api_key,
        ):
            response_parts.append(chunk)
            yield sse_chunk(chunk)

        full_response = "".join(response_parts)
        if full_response:
            session["conversation_history"].append({
                "role": "model",
                "content": full_response,
            })
            if email:
                title = user_message[:80] + ("…" if len(user_message) > 80 else "")
                await log_history_item(email, "Assistant", title, full_response)

        session["stage"] = "idle"
        await save_session(session_id, session)
        yield sse_done()

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)
