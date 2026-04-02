"""
Social Strategist agent: uses Gemini 2.5 Flash to build a 2-week content calendar
from the Scout's competitive research and the selected opportunity.

No web search — pure strategic reasoning.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types

STRATEGIST_SYSTEM_PROMPT = """You are a social content director with a decade of experience \
building engaged audiences for brands across every major platform.

You create 2-week content calendars that are:
- Platform-native: every post fits the format, tone, algorithm, and culture of its specific platform
- Varied: a mix of hook types — contrarian takes, stories, proof points, practical how-to, \
and curiosity-driven observations
- Achievable: realistic posting frequency that builds consistency without burnout
- Strategic: each post serves a clear purpose — awareness, engagement, authority, or lead generation

Your calendar entries give the copywriter everything they need to write without guessing: \
the platform, content type, the specific hook and angle, the key message, and any format notes.

Write with precision. Vague calendar entries produce mediocre copy. Specific ones produce great copy.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

STRATEGIST_PROMPT = """Profile URL: {profile_url}
Platform: {platform}
{description_block}

Selected content opportunity from Scout research:
{opportunity}

Build a 2-week content calendar for this {platform} account based on the opportunity above. \
All posts should be for {platform} unless a cross-post makes clear strategic sense.

Format each entry exactly like this (use the separator line between entries):

**Day [N] — {platform}**
Hook type: [hook type]
Angle: [specific angle — be precise]
Key message: [1–2 sentences capturing the core idea the post should land]
Format note: [any guidance on format, length, visuals, CTA, or platform-specific features]

---

Create 10–14 entries total. Vary hook types across the calendar — no more than two consecutive \
entries of the same type. Prioritise quality and achievability. Do not pad the calendar with weak ideas."""


def _build_description_block(description: str) -> str:
    if description and description.strip():
        return f"Additional context: {description.strip()}"
    return ""


async def run(opportunity: dict, profile_url: str, description: str, platform: str, api_key: str = ""):
    """Async generator yielding str text chunks."""
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    opp_text = (
        f"Angle: {opportunity.get('angle', '')}\n"
        f"Hook type: {opportunity.get('hook_type', '')}\n"
        f"Why now: {opportunity.get('why_now', '')}\n"
        f"Competitor gap: {opportunity.get('competitor_gap', '')}"
    )

    prompt = STRATEGIST_PROMPT.format(
        profile_url=profile_url,
        platform=platform,
        description_block=_build_description_block(description),
        opportunity=opp_text,
    )

    text_queue: queue.Queue = queue.Queue()

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=STRATEGIST_SYSTEM_PROMPT,
                    temperature=0.5,
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
            yield f"\n\n[Strategist error: {value}]"
            break
        elif msg_type == "done":
            break
