"""
SEO Implementer agent: turns prioritised recommendations into a concrete,
step-by-step implementation guide tailored to the detected CMS (WordPress
by default), with ready-to-use assets and assistant task-tracking notes.
"""

import asyncio
import json as _json
import os
import queue
import threading

from google import genai
from google.genai import types

IMPLEMENTER_SYSTEM_PROMPT = """You are a hands-on technical SEO specialist and WordPress expert. \
You translate SEO recommendations into exact implementation steps that a non-technical \
business owner can follow inside their CMS — no coding knowledge assumed.

Your output must be practical and complete:
- Every step uses exact menu paths (e.g. "WordPress Admin → Appearance → Theme Editor")
- Where code or markup is needed, provide the exact snippet — ready to copy and paste
- Where a plugin is the right tool, name the specific plugin and the exact settings to change
- Each task ends with a note for the agency assistant to log, so progress can be tracked

You write for people who know their business, not their back-end.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

IMPLEMENTER_PROMPT = """Here is the complete SEO audit for {url}:

Business context: {context}
Detected CMS: {cms}

Technical findings:
{technical_summary}

Strategic analysis:
{analysis}

Prioritised recommendations:
{recommendations}

Produce a step-by-step implementation guide. For each of the top 6 recommendations, write a task block using EXACTLY this format:

---
## TASK [N]: [Task title]
**Priority:** Quick Win / Medium-term / Long-term
**Effort:** Low / Medium / High
**Impact:** Low / Medium / High

### What this fixes
[1–2 sentences on the SEO problem and why it matters for rankings/clicks.]

### Step-by-step instructions ({cms})
1. [Exact step with menu path, button name, or field label]
2. [Next step]
3. [Continue until complete]

### Ready-to-use asset
[If applicable: paste the exact title tag copy, meta description, JSON-LD schema block, \
redirect rule, or other ready-to-implement asset. If no asset needed, write "No asset required."]

### ✅ Assistant task note
**Log as:** "[Short task title for the agency log]"
**Status:** To Do
**Notes:** [1–2 sentences the assistant should record — what was found, what was done, what to check next time]
---

After all 6 tasks, add a final section:

## Implementation Checklist
A numbered list of all 6 tasks with their priority and a [ ] checkbox.

## Assistant Summary Note
A short paragraph (3–5 sentences) the assistant should save as a note in the agency log. \
Include: the site audited, the top 3 issues found, and what the client should tackle first."""


async def run(url: str, context: str, cms: str, audit_data: dict, analysis: str, recommendations: str, api_key: str = ""):
    """Stream the implementation guide. Yields text chunks then a done event."""

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    # Build a readable technical summary from audit_data
    tech = audit_data.get("technical_signals", {})
    issues = audit_data.get("technical_issues", [])

    tech_lines = []
    if issues:
        for i in issues:
            tech_lines.append(f"- [{i.get('severity', '').upper()}] {i.get('issue', '')}")
    else:
        # Fall back to raw signals
        if tech:
            tech_lines.append(f"- Title: {tech.get('title', 'N/A')} ({tech.get('title_length', 0)} chars)")
            tech_lines.append(f"- Meta description: {'Present' if tech.get('meta_description') else 'MISSING'}")
            tech_lines.append(f"- H1 count: {tech.get('h1_count', 0)}")
            tech_lines.append(f"- Schema markup: {', '.join(tech.get('schema_types', [])) or 'None detected'}")
            tech_lines.append(f"- Images missing alt text: {tech.get('images_missing_alt', 0)}")
            tech_lines.append(f"- Open Graph tags: {'Present' if tech.get('og_title') else 'Missing'}")
    technical_summary = "\n".join(tech_lines) if tech_lines else _json.dumps(audit_data, indent=2)[:1500]

    prompt = IMPLEMENTER_PROMPT.format(
        url=url,
        context=context,
        cms=cms or "WordPress",
        technical_summary=technical_summary,
        analysis=analysis,
        recommendations=recommendations,
    )

    result_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=IMPLEMENTER_SYSTEM_PROMPT,
                    temperature=0.3,
                ),
            ):
                if chunk.text:
                    result_queue.put(("chunk", chunk.text))
            result_queue.put(("done", None))
        except Exception as exc:
            result_queue.put(("error", str(exc)))

    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=90)
            )
        except queue.Empty:
            yield ("error", "Implementer timed out")
            return

        if kind == "chunk":
            yield ("chunk", value)
        elif kind == "done":
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
