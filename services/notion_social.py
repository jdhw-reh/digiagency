"""
Notion service: pushes finished social posts to a Notion database.

Saves all posts from a campaign as individual pages in the social posts database.

Required Notion database columns:
  - Name        (title)
  - Platform    (select — auto-created per platform: LinkedIn / X / Instagram /
                 TikTok / YouTube / Facebook / Pinterest / Threads / Snapchat)
  - Status      (select: Draft / Scheduled / Posted)
  - Date Created (date)

Set NOTION_SOCIAL_DATABASE_ID in your .env file.
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


async def save_posts(posts: list[dict], notion_token: str = "", database_id: str = "") -> list[dict]:
    """
    Save each post as a Notion page. Returns a list of {platform, url} dicts.

    Raises ValueError if database_id is not available.
    """
    if not database_id:
        database_id = os.environ.get("NOTION_SOCIAL_DATABASE_ID", "")
    if not notion_token:
        notion_token = os.environ.get("NOTION_TOKEN", "")
    if not database_id:
        raise ValueError(
            "Notion Social database ID is not configured. "
            "Complete Notion setup in Settings to enable saving posts."
        )

    results = []
    for post in posts:
        url = await asyncio.to_thread(_create_post_page_sync, post, database_id, notion_token)
        results.append({"platform": post.get("platform", ""), "url": url})

    return results


def _create_post_page_sync(post: dict, database_id: str, notion_token: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    platform = post.get("platform", "LinkedIn")
    content = post.get("content", "")
    post_id = post.get("id", 1)

    # Build content blocks. Notion enforces a 2000-char limit per rich_text segment.
    blocks = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        segments = [line[i:i + 2000] for i in range(0, len(line), 2000)]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": seg}} for seg in segments
                ]
            },
        })

    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"text": {"content": f"{platform} post #{post_id}"}}]},
            "Platform": {"select": {"name": platform}},
            "Status": {"select": {"name": "Draft"}},
            "Date Created": {"date": {"start": today}},
        },
        "children": blocks[:100],
    }

    response = httpx.post(_NOTION_PAGES_URL, headers=_headers(notion_token), json=payload)
    response.raise_for_status()
    return response.json()["url"]
