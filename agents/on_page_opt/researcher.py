"""
On-Page Optimiser — Researcher agent

Keyword research for new page builds. Uses Google Search grounding to find
real search data: primary keyword, semantic variants, intent, competitiveness.

Returns a structured keyword brief and a human-readable research summary.
"""

import asyncio
import json
import os
import queue
import re
import threading

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, get_user_prompt


async def run(prompt: str, page_type: str, location: str = "", audit_context: str = "", api_key: str = ""):
    """
    Stream keyword research.
    Yields: ("chunk", str), ("keyword_data", dict), ("done", None) or ("error", str)
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    location_section = f"\nTarget location: {location}" if location.strip() else ""
    audit_context_section = ""
    if audit_context.strip():
        audit_context_section = f"\nSEO Audit context (existing site findings):\n{audit_context}\n"

    full_prompt = get_user_prompt(
        "on_page_opt/researcher",
        page_type=page_type or "Service page",
        prompt=prompt,
        location_section=location_section,
        audit_context_section=audit_context_section,
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            full_prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("on_page_opt/researcher"),
                temperature=0.3,
            ),
            result_queue,
        )

    loop = asyncio.get_event_loop()
    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    full_text = ""

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=120)
            )
        except queue.Empty:
            yield ("error", "Researcher timed out")
            return

        if kind == "chunk":
            full_text += value
            yield ("chunk", value)
        elif kind == "done":
            keyword_data = {}
            match = re.search(r"<keyword_data>(.*?)</keyword_data>", full_text, re.DOTALL)
            if match:
                try:
                    keyword_data = json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass
            yield ("keyword_data", keyword_data)
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
