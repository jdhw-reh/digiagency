"""
Researcher agent: uses Gemini 2.0 Flash with Google Search grounding
to discover high-value blog topic ideas for a professional services copywriting business.

The Gemini SDK is synchronous, so we bridge it to FastAPI's async event loop
using threading.Thread + queue.Queue. Do NOT use asyncio.to_thread for streaming
— it only returns after the full response is complete, killing the live-stream effect.
"""

import asyncio
import json
import os
import queue
import re
import threading

from google import genai
from google.genai import types

RESEARCHER_SYSTEM_PROMPT = """You are a senior SEO strategist. Your job is to identify \
high-value blog topics for any business or niche based on the context provided.

Your job is to identify high-value blog topics that:
1. Have genuine search demand from the target audience described in the business context
2. Match informational or commercial search intent — not navigational or transactional
3. Can be owned by a thought leadership article of 800–1,200 words
4. Are not already dominated by large media publications

You have access to real-time Google Search. Use it to validate demand and competition before \
recommending topics. Surface topics where the business described has a clear authority edge \
over generic competitors.

Return your research as instructed. Always ground your competition assessment in what you \
actually find in the SERP, not assumptions."""

RESEARCHER_PROMPT = """Business context: {context}

Research and discover 5–10 high-value blog topic ideas for this business. \
Use Google Search to validate real demand and competition levels.

For each topic, provide a JSON object with these exact fields:
- title: the article headline (compelling, specific)
- primary_keyword: exact phrase to target
- secondary_keywords: list of 3–5 related phrases
- search_intent: one of: informational | commercial | transactional
- competition: one of: low | medium | high
- estimated_monthly_searches: rough estimate string e.g. "1,000–5,000"
- why_target: 2–3 sentence rationale grounded in your actual search findings

Write a brief 2–3 paragraph research commentary explaining your overall findings and \
the content opportunity landscape.

Then output ALL topics as a single JSON array enclosed in <topics> and </topics> tags like this:

<topics>
[
  {{
    "title": "...",
    "primary_keyword": "...",
    "secondary_keywords": ["...", "..."],
    "search_intent": "informational",
    "competition": "medium",
    "estimated_monthly_searches": "1,000–5,000",
    "why_target": "..."
  }}
]
</topics>"""


async def run(business_context: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks as they arrive from Gemini,
    then yields a final dict {"type": "topics", "data": [...]} with the parsed topics.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=RESEARCHER_PROMPT.format(context=business_context),
                config=types.GenerateContentConfig(
                    system_instruction=RESEARCHER_SYSTEM_PROMPT,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.4,
                ),
            )
            for chunk in response:
                text = chunk.text
                if text:
                    text_queue.put(("chunk", text))
                    full_text_parts.append(text)
        except Exception as e:
            text_queue.put(("error", str(e)))
        finally:
            text_queue.put(("done", None))

    thread = threading.Thread(target=_stream_to_queue, daemon=True)
    thread.start()

    while True:
        try:
            msg_type, value = text_queue.get(timeout=0.05)
        except queue.Empty:
            await asyncio.sleep(0.01)
            continue

        if msg_type == "chunk":
            yield value
        elif msg_type == "error":
            yield f"\n\n[Researcher error: {value}]"
            break
        elif msg_type == "done":
            break

    thread.join(timeout=5)

    # Parse the <topics>...</topics> block from the accumulated output.
    # We use XML-tag wrapping (not raw JSON) because Gemini's grounding citations
    # can insert characters mid-stream that corrupt inline JSON parsing.
    full_text = "".join(full_text_parts)
    match = re.search(r"<topics>(.*?)</topics>", full_text, re.DOTALL)
    if match:
        try:
            topics = json.loads(match.group(1).strip())
            yield {"type": "topics", "data": topics}
        except json.JSONDecodeError as e:
            yield {"type": "topics", "data": [], "error": f"Failed to parse topics JSON: {e}"}
    else:
        yield {"type": "topics", "data": [], "error": "No <topics> block found in response"}
