"""
Researcher agent: uses Gemini 2.5 Flash with Google Search grounding
to discover high-value blog topic ideas for a professional services copywriting business.

The Gemini SDK is synchronous, so we bridge it to FastAPI's async event loop
using threading.Thread + queue.Queue. Do NOT use asyncio.to_thread for streaming
— it only returns after the full response is complete, killing the live-stream effect.
"""

import asyncio
import json
import os
import queue
import re
import threading
import time

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, get_user_prompt


async def run(business_context: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks as they arrive from Gemini,
    then yields a final dict {"type": "topics", "data": [...]} with the parsed topics.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            get_user_prompt("content/researcher", context=business_context),
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("content/researcher"),
                temperature=0.4,
            ),
            text_queue,
            full_text_parts,
        )

    thread = threading.Thread(target=_stream_to_queue, daemon=True)
    thread.start()

    deadline = time.monotonic() + 120
    while True:
        try:
            msg_type, value = text_queue.get(timeout=0.05)
            deadline = time.monotonic() + 120  # reset on each message
        except queue.Empty:
            if time.monotonic() > deadline:
                yield {"type": "error", "message": "Research agent timed out after 120 seconds"}
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

    thread.join(timeout=5)

    # Parse the <topics>...</topics> block from the accumulated output.
    # We use XML-tag wrapping (not raw JSON) because Gemini's grounding citations
    # can insert characters mid-stream that corrupt inline JSON parsing.
    full_text = "".join(full_text_parts)
    match = re.search(r"<topics>(.*?)</topics>", full_text, re.DOTALL)
    if match:
        try:
            topics = json.loads(match.group(1).strip())
            yield {"type": "topics", "data": topics}
        except json.JSONDecodeError as e:
            yield {"type": "topics", "data": [], "error": f"Failed to parse topics JSON: {e}"}
    else:
        yield {"type": "topics", "data": [], "error": "No <topics> block found in response"}
