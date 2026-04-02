"""
Writer agent: uses Gemini 2.5 Flash to write a full 800–1,200 word thought
leadership article from the Planner's content brief.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types

WRITER_SYSTEM_PROMPT = """You are a professional services copywriter with a reputation for writing \
thought leadership that sounds like a smart practitioner, not a content mill.

Your articles:
- Open with a specific, counterintuitive observation or a concrete problem — never a definition, \
never a rhetorical question, never a statistic as the first sentence
- Use short paragraphs (2–4 sentences maximum)
- Avoid these phrases without exception: "In today's fast-paced world", "it's no secret that", \
"leverage", "synergy", "game-changer", "dive into", "delve into", "at the end of the day", \
"it goes without saying", "needless to say", "in conclusion", "in summary"
- Never use bullet-heavy sections — maximum one list per article, maximum 5 items
- Sound like they were written by someone who has done the work, not researched it
- Earn the reader's trust through precision, not through credentials
- End with a single, specific action the reader can take — not a generic call to action

SEO requirements (apply naturally, never mechanically):
- Use the primary keyword within the first 100 words — work it into a sentence that would \
read well without it
- Maintain roughly 1–2% keyword density across the article; use semantic variations and \
related terms rather than repeating the exact phrase
- Phrase H2 headings to directly answer a reader question where natural — this improves \
featured snippet eligibility without sounding like a FAQ
- Vary anchor language if referencing related topics inline; never use "click here" or "read more"

Follow the content brief exactly for structure, keywords, and CTA placement.
Hit the word count target. Write the full article, not a summary or outline.

Output format: clean Markdown with H2 and H3 headings only. No bold for emphasis — \
use sentence construction instead. No introduction heading — start the article directly.

After the article, add a separator line and a meta description:

---
**Meta description:** [150–160 character summary that includes the primary keyword and \
gives a clear reason to click — written as a complete sentence, no truncation]

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

WRITER_PROMPT = """Business context: {context}

Topic: {title}
Primary keyword: {primary_keyword}

Content Brief:
{brief}

Write the full article now. Follow the brief structure exactly. \
Target word count: 800–1,200 words. Write as a practitioner, not a researcher."""


async def run(brief: str, topic: dict, business_context: str, api_key: str = ""):
    """Async generator yielding str text chunks."""
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = WRITER_PROMPT.format(
        context=business_context,
        title=topic.get("title", ""),
        primary_keyword=topic.get("primary_keyword", ""),
        brief=brief,
    )

    text_queue: queue.Queue = queue.Queue()

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=WRITER_SYSTEM_PROMPT,
                    temperature=0.7,
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
            yield f"\n\n[Writer error: {value}]"
            break
        elif msg_type == "done":
            break
