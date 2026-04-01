"""
Notion service: pushes finished articles to a Notion database.

The notion-client library is synchronous, so we wrap the blocking call in
asyncio.to_thread to avoid blocking FastAPI's event loop.

Required Notion database columns:
  - Name       (title)
  - Status     (select: Draft / Ready)
  - Primary Keyword  (rich_text)
  - Search Intent    (select)
"""

import asyncio
import os
from datetime import datetime, timezone

from notion_client import Client

def _markdown_to_notion_blocks(markdown: str) -> list[dict]:
    """
    Convert Markdown text to a list of Notion block objects.

    Handles: # H1, ## H2, ### H3, - bullet items, blank lines (skipped),
    and everything else as paragraph blocks.

    Notion API limit: 100 blocks per create request. At 800–1,200 words this
    limit is never hit, but we guard with a slice in create_article_page.
    """
    blocks = []
    for line in markdown.split("\n"):
        line = line.rstrip()

        if not line:
            continue

        if line.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": line[4:]}}]
                },
            })
        elif line.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": line[3:]}}]
                },
            })
        elif line.startswith("# "):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": line[2:]}}]
                },
            })
        elif line.startswith("- "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": line[2:]}}]
                },
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                },
            })

    return blocks


async def create_article_page(title: str, article_markdown: str, topic: dict, notion_token: str, database_id: str) -> str:
    """
    Create a Notion page for the article and return its URL.
    Initial status is set to 'Draft'.
    """
    def _create_sync() -> str:
        client = Client(auth=notion_token)
        blocks = _markdown_to_notion_blocks(article_markdown)

        search_intent = topic.get("search_intent", "informational")
        search_intent_label = search_intent.capitalize()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        response = client.pages.create(
            parent={"database_id": database_id},
            properties={
                "Name": {
                    "title": [{"text": {"content": title}}]
                },
                "Status": {
                    "select": {"name": "Draft"}
                },
                "Primary Keyword": {
                    "rich_text": [{"text": {"content": topic.get("primary_keyword", "")}}]
                },
                "Search Intent": {
                    "select": {"name": search_intent_label}
                },
                "Date Created": {
                    "date": {"start": today}
                },
            },
            # Notion enforces a 100-block limit per create call
            children=blocks[:100],
        )
        return response["url"]

    return await asyncio.to_thread(_create_sync)
