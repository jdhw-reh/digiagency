"""
Social Strategist agent: uses Gemini 2.5 Flash to build a 2-week content calendar
from the Scout's competitive research and the selected opportunity.

No web search — pure strategic reasoning.
"""

import asyncio
import os
import queue
import threading
import time

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, get_user_prompt


def _build_description_block(description: str) -> str:
    if description and description.strip():
        return f"Additional context: {description.strip()}"
    return ""


async def run(opportunity: dict, profile_url: str, description: str, platform: str, api_key: str = ""):
    """Async generator yielding str text chunks."""
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    opp_text = (
        f"Angle: {opportunity.get('angle', '')}\n"
        f"Hook type: {opportunity.get('hook_type', '')}\n"
        f"Why now: {opportunity.get('why_now', '')}\n"
        f"Competitor gap: {opportunity.get('competitor_gap', '')}"
    )

    prompt = get_user_prompt(
        "social/strategist",
        profile_url=profile_url,
        platform=platform,
        description_block=_build_description_block(description),
        opportunity=opp_text,
    )

    text_queue: queue.Queue = queue.Queue()

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("social/strategist"),
                temperature=0.5,
            ),
            text_queue,
        )

    threading.Thread(target=_stream_to_queue, daemon=True).start()

    deadline = time.monotonic() + 120
    while True:
        try:
            msg_type, value = text_queue.get(timeout=0.05)
            deadline = time.monotonic() + 120  # reset on each message
        except queue.Empty:
            if time.monotonic() > deadline:
                yield {"type": "error", "message": "Strategy agent timed out after 120 seconds"}
                return
            await asyncio.sleep(0.01)
            continue

        if msg_type == "chunk":
            yield value
        elif msg_type == "error":
            yield {"type": "error", "message": value}
            break
        elif msg_type == "done":
            break
