"""
Notion service: pushes finished video briefs to a Notion database.

Saves each brief as a single page with concept overview properties and
a full shot-by-shot breakdown in the page body.

Required Notion database columns:
  - Name           (title)
  - Platform       (select — TikTok / Instagram / YouTube / Other)
  - Duration       (rich_text)
  - Visual Style   (rich_text)
  - Audio Mood     (rich_text)
  - Hook Strategy  (rich_text)
  - Status         (select: Draft / In Production / Published)
  - Date Created   (date)

Set NOTION_VIDEO_DATABASE_ID in your .env file.
"""

import asyncio
import os
from datetime import datetime, timezone

import httpx

_NOTION_VERSION = "2022-06-28"
_NOTION_PAGES_URL = "https://api.notion.com/v1/pages"


def _headers(notion_token: str) -> dict:
    return {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _rich_text(value: str) -> list:
    """Build a rich_text array, chunking at Notion's 2000-char limit."""
    if not value:
        return [{"type": "text", "text": {"content": ""}}]
    segments = [value[i:i + 2000] for i in range(0, len(value), 2000)]
    return [{"type": "text", "text": {"content": seg}} for seg in segments]


def _paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _heading_block(text: str, level: int = 1) -> dict:
    htype = f"heading_{level}"
    return {
        "object": "block",
        "type": htype,
        htype: {"rich_text": _rich_text(text)},
    }


async def save_brief(concept: dict, shots: list[dict], notion_token: str = "", database_id: str = "") -> str:
    """
    Save a video brief as a Notion page. Returns the page URL.

    Raises ValueError if database_id is not available.
    """
    if not database_id:
        database_id = os.environ.get("NOTION_VIDEO_DATABASE_ID", "")
    if not notion_token:
        notion_token = os.environ.get("NOTION_TOKEN", "")
    if not database_id:
        raise ValueError(
            "Notion Video database ID is not configured. "
            "Complete Notion setup in Settings to enable saving briefs."
        )

    url = await asyncio.to_thread(_create_brief_page_sync, concept, shots, database_id, notion_token)
    return url


def _create_brief_page_sync(concept: dict, shots: list[dict], database_id: str, notion_token: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = concept.get("title") or "Video Brief"
    platform = concept.get("platform") or "Other"
    duration = concept.get("duration") or ""
    visual_style = concept.get("visual_style") or ""
    audio_mood = concept.get("audio_mood") or ""
    hook_strategy = concept.get("hook_strategy") or ""

    # Build page body blocks
    blocks = [
        _heading_block("Concept Overview", 1),
        _paragraph_block(f"Platform: {platform}"),
        _paragraph_block(f"Duration: {duration}"),
        _paragraph_block(f"Visual Style: {visual_style}"),
        _paragraph_block(f"Audio Mood: {audio_mood}"),
        _paragraph_block(f"Hook Strategy: {hook_strategy}"),
        _heading_block("Shot Breakdown", 1),
    ]

    for shot in shots:
        shot_id = shot.get("id", "")
        shot_dur = shot.get("duration", "")
        blocks.append(_heading_block(f"Shot {shot_id} — {shot_dur}", 2))
        blocks.append(_paragraph_block(f"Runway Prompt: {shot.get('runway_prompt', '')}"))
        blocks.append(_paragraph_block(f"Camera: {shot.get('camera', '')}"))
        blocks.append(_paragraph_block(f"On-Screen Text: {shot.get('on_screen_text', 'None')}"))
        blocks.append(_paragraph_block(f"B-Roll Note: {shot.get('broll_note', 'None')}"))

    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "Platform": {"select": {"name": platform}},
            "Duration": {"rich_text": _rich_text(duration)},
            "Visual Style": {"rich_text": _rich_text(visual_style)},
            "Audio Mood": {"rich_text": _rich_text(audio_mood)},
            "Hook Strategy": {"rich_text": _rich_text(hook_strategy)},
            "Status": {"select": {"name": "Draft"}},
            "Date Created": {"date": {"start": today}},
        },
        "children": blocks[:100],
    }

    response = httpx.post(_NOTION_PAGES_URL, headers=_headers(notion_token), json=payload)
    response.raise_for_status()
    return response.json()["url"]
