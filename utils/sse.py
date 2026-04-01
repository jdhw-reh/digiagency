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
