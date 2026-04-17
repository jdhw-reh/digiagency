"""
On-Page Optimiser — Copywriter agent

Operates in two modes:
  - Review mode: rewrites/fixes supplied copy based on the analysis findings
  - Build mode: writes a full new page from scratch using the keyword research brief

Produces clean, well-structured, SEO-optimised copy ready to publish.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, load_prompt


async def run(
    mode: str,
    page_type: str,
    # Review mode
    original_copy: str = "",
    target_keyword: str = "",
    analysis: str = "",
    # Build mode
    prompt: str = "",
    keyword_data: dict = None,
    keyword_brief: str = "",
    audit_context: str = "",
    api_key: str = "",
):
    """
    Stream the copywritten output.
    mode: "review" | "build"
    Yields: ("chunk", str) then ("done", None) or ("error", str)
    """
    if keyword_data is None:
        keyword_data = {}

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    _prompts = load_prompt("on_page_opt/copywriter")

    if mode == "review":
        full_prompt = _prompts["user_prompt_template_review"].format(
            page_type=page_type or "General page",
            target_keyword=target_keyword or "not specified",
            original_copy=original_copy,
            analysis=analysis,
        )
    else:
        import json as _json
        brief_str = keyword_brief or _json.dumps(keyword_data, indent=2)
        audit_context_section = ""
        if audit_context.strip():
            audit_context_section = f"SEO Audit context:\n{audit_context}\n"

        full_prompt = _prompts["user_prompt_template_build"].format(
            page_type=page_type or "service page",
            keyword_brief=brief_str,
            audit_context_section=audit_context_section,
            prompt=prompt,
            word_count=keyword_data.get("recommended_word_count", 800),
            search_intent=keyword_data.get("search_intent", "transactional"),
        )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            full_prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("on_page_opt/copywriter"),
                temperature=0.5,
            ),
            result_queue,
        )

    loop = asyncio.get_event_loop()
    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=120)
            )
        except queue.Empty:
            yield ("error", "Copywriter timed out")
            return

        if kind == "chunk":
            yield ("chunk", value)
        elif kind == "done":
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
