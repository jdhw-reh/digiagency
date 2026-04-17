"""
SEO Implementer agent: turns prioritised recommendations into a concrete,
step-by-step implementation guide tailored to the detected CMS (WordPress
by default), with ready-to-use assets and assistant task-tracking notes.
"""

import asyncio
import json as _json
import os
import queue
import threading

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, get_user_prompt


async def run(url: str, context: str, cms: str, audit_data: dict, analysis: str, recommendations: str, api_key: str = ""):
    """Stream the implementation guide. Yields text chunks then a done event."""

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    # Build a readable technical summary from audit_data
    tech = audit_data.get("technical_signals", {})
    issues = audit_data.get("technical_issues", [])

    tech_lines = []
    if issues:
        for i in issues:
            tech_lines.append(f"- [{i.get('severity', '').upper()}] {i.get('issue', '')}")
    else:
        # Fall back to raw signals
        if tech:
            tech_lines.append(f"- Title: {tech.get('title', 'N/A')} ({tech.get('title_length', 0)} chars)")
            tech_lines.append(f"- Meta description: {'Present' if tech.get('meta_description') else 'MISSING'}")
            tech_lines.append(f"- H1 count: {tech.get('h1_count', 0)}")
            tech_lines.append(f"- Schema markup: {', '.join(tech.get('schema_types', [])) or 'None detected'}")
            tech_lines.append(f"- Images missing alt text: {tech.get('images_missing_alt', 0)}")
            tech_lines.append(f"- Open Graph tags: {'Present' if tech.get('og_title') else 'Missing'}")
    technical_summary = "\n".join(tech_lines) if tech_lines else _json.dumps(audit_data, indent=2)[:1500]

    prompt = get_user_prompt(
        "seo_audit/implementer",
        url=url,
        context=context,
        cms=cms or "WordPress",
        technical_summary=technical_summary,
        analysis=analysis,
        recommendations=recommendations,
    )

    result_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()

    def _run_sync():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("seo_audit/implementer"),
                temperature=0.3,
            ),
            result_queue,
        )

    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=120)
            )
        except queue.Empty:
            yield ("error", "Implementer timed out")
            return

        if kind == "chunk":
            yield ("chunk", value)
        elif kind == "done":
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
