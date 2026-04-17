"""
Planner agent: uses Gemini 2.5 Flash to turn a selected topic into a detailed
content brief for the Writer agent.

No web search needed here — pure language generation. Sync→async bridge used
for consistency with the streaming pattern established in researcher.py.
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


async def run(topic: dict, business_context: str, api_key: str = ""):
    """Async generator yielding str text chunks."""
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = get_user_prompt(
        "content/planner",
        context=business_context,
        title=topic.get("title", ""),
        primary_keyword=topic.get("primary_keyword", ""),
        secondary_keywords=", ".join(topic.get("secondary_keywords", [])),
        search_intent=topic.get("search_intent", ""),
        competition=topic.get("competition", ""),
        why_target=topic.get("why_target", ""),
    )

    text_queue: queue.Queue = queue.Queue()

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("content/planner"),
                temperature=0.3,
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
                yield {"type": "error", "message": "Planning agent timed out after 120 seconds"}
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
