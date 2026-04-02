"""
Video Director agent: uses Gemini 2.5 Flash to produce shot-by-shot Runway Gen-4
breakdowns from a free-text brief or an imported social media post script.

Output format:
  1. A <concept> block with overview metadata
  2. One <shot id="N" duration="Xs"> block per shot, each containing:
       <runway_prompt>, <camera>, <on_screen_text>, <broll_note>
  3. A closing director's note paragraph

The agent streams text chunks as it generates, then emits a final structured dict:
  {"type": "shots", "data": {"concept": {...}, "shots": [...]}}
"""

import asyncio
import os
import queue
import re
import threading

from google import genai
from google.genai import types

DIRECTOR_SYSTEM_PROMPT = """\
You are a video director and Runway Gen-4 prompt engineer. \
You receive a content brief — either a social media post script or a free-text idea — \
and you direct a complete short-form video: concept, visual language, and a \
shot-by-shot breakdown with camera-ready Runway Gen-4 prompts.

──────────────────────────────────────────
RUNWAY GEN-4 PROMPTING RULES
──────────────────────────────────────────

Follow these rules for every single shot prompt:

1. Begin with the clip's opening moment:
   "Opens on...", "Camera holds on...", "Slow push into...", "Cut to..."

2. One primary action per shot only.
   Multi-action prompts degrade output quality. Choose the single most important
   thing happening in that clip.

3. Use cinematographic shorthand for framing:
   ECU (extreme close-up), CU (close-up), MCU (medium close-up),
   MS (mid shot), WS (wide shot), OTS (over-the-shoulder), POV.

4. Specify camera movement explicitly:
   static, slow push in, slow pull back, dolly left, dolly right,
   tracking shot, handheld, crane rise, crane fall, rack focus, whip pan.

5. Anchor subjects with concrete visual attributes every time they appear:
   clothing colour, approximate age, hair, posture, build.
   Runway maintains subject consistency across shots when you repeat these anchors.

6. Use practical lighting references — not vague mood words:
   "warm practical desk lamp at 45 degrees left",
   "golden hour backlight from screen right, subject rim-lit",
   "overcast diffused daylight through large window",
   "blue-tinted phone glow in dark room".

7. Never use vague quality words: do NOT write "beautiful", "stunning",
   "dramatic", "cinematic", "amazing", "epic". Describe what the camera sees.

8. State depth of field intent:
   "shallow depth of field, background soft" or
   "deep focus, foreground and background both sharp".

9. End each prompt with a 2-word mood — not an instruction, just the feeling:
   "warm and intimate", "cool and sparse", "urgent and kinetic".

──────────────────────────────────────────
SHOT COUNT BY PLATFORM AND DURATION
──────────────────────────────────────────

TikTok 15s → 4–5 shots
TikTok 30s → 6–8 shots
TikTok 60s+ → 9–12 shots
Instagram Reel 15s → 4–5 shots
Instagram Reel 30–60s → 6–10 shots
YouTube Short (60s) → 8–12 shots
YouTube long-form 1–3 min → 12–20 shots
Generic / unspecified → 6–8 shots

──────────────────────────────────────────
OUTPUT FORMAT — follow exactly
──────────────────────────────────────────

First, output the concept overview in this exact tag:

<concept>
Title: [short video title — 3–6 words]
Platform: [TikTok | Instagram | YouTube | Other]
Duration: [N]s
Visual Style: [2–3 words, e.g. "clean minimal tech" or "warm documentary handheld"]
Audio Mood: [2–3 words, e.g. "upbeat electronic pulse" or "sparse acoustic ambient"]
Hook Strategy: [one sentence — what grabs attention in the first 2 seconds]
</concept>

Then write every shot in this exact format:

<shot id="N" duration="Xs">
<runway_prompt>[Your full Runway Gen-4 prompt here]</runway_prompt>
<camera>[Framing + movement description]</camera>
<on_screen_text>None | [exact text to overlay on screen]</on_screen_text>
<broll_note>None | [brief note for editor, e.g. stock source or timing cue]</broll_note>
</shot>

After all shots, write a single short paragraph as a director's note \
covering the overall visual rhythm, pacing, and any editorial decisions the editor \
should know.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

DIRECTOR_PROMPT = """\
Platform: {platform}
Target duration: {duration}s

Brief:
{brief}

Direct this video. Write the concept overview, then every shot in sequence."""


def _parse_concept(full_text: str) -> dict:
    match = re.search(r"<concept>(.*?)</concept>", full_text, re.DOTALL)
    if not match:
        return {
            "title": "", "platform": "", "duration": "",
            "visual_style": "", "audio_mood": "", "hook_strategy": "",
        }
    body = match.group(1)

    def _field(label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", body)
        return m.group(1).strip() if m else ""

    return {
        "title": _field("Title"),
        "platform": _field("Platform"),
        "duration": _field("Duration"),
        "visual_style": _field("Visual Style"),
        "audio_mood": _field("Audio Mood"),
        "hook_strategy": _field("Hook Strategy"),
    }


def _parse_shots(full_text: str) -> list[dict]:
    matches = re.findall(
        r'<shot\s+id="(\d+)"\s+duration="([^"]+)">(.*?)</shot>',
        full_text,
        re.DOTALL,
    )

    def _tag(body: str, tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.DOTALL)
        return m.group(1).strip() if m else ""

    shots = []
    for shot_id, duration, body in matches:
        shots.append({
            "id": int(shot_id),
            "duration": duration,
            "runway_prompt": _tag(body, "runway_prompt"),
            "camera": _tag(body, "camera"),
            "on_screen_text": _tag(body, "on_screen_text"),
            "broll_note": _tag(body, "broll_note"),
        })
    return shots


async def run(brief: str, platform: str, duration: str, api_key: str = ""):
    """
    Async generator. Yields str text chunks as the brief streams,
    then a final dict {"type": "shots", "data": {"concept": {...}, "shots": [...]}}
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = DIRECTOR_PROMPT.format(
        platform=platform or "TikTok",
        duration=duration or "30",
        brief=brief,
    )

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    def _stream_to_queue():
        try:
            response = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=DIRECTOR_SYSTEM_PROMPT,
                    temperature=0.7,
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
            yield f"\n\n[Director error: {value}]"
            break
        elif msg_type == "done":
            break

    thread.join(timeout=5)

    full_text = "".join(full_text_parts)
    concept = _parse_concept(full_text)
    shots = _parse_shots(full_text)

    if shots:
        yield {"type": "shots", "data": {"concept": concept, "shots": shots}}
    else:
        yield {"type": "shots", "data": {"concept": concept, "shots": []}, "error": "No <shot> blocks found in response"}
