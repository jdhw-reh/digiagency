"""
SEO Recommender agent: produces a prioritised, actionable recommendation list.
No search grounding — synthesises audit data + analysis into concrete next steps.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types

RECOMMENDER_SYSTEM_PROMPT = """You are an SEO consultant who specialises in turning analysis \
into clear, prioritised action plans. You write for business owners and marketing managers, \
not developers. Your recommendations are specific, actionable, and ranked by impact.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

RECOMMENDER_PROMPT = """Based on this SEO audit and analysis for {url}:

Business context: {context}
{competitor_section}
Audit data summary:
{audit_data}

Strategic analysis:
{analysis}

Write a prioritised SEO action plan with exactly 8 recommendations.

Format each recommendation exactly like this:

**1. [Recommendation title]**
Effort: Low/Medium/High | Impact: Low/Medium/High
[2–3 sentences describing exactly what to do and why it will move the needle.]

Order them from highest-impact to lowest. Be brutally specific — name the exact keywords, \
pages, or content pieces where relevant. No filler."""


async def run(url: str, context: str, audit_data: dict, analysis: str, api_key: str = "", competitor_urls: list | None = None):
    """Stream the recommendations. Yields text chunks then a done event."""

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    import json as _json
    audit_str = _json.dumps(audit_data, indent=2) if audit_data else ""
    competitors = [u for u in (competitor_urls or []) if u]
    competitor_section = (
        f"\nCompetitor domains to benchmark against: {', '.join(competitors)}\n"
        if competitors else ""
    )
    prompt = RECOMMENDER_PROMPT.format(
        url=url,
        context=context,
        audit_data=audit_str,
        analysis=analysis,
        competitor_section=competitor_section,
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=RECOMMENDER_SYSTEM_PROMPT,
                    temperature=0.4,
                ),
            ):
                if chunk.text:
                    result_queue.put(("chunk", chunk.text))
            result_queue.put(("done", None))
        except Exception as exc:
            result_queue.put(("error", str(exc)))

    loop = asyncio.get_event_loop()
    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=60)
            )
        except queue.Empty:
            yield ("error", "Recommender timed out")
            return

        if kind == "chunk":
            yield ("chunk", value)
        elif kind == "done":
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
