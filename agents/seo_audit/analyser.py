"""
SEO Analyser agent: analyses raw audit data and produces a structured SEO analysis.
No search grounding — pure strategic reasoning from the audit findings.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types

ANALYSER_SYSTEM_PROMPT = """You are a senior SEO strategist who turns raw audit data \
into clear strategic analysis. You are direct, specific, and always tie observations \
to business impact. You do not repeat the raw data — you interpret it.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

ANALYSER_PROMPT = """Here is the raw SEO audit for {url}:

Business context: {context}
{competitor_section}
Audit findings:
{audit_data}

Produce a structured SEO analysis with these sections:

## Strengths
What is this site already doing well from an SEO perspective? (2–3 bullet points)

## Critical Gaps
What are the most damaging gaps — keywords, content, authority — that are costing them \
rankings right now? (3–4 bullet points, be specific)

## Competitive Position
How do they compare to the competitors identified? Where are they losing ground and where \
do they have an edge?

## Highest-Leverage Opportunities
The 3 opportunities with the best ratio of effort to SEO impact. Be concrete — name the \
keyword clusters, content types, or structural changes.

Keep the analysis tight — 400–600 words total."""


async def run(url: str, context: str, audit_data: dict, api_key: str = "", competitor_urls: list | None = None):
    """Stream the SEO analysis. Yields text chunks then a done event."""

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    import json as _json
    audit_str = _json.dumps(audit_data, indent=2) if audit_data else "No structured data available."
    competitors = [u for u in (competitor_urls or []) if u]
    competitor_section = (
        f"\nCompetitor domains to benchmark against: {', '.join(competitors)}\n"
        if competitors else ""
    )
    prompt = ANALYSER_PROMPT.format(
        url=url, context=context, audit_data=audit_str, competitor_section=competitor_section
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=ANALYSER_SYSTEM_PROMPT,
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
