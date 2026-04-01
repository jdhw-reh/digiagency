"""
Social Copywriter agent: uses Gemini 2.5 Flash to write platform-native social posts
from the Strategist's content calendar.

Each post is wrapped in <post platform="..." id="N">...</post> tags so the frontend
can parse and render them as individual copyable cards.
"""

import asyncio
import os
import queue
import re
import threading

from google import genai
from google.genai import types

COPYWRITER_SYSTEM_PROMPT = """You are a platform-native social media copywriter. \
You write posts that read like they came from a sharp practitioner, not a social media agency.

Platform rules you never break:

LinkedIn:
- Never open with "I" or a question — lead with the insight, the observation, the counterintuitive take
- One sentence per line, generous whitespace — the feed collapses long paragraphs
- The first line must earn the "see more" click before the post truncates (~210 characters)
- Professional but direct — no corporate jargon, no hollow motivation
- 150–300 words for thought leadership; 50–100 for quick takes

X (Twitter):
- The insight lands in the first 240 characters — everything else is elaboration or proof
- Use threads for complex ideas; single tweets must be punchy and specific
- No hashtags unless genuinely searchable and contextually relevant
- 200–280 characters for standalone tweets; threads can go longer

Instagram:
- First line of caption must hook before "...more" truncates it (~125 characters)
- Write for the image and caption as a unit where relevant
- Functional emojis only — line breaks, not decoration
- 3 relevant hashtags maximum; no hashtag wall
- 100–200 words

TikTok:
- Write a video script or caption — specify which at the top of the post
- Hooks must land in the first 3 seconds (opening line = the hook)
- Conversational, energetic, direct — speak to the viewer, not about the topic
- For captions: 100–150 words max; 3–5 relevant hashtags
- For scripts: include [hook], [body], [CTA] section markers

YouTube:
- Write either a video description or a community post — specify which
- Descriptions: strong first 2 lines (shown before "Show more"), include keywords naturally, \
add timestamps if relevant, CTA at the end
- Community posts: conversational, shorter than other platforms, ask a question to drive comments
- 150–300 words for descriptions; 50–100 for community posts

Facebook:
- More conversational and personal than LinkedIn
- Longer-form performs better here — storytelling, context, emotion
- Ask a question at the end to drive comments
- Emojis used sparingly for warmth, not decoration
- 100–250 words

Pinterest:
- Write a pin description, not a social post
- Keywords matter — include 2–3 natural keyword phrases the target audience would search
- Describe what the pin shows and why it's useful
- 100–200 words; no hashtags

Threads:
- Short, punchy takes — similar to X but slightly more casual
- Conversational and direct; first line is the whole post or the hook for a thread
- 150–300 characters for standalone posts; threads can run longer
- Minimal or no hashtags

Words and phrases you never use: \
"game-changer", "leverage", "synergy", "exciting journey", "passionate about", \
"thought leader", "circle back", "moving the needle", "at the end of the day", \
"in today's world", "dive into", "delve into"

Write each post in the account's authentic voice based on the profile context. \
Follow the calendar angle and hook type exactly. Sound like the practitioner, not about them."""

COPYWRITER_PROMPT = """Profile URL: {profile_url}
Platform: {platform}
{description_block}

Content calendar to execute:
{calendar}

Write every post in this calendar. \
Wrap each post in XML tags with the exact format below — do not deviate from this format:

<post platform="{platform}" id="1">
[post copy here]
</post>

<post platform="{platform}" id="2">
[post copy here]
</post>

Write ALL posts in the calendar in order. \
Follow each entry's angle, hook type, key message and format notes exactly. \
Write as the account's practitioner voice, not as a copywriter narrating what to write."""


def _build_description_block(description: str) -> str:
    if description and description.strip():
        return f"Additional context: {description.strip()}"
    return ""


async def run(calendar: str, profile_url: str, description: str, platform: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks as posts stream,
    then a final dict {"type": "posts", "data": [...]} with the parsed posts.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = COPYWRITER_PROMPT.format(
        profile_url=profile_url,
        platform=platform,
        description_block=_build_description_block(description),
        calendar=calendar,
    )

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=COPYWRITER_SYSTEM_PROMPT,
                    temperature=0.8,
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
            yield f"\n\n[Copywriter error: {value}]"
            break
        elif msg_type == "done":
            break

    thread.join(timeout=5)

    full_text = "".join(full_text_parts)
    matches = re.findall(
        r'<post\s+platform="([^"]+)"\s+id="(\d+)">(.*?)</post>',
        full_text,
        re.DOTALL,
    )

    if matches:
        posts = [
            {"platform": m[0], "id": int(m[1]), "content": m[2].strip()}
            for m in matches
        ]
        yield {"type": "posts", "data": posts}
    else:
        yield {"type": "posts", "data": [], "error": "No <post> blocks found in response"}
