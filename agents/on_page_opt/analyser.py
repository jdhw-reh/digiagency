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

ANALYSER_SYSTEM_PROMPT = """You are a senior on-page SEO specialist with deep expertise in \
content optimisation, search intent, and semantic SEO. You analyse page copy with precision, \
identifying exactly what is hurting rankings and what needs to change.

You do not guess — every issue you flag is grounded in SEO best practice and tied to a \
specific part of the copy. You are direct, specific and actionable."""

ANALYSER_PROMPT = """Analyse the following page copy for on-page SEO issues.

Page type: {page_type}
Target keyword: {target_keyword}
{audit_context_section}

--- PAGE COPY ---
{copy}
--- END COPY ---

Produce a structured on-page SEO analysis with these sections:

## Search Intent Assessment
Does this copy match the search intent for "{target_keyword}"? Is it informational, transactional, \
navigational or commercial? Does the content align? (2–3 sentences)

## Keyword & Semantic Issues
- Is the target keyword used naturally and at an appropriate density?
- Are relevant semantic / LSI terms missing?
- List specific missing keywords or phrases that should appear on this page type

## Content Structure Issues
- Heading hierarchy (H1, H2, H3) — is it logical and keyword-rich?
- Is there a clear value proposition above the fold?
- Does the copy guide the user through a logical flow?

## Thin Content & Gaps
- Word count adequacy for this page type
- Missing sections that competitors typically include
- Any content that adds no SEO or user value

## Meta & Technical Copy Issues
- Title tag recommendation (if derivable from copy)
- Meta description suggestion
- Any other on-page copy elements to fix

## Priority Fixes (Top 5)
List the 5 highest-impact changes, ordered by impact. Be specific — quote the copy where relevant.

Keep the analysis tight and actionable. Reference specific sentences or phrases from the copy."""


async def run(copy: str, target_keyword: str, page_type: str, audit_context: str = "", api_key: str = ""):
    """
    Stream the on-page SEO analysis.
    Yields: ("chunk", str) then ("done", None) or ("error", str)
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    audit_context_section = ""
    if audit_context.strip():
        audit_context_section = f"\nSEO Audit context (technical findings for this site):\n{audit_context}\n"

    prompt = ANALYSER_PROMPT.format(
        page_type=page_type or "General page",
        target_keyword=target_keyword or "not specified",
        audit_context_section=audit_context_section,
        copy=copy,
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=ANALYSER_SYSTEM_PROMPT,
                    temperature=0.3,
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
                None, lambda: result_queue.get(timeout=90)
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
