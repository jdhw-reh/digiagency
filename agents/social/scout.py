"""
Social Scout agent: uses Gemini 2.5 Flash with Google Search grounding
to analyse a social media profile, identify its niche, find competitor
accounts, and surface content opportunities.
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


def _build_description_block(description: str) -> str:
    if description and description.strip():
        return f"Additional context from account owner: {description.strip()}"
    return ""


async def run(profile_url: str, description: str, platform: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks, then a final dict
    {"type": "opportunities", "data": [...]} with parsed opportunities.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    prompt = get_user_prompt(
        "social/scout",
        profile_url=profile_url,
        platform=platform,
        description_block=_build_description_block(description),
    )

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("social/scout"),
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
                yield {"type": "error", "message": "Scout agent timed out after 120 seconds"}
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

    full_text = "".join(full_text_parts)
    match = re.search(r"<opportunities>(.*?)</opportunities>", full_text, re.DOTALL)
    if match:
        try:
            opportunities = json.loads(match.group(1).strip())
            yield {"type": "opportunities", "data": opportunities}
        except json.JSONDecodeError as e:
            yield {"type": "opportunities", "data": [], "error": f"Failed to parse opportunities JSON: {e}"}
    else:
        yield {"type": "opportunities", "data": [], "error": "No <opportunities> block found in response"}
