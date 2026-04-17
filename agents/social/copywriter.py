"""
Social Copywriter agent: uses Gemini 2.5 Flash to write platform-native social posts
from the Strategist's content calendar.

Each post is wrapped in <post platform="..." id="N">...</post> tags so the frontend
can parse and render them as individual copyable cards.
"""

import asyncio
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
        return f"Additional context: {description.strip()}"
    return ""


async def run(calendar: str, profile_url: str, description: str, platform: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks as posts stream,
    then a final dict {"type": "posts", "data": [...]} with the parsed posts.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = get_user_prompt(
        "social/copywriter",
        profile_url=profile_url,
        platform=platform,
        description_block=_build_description_block(description),
        calendar=calendar,
    )

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("social/copywriter"),
                temperature=0.8,
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
                yield {"type": "error", "message": "Copywriting agent timed out after 120 seconds"}
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
    matches = re.findall(
        r'<post\s+platform="([^"]+)"\s+id="(\d+)">(.*?)</post>',
        full_text,
        re.DOTALL,
    )

    if matches:
        posts = [
            {"platform": m[0], "id": int(m[1]), "content": m[2].strip()}
            for m in matches
        ]
        yield {"type": "posts", "data": posts}
    else:
        yield {"type": "posts", "data": [], "error": "No <post> blocks found in response"}
