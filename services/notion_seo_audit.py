"""
Notion SEO Audit service: saves a completed SEO audit report to a Notion page.

Creates a rich page with sections for each pipeline stage plus a technical
score card and an implementation checklist.

Required Notion database columns (same DB as articles, or a separate one):
  - Name       (title)   — the audited URL
  - Status     (select)  — "Completed"
  - Domain     (rich_text)
  - Score      (number)  — technical SEO score /10
  - CMS        (select)
  - Date       (date)

Set NOTION_SEO_AUDIT_DB_ID in .env to enable. If missing, silently no-ops.
"""

import asyncio
import os
from datetime import datetime, timezone

from notion_client import Client

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


def _code_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": "plain text",
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
        },
    }


def _todo(text: str, checked: bool = False) -> dict:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
            "checked": checked,
        },
    }


def _markdown_to_blocks(markdown: str) -> list[dict]:
    """Convert markdown text to Notion blocks (headings, bullets, paragraphs)."""
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
        elif line.startswith("[ ] ") or line.startswith("- [ ] "):
            task = line.replace("- [ ] ", "").replace("[ ] ", "")
            blocks.append(_todo(task, checked=False))
        elif line.startswith("[x] ") or line.startswith("- [x] "):
            task = line.replace("- [x] ", "").replace("[x] ", "")
            blocks.append(_todo(task, checked=True))
        else:
            blocks.append(_text_block(line))
    return blocks


def _build_audit_blocks(
    url: str,
    audit_data: dict,
    audit_text: str,
    analysis: str,
    recommendations: str,
    implementation: str,
) -> list[dict]:
    """Build the full list of Notion blocks for the audit report."""
    blocks: list[dict] = []

    # --- Score card ---
    score = audit_data.get("technical_score", "N/A")
    cms = audit_data.get("cms", "Unknown")
    tech = audit_data.get("technical_signals", {})
    issues = audit_data.get("technical_issues", [])

    blocks.append(_heading_block("Technical Score Card", 2))
    blocks.append(_bullet(f"SEO Score: {score}/10"))
    blocks.append(_bullet(f"CMS: {cms}"))
    blocks.append(_bullet(f"HTTPS: {'Yes' if tech.get('https') else 'No'}"))
    blocks.append(_bullet(f"Title: {tech.get('title', 'Not found')} ({tech.get('title_length', 0)} chars)"))
    blocks.append(_bullet(f"Meta description: {'Present' if tech.get('meta_description') else 'Missing'} ({tech.get('meta_description_length', 0)} chars)"))
    blocks.append(_bullet(f"H1 tags: {tech.get('h1_count', 0)}"))
    blocks.append(_bullet(f"Schema markup: {', '.join(tech.get('schema_types', [])) or 'None'}"))
    blocks.append(_bullet(f"Images missing alt text: {tech.get('images_missing_alt', 0)} / {tech.get('total_images', 0)}"))
    blocks.append(_bullet(f"Open Graph tags: {'Present' if tech.get('og_title') else 'Missing'}"))
    blocks.append(_bullet(f"Mobile viewport: {'Present' if tech.get('has_viewport') else 'Missing'}"))
    blocks.append(_divider())

    # --- Technical issues ---
    if issues:
        blocks.append(_heading_block("Technical Issues Found", 2))
        for i in issues:
            sev = i.get("severity", "").upper()
            blocks.append(_bullet(f"[{sev}] {i.get('issue', '')}"))
        blocks.append(_divider())

    # --- Audit findings ---
    blocks.append(_heading_block("Audit Findings", 2))
    # Strip the <audit_data>...</audit_data> JSON block from display text
    import re
    clean_audit = re.sub(r"<audit_data>.*?</audit_data>", "", audit_text, flags=re.DOTALL).strip()
    blocks.extend(_markdown_to_blocks(clean_audit))
    blocks.append(_divider())

    # --- Analysis ---
    blocks.append(_heading_block("Strategic Analysis", 2))
    blocks.extend(_markdown_to_blocks(analysis))
    blocks.append(_divider())

    # --- Recommendations ---
    blocks.append(_heading_block("Prioritised Recommendations", 2))
    blocks.extend(_markdown_to_blocks(recommendations))
    blocks.append(_divider())

    # --- Implementation guide ---
    blocks.append(_heading_block("Implementation Guide", 2))
    blocks.extend(_markdown_to_blocks(implementation))

    return blocks


async def save_audit_report(
    url: str,
    audit_data: dict,
    audit_text: str,
    analysis: str,
    recommendations: str,
    implementation: str,
    notion_token: str = "",
    db_id: str = "",
) -> str | None:
    """
    Save the full audit report to Notion. Returns the page URL or None.
    """
    if not db_id:
        db_id = os.environ.get("NOTION_SEO_AUDIT_DB_ID", "")
    if not notion_token:
        notion_token = os.environ.get("NOTION_TOKEN", "")
    if not db_id or not notion_token:
        return None

    from urllib.parse import urlparse
    domain = urlparse(url).netloc or url
    score = audit_data.get("technical_score")
    cms = audit_data.get("cms", "Unknown")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    blocks = _build_audit_blocks(url, audit_data, audit_text, analysis, recommendations, implementation)

    def _create_sync() -> str:
        client = Client(auth=notion_token)

        props: dict = {
            "Name": {"title": [{"text": {"content": f"SEO Audit — {domain}"}}]},
            "Status": {"select": {"name": "Completed"}},
            "Domain": {"rich_text": [{"text": {"content": domain}}]},
            "Date": {"date": {"start": today}},
        }
        if score is not None:
            props["Score"] = {"number": int(score)}
        if cms:
            props["CMS"] = {"select": {"name": cms}}

        # Notion allows max 100 blocks per create call
        response = client.pages.create(
            parent={"database_id": db_id},
            properties=props,
            children=blocks[:100],
        )
        page_id = response["id"]
        page_url = response.get("url", "")

        # Append remaining blocks in batches of 100
        remaining = blocks[100:]
        while remaining:
            batch, remaining = remaining[:100], remaining[100:]
            client.blocks.children.append(
                block_id=page_id,
                children=batch,
            )

        return page_url

    return await asyncio.to_thread(_create_sync)
