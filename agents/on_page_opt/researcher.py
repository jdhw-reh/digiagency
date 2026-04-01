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

RESEARCHER_SYSTEM_PROMPT = """You are a senior SEO keyword researcher. You use real-time \
search data to identify the best keyword opportunities for a specific page. You understand \
search intent deeply and always match keyword targeting to the right page type.

You have access to Google Search — use it to find real search volumes, competition levels, \
related queries and SERP features. Ground every recommendation in actual data."""

RESEARCHER_PROMPT = """Research keywords and search intent for this page:

Page type: {page_type}
Brief / topic: {prompt}
{location_section}
{audit_context_section}

Use Google Search to investigate:
1. What is the primary keyword with the best traffic-to-competition ratio for this page?
2. What are 5–8 semantically related keywords and LSI terms to include in the copy?
3. What search intent dominates this query? (informational / transactional / local / commercial)
4. What questions does the target audience ask? (People Also Ask / related searches)
5. Who ranks on page 1? What content patterns do they share?

Write a keyword research summary covering your findings (3–4 paragraphs).

Then output the structured keyword brief as JSON enclosed in <keyword_data> and </keyword_data> tags:

<keyword_data>
{{
  "primary_keyword": "main target keyword",
  "secondary_keywords": ["kw2", "kw3", "kw4"],
  "lsi_terms": ["term1", "term2", "term3", "term4", "term5"],
  "search_intent": "transactional",
  "target_audience": "description of who is searching",
  "recommended_word_count": 800,
  "key_questions_to_answer": ["question 1?", "question 2?", "question 3?"],
  "top_competitors": ["competitor1.com", "competitor2.com"],
  "page_structure_tips": ["tip 1", "tip 2", "tip 3"]
}}
</keyword_data>"""


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

    full_prompt = RESEARCHER_PROMPT.format(
        page_type=page_type or "Service page",
        prompt=prompt,
        location_section=location_section,
        audit_context_section=audit_context_section,
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=RESEARCHER_SYSTEM_PROMPT,
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

    full_text = ""

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=90)
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
