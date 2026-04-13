"""
Planner agent: uses Gemini 2.5 Flash to turn a selected topic into a detailed
content brief for the Writer agent.

No web search needed here — pure language generation. Sync→async bridge used
for consistency with the streaming pattern established in researcher.py.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types

PLANNER_SYSTEM_PROMPT = """You are a content strategist and editorial director with 15 years of \
experience in B2B and professional services copywriting.

You create content briefs that are detailed enough for a senior writer to produce a \
publication-ready first draft with no clarifying questions. Your briefs are:
- Structured with clear H2/H3 hierarchy
- Grounded in the specific search intent (not generic "target this keyword" advice)
- Opinionated about tone — professional services audiences respond to confident, \
evidence-backed writing, not hedging
- Explicit about what NOT to include (scope creep kills articles)
- Precise about CTA placement and purpose

Write briefs in Markdown. Be direct. Do not pad. A great brief is 400–600 words, not 1,500.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

PLANNER_PROMPT = """Business context: {context}

Topic to plan:
Title: {title}
Primary keyword: {primary_keyword}
Secondary keywords: {secondary_keywords}
Search intent: {search_intent}
Competition: {competition}
Why target this: {why_target}

Create a detailed content brief for this article. Include:
1. Target audience description (who they are, what they already know, what they need)
2. Tone and voice notes (specific, not generic)
3. H2/H3 article structure with key points for each section
4. Keyword placement guidance (where each keyword fits naturally)
5. CTA placement: where, what type, exact suggested copy
6. Word count target (800–1,200 words)
7. Do Not Include section (common mistakes or tangents that would weaken this article)

Format as clean Markdown."""


async def run(topic: dict, business_context: str, api_key: str = ""):
    """Async generator yielding str text chunks."""
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = PLANNER_PROMPT.format(
        context=business_context,
        title=topic.get("title", ""),
        primary_keyword=topic.get("primary_keyword", ""),
        secondary_keywords=", ".join(topic.get("secondary_keywords", [])),
        search_intent=topic.get("search_intent", ""),
        competition=topic.get("competition", ""),
        why_target=topic.get("why_target", ""),
    )

    text_queue: queue.Queue = queue.Queue()

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=PLANNER_SYSTEM_PROMPT,
                    temperature=0.3,
                ),
            )
            for chunk in response:
                if chunk.text:
                    text_queue.put(("chunk", chunk.text))
        except Exception as e:
            text_queue.put(("error", str(e)))
        finally:
            text_queue.put(("done", None))

    threading.Thread(target=_stream_to_queue, daemon=True).start()

    while True:
        try:
            msg_type, value = text_queue.get(timeout=0.05)
        except queue.Empty:
            await asyncio.sleep(0.01)
            continue

        if msg_type == "chunk":
            yield value
        elif msg_type == "error":
            yield {"type": "error", "message": value}
            break
        elif msg_type == "done":
            break
