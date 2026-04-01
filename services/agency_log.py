"""
Agency Log service: records completed tasks from all teams into a central
Notion database — the agency's persistent memory.

Required Notion database columns:
  - Name        (title)
  - Team        (select: Content Team | Social Team | SEO Audit | Assistant)
  - Type        (select: Article | Social Posts | SEO Audit | Note)
  - Status      (select: Completed)
  - Date        (date)
  - Link        (url)  — optional, content/social Notion page URL

Set NOTION_AGENCY_LOG_DB_ID in .env to enable. If the variable is missing the
function silently no-ops so the rest of the app still works.
"""

import asyncio
import os
from datetime import datetime, timezone

from notion_client import Client

async def log_task(
    team: str,
    task_type: str,
    title: str,
    link: str | None = None,
    notion_token: str = "",
    db_id: str = "",
) -> None:
    """
    Create a record in the Agency Log Notion database.

    team      — human label: "Content Team" | "Social Team" | "SEO Audit" | "Assistant"
    task_type — "Article" | "Social Posts" | "SEO Audit" | "Note"
    title     — short description of what was completed
    link      — optional Notion URL to the produced content
    """
    if not db_id:
        db_id = os.environ.get("NOTION_AGENCY_LOG_DB_ID", "")
    if not notion_token:
        notion_token = os.environ.get("NOTION_TOKEN", "")
    if not db_id or not notion_token:
        return  # graceful no-op if not configured

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _create_sync() -> None:
        client = Client(auth=notion_token)
        props: dict = {
            "Name": {
                "title": [{"text": {"content": title}}]
            },
            "Team": {
                "select": {"name": team}
            },
            "Type": {
                "select": {"name": task_type}
            },
            "Status": {
                "select": {"name": "Completed"}
            },
            "Date": {
                "date": {"start": today}
            },
        }
        if link:
            props["Link"] = {"url": link}

        client.pages.create(
            parent={"database_id": db_id},
            properties=props,
        )

    await asyncio.to_thread(_create_sync)
