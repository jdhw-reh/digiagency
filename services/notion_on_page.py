"""
Notion On-Page Optimiser service: saves a completed optimisation report to Notion.

Creates a rich page with the analysis (Review mode) or keyword brief (Build mode)
plus the final optimised copy.

Required Notion database columns:
  - Name           (title)   — page title / topic
  - Status         (select)  — "Draft" | "Done"
  - Mode           (select)  — "Review" | "Build"
  - Page Type      (select)  — e.g. "Service Page"
  - Target Keyword (rich_text)
  - Date           (date)

Set NOTION_ON_PAGE_OPT_DB_ID in .env to enable. If missing, silently no-ops.
"""

import asyncio
import os
from datetime import datetime, timezone

from notion_client import Client

# ---------------------------------------------------------------------------
# Block builders (same helpers as notion_seo_audit)
# ---------------------------------------------------------------------------

def _text_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
        },
    }


def _heading_block(text: str, level: int = 2) -> dict:
    htype = f"heading_{level}"
    return {
        "object": "block",
        "type": htype,
        htype: {
            "rich_text": [{"type": "text", "text": {"content": text[:100]}}]
        },
    }


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
        },
    }


def _markdown_to_blocks(markdown: str) -> list[dict]:
    """Convert markdown text to Notion blocks."""
    blocks = []
    for line in markdown.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            blocks.append(_heading_block(line[4:], 3))
        elif line.startswith("## "):
            blocks.append(_heading_block(line[3:], 2))
        elif line.startswith("# "):
            blocks.append(_heading_block(line[2:], 1))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(_bullet(line[2:]))
        elif line.startswith("**") and line.endswith("**"):
            blocks.append(_text_block(line.strip("*")))
        else:
            blocks.append(_text_block(line))
    return blocks


def _build_report_blocks(
    mode: str,
    page_type: str,
    target_keyword: str,
    prompt: str,
    analysis: str,
    keyword_data: dict,
    keyword_brief: str,
    final_copy: str,
) -> list[dict]:
    blocks: list[dict] = []

    if mode == "review":
        # --- Review mode: analysis then rewritten copy ---
        blocks.append(_heading_block("On-Page Analysis", 2))
        if target_keyword:
            blocks.append(_bullet(f"Target keyword: {target_keyword}"))
        if page_type:
            blocks.append(_bullet(f"Page type: {page_type}"))
        blocks.append(_divider())

        if analysis:
            blocks.extend(_markdown_to_blocks(analysis))
            blocks.append(_divider())

        blocks.append(_heading_block("Optimised Copy", 2))
        blocks.extend(_markdown_to_blocks(final_copy))

    else:
        # --- Build mode: keyword brief then new page copy ---
        blocks.append(_heading_block("Keyword Research Brief", 2))
        if prompt:
            blocks.append(_bullet(f"Brief: {prompt}"))
        if page_type:
            blocks.append(_bullet(f"Page type: {page_type}"))

        if keyword_data:
            blocks.append(_bullet(f"Primary keyword: {keyword_data.get('primary_keyword', '—')}"))
            secondary = keyword_data.get("secondary_keywords", [])
            if secondary:
                blocks.append(_bullet(f"Secondary keywords: {', '.join(secondary)}"))
            lsi = keyword_data.get("lsi_terms", [])
            if lsi:
                blocks.append(_bullet(f"LSI terms: {', '.join(lsi)}"))
            if keyword_data.get("search_intent"):
                blocks.append(_bullet(f"Search intent: {keyword_data['search_intent']}"))
            if keyword_data.get("recommended_word_count"):
                blocks.append(_bullet(f"Recommended word count: {keyword_data['recommended_word_count']}"))

        blocks.append(_divider())

        if keyword_brief:
            blocks.extend(_markdown_to_blocks(keyword_brief))
            blocks.append(_divider())

        blocks.append(_heading_block("Generated Page Copy", 2))
        blocks.extend(_markdown_to_blocks(final_copy))

    return blocks


async def save_optimiser_report(
    mode: str,
    page_type: str,
    target_keyword: str,
    prompt: str,
    analysis: str,
    keyword_data: dict,
    keyword_brief: str,
    final_copy: str,
    notion_token: str = "",
    db_id: str = "",
) -> str | None:
    """Save the report to Notion. Returns the page URL or None."""
    if not db_id:
        db_id = os.environ.get("NOTION_ON_PAGE_OPT_DB_ID", "")
    if not notion_token:
        notion_token = os.environ.get("NOTION_TOKEN", "")
    if not db_id or not notion_token:
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Derive a page title
    if mode == "review":
        title = f"On-Page Review — {target_keyword or page_type}"
    else:
        kw = keyword_data.get("primary_keyword") or prompt[:60] if prompt else page_type
        title = f"Page Build — {kw}"

    blocks = _build_report_blocks(
        mode=mode,
        page_type=page_type,
        target_keyword=target_keyword,
        prompt=prompt,
        analysis=analysis,
        keyword_data=keyword_data,
        keyword_brief=keyword_brief,
        final_copy=final_copy,
    )

    def _create_sync() -> str:
        client = Client(auth=notion_token)

        props: dict = {
            "Name": {"title": [{"text": {"content": title}}]},
            "Status": {"select": {"name": "Done"}},
            "Mode": {"select": {"name": "Review" if mode == "review" else "Build"}},
            "Date": {"date": {"start": today}},
        }
        if page_type:
            props["Page Type"] = {"select": {"name": page_type}}
        if target_keyword and mode == "review":
            props["Target Keyword"] = {"rich_text": [{"text": {"content": target_keyword}}]}
        elif keyword_data.get("primary_keyword"):
            props["Target Keyword"] = {"rich_text": [{"text": {"content": keyword_data["primary_keyword"]}}]}

        response = client.pages.create(
            parent={"database_id": db_id},
            properties=props,
            children=blocks[:100],
        )
        page_id = response["id"]
        page_url = response.get("url", "")

        remaining = blocks[100:]
        while remaining:
            batch, remaining = remaining[:100], remaining[100:]
            client.blocks.children.append(block_id=page_id, children=batch)

        return page_url

    return await asyncio.to_thread(_create_sync)
