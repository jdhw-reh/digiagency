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
import time

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt, get_user_prompt


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

    prompt = get_user_prompt(
        "video/director",
        platform=platform or "TikTok",
        duration=duration or "30",
        brief=brief,
    )

    text_queue: queue.Queue = queue.Queue()
    full_text_parts: list[str] = []

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            prompt,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("video/director"),
                temperature=0.7,
            ),
            text_queue,
            full_text_parts,
        )

    thread = threading.Thread(target=_stream_to_queue, daemon=True)
    thread.start()

    deadline = time.monotonic() + 120
    while True:
        try:
            msg_type, value = text_queue.get(timeout=0.05)
            deadline = time.monotonic() + 120  # reset on each message
        except queue.Empty:
            if time.monotonic() > deadline:
                yield {"type": "error", "message": "Video director agent timed out after 120 seconds"}
                return
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
    concept = _parse_concept(full_text)
    shots = _parse_shots(full_text)

    if shots:
        yield {"type": "shots", "data": {"concept": concept, "shots": shots}}
    else:
        yield {"type": "shots", "data": {"concept": concept, "shots": []}, "error": "No <shot> blocks found in response"}
