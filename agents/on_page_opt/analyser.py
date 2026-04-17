"""
On-Page Optimiser — Analyser agent

Reviews supplied page copy for on-page SEO issues. No search grounding —
pure expert analysis of the text provided.

Awareness of SEO Audit findings can be passed in via audit_context to
cross-reference technical findings with copy-level issues.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, get_user_prompt


async def run(copy: str, target_keyword: str, page_type: str, audit_context: str = "", api_key: str = ""):
    """
    Stream the on-page SEO analysis.
    Yields: ("chunk", str) then ("done", None) or ("error", str)
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    audit_context_section = ""
    if audit_context.strip():
        audit_context_section = f"\nSEO Audit context (technical findings for this site):\n{audit_context}\n"

    prompt = get_user_prompt(
        "on_page_opt/analyser",
        page_type=page_type or "General page",
        target_keyword=target_keyword or "not specified",
        audit_context_section=audit_context_section,
        copy=copy,
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("on_page_opt/analyser"),
                temperature=0.3,
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
            yield ("error", "Analyser timed out")
            return

        if kind == "chunk":
            yield ("chunk", value)
        elif kind == "done":
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
