"""
Social Scout agent: uses Gemini 2.5 Flash with Google Search grounding
to analyse a social media profile, identify its niche, find competitor
accounts, and surface content opportunities.
"""

import asyncio
import json
import os
import queue
import re
import threading

from google import genai
from google.genai import types

SCOUT_SYSTEM_PROMPT = """You are a social media intelligence analyst. \
You specialise in profiling accounts, benchmarking competitors, and identifying \
content opportunities that will actually perform.

You have access to real-time Google Search. Use it rigorously — every claim \
about an account, competitor, or stat should come from what you actually find, \
not what you assume.

When researching accounts:
- Search for the account by URL and handle to understand what they post about
- Look for publicly available stats: follower counts, average engagement, view counts
- Search Social Blade, third-party tools, or news/media coverage for performance data
- If direct stats are unavailable, note that and describe content patterns instead

Be specific. Vague intelligence wastes everyone's time.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

SCOUT_PROMPT = """Profile URL: {profile_url}
Platform: {platform}
{description_block}

Your job is to analyse this account and the competitive landscape around it.

Step 1 — Profile the account:
Search for this profile. Identify:
- The niche or industry this account operates in
- The type of content they post (format, tone, topics)
- Any publicly available performance data (followers, engagement, views)

Step 2 — Find competitor accounts:
Search for 4–6 similar accounts on {platform} in the same niche. \
For each, find: follower count, typical engagement (likes/comments/views per post), \
posting frequency, and what content types perform best for them.

Step 3 — Identify content opportunities:
Based on what competitors are doing well and poorly, identify 5–8 specific \
content angles this account could exploit. Look for gaps, underserved topics, \
and formats that are gaining traction in the niche.

Write a 2–3 paragraph analysis covering: what niche this account is in, \
how the competitive landscape looks, and the single biggest underserved opportunity.

Then output ALL opportunities as a JSON array enclosed in <opportunities> and </opportunities> tags:

<opportunities>
[
  {{
    "platform": "{platform}",
    "angle": "specific content angle — be precise, not generic",
    "hook_type": "one of: curiosity | contrarian | story | proof | how-to",
    "why_now": "why this opportunity exists based on your research",
    "competitor_gap": "what competitors are missing that this account can own"
  }}
]
</opportunities>"""


def _build_description_block(description: str) -> str:
    if description and description.strip():
        return f"Additional context from account owner: {description.strip()}"
    return ""


async def run(profile_url: str, description: str, platform: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks, then a final dict
    {"type": "opportunities", "data": [...]} with parsed opportunities.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    prompt = SCOUT_PROMPT.format(
        profile_url=profile_url,
        platform=platform,
        description_block=_build_description_block(description),
    )

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SCOUT_SYSTEM_PROMPT,
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
            yield {"type": "error", "message": value}
            break
        elif msg_type == "done":
            break

    thread.join(timeout=5)

    full_text = "".join(full_text_parts)
    match = re.search(r"<opportunities>(.*?)</opportunities>", full_text, re.DOTALL)
    if match:
        try:
            opportunities = json.loads(match.group(1).strip())
            yield {"type": "opportunities", "data": opportunities}
        except json.JSONDecodeError as e:
            yield {"type": "opportunities", "data": [], "error": f"Failed to parse opportunities JSON: {e}"}
    else:
        yield {"type": "opportunities", "data": [], "error": "No <opportunities> block found in response"}
