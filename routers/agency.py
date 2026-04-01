"""
Agency router — cross-team endpoints.

GET /api/agency/stream/notifications
    SSE stream. Any browser tab that is open on the home view subscribes here
    and receives a live push whenever any team logs a completed task.
    The frontend uses this to refresh the activity feed without polling.
"""

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from state import subscribe_notifications, unsubscribe_notifications
from utils.sse import SSE_HEADERS

router = APIRouter()

_KEEPALIVE_SECONDS = 25  # send a comment ping to keep the connection alive


@router.get("/stream/notifications")
async def stream_notifications():
    """
    Subscribe to agency-wide completion events.

    Each event has the shape:
        data: {"team": "content", "action": "Saved article: ...", "ts": "..."}
    """
    q = subscribe_notifications()

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_SECONDS)
                    payload = json.dumps(event)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # SSE keep-alive comment
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_notifications(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
