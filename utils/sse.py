"""SSE helpers shared across all routers."""

import json

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # prevent nginx/proxy buffering
    "Access-Control-Allow-Origin": "*",
}


def sse_chunk(text: str) -> str:
    return f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def sse_done() -> str:
    return f"data: {json.dumps({'type': 'done'})}\n\n"


def friendly_error(exc_str: str) -> str:
    """Convert raw exception strings into user-friendly messages."""
    s = exc_str.lower()
    # Quota/billing exhaustion — NOT transient, needs action from the user
    if any(k in s for k in ("quota", "resource_exhausted", "resource exhausted")):
        return f"Gemini API quota exceeded — check your API key usage in Google AI Studio. (detail: {exc_str[:200]})"
    # Auth/key problems
    if any(k in s for k in ("api_key_invalid", "api key", "permission_denied", "permission denied", "unauthenticated")):
        return f"Gemini API key error — check that your API key is valid and has Gemini enabled. (detail: {exc_str[:200]})"
    # Genuine transient overload
    if any(k in s for k in ("overloaded", "unavailable")):
        return "Gemini is temporarily busy — please wait a moment and try again."
    if "503" in s:
        return "Gemini is temporarily busy — please wait a moment and try again."
    if "429" in s:
        return "Too many requests — please wait a moment before trying again."
    if "timeout" in s or "timed out" in s:
        return "The request timed out — please try again."
    return f"Something went wrong — please try again. ({exc_str[:200]})"
