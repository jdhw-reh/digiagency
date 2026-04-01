"""
On-Page Optimiser — Copywriter agent

Operates in two modes:
  - Review mode: rewrites/fixes supplied copy based on the analysis findings
  - Build mode: writes a full new page from scratch using the keyword research brief

Produces clean, well-structured, SEO-optimised copy ready to publish.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types

COPYWRITER_SYSTEM_PROMPT = """You are an expert SEO copywriter who produces copy that ranks \
and converts. You write with authority, clarity and natural keyword integration. Your copy \
is structured for both search engines and humans — clear headings, scannable sections, \
strong calls to action.

You never keyword-stuff. You write like a human expert, not a machine. Every page you \
produce has a clear purpose, a strong value proposition and a logical flow from top to bottom."""

REWRITE_PROMPT = """You have analysed the following page copy and identified on-page SEO issues. \
Now rewrite the copy to fix all identified problems.

Page type: {page_type}
Target keyword: {target_keyword}

--- ORIGINAL COPY ---
{original_copy}
--- END ORIGINAL COPY ---

--- SEO ANALYSIS (issues to fix) ---
{analysis}
--- END ANALYSIS ---

Rewrite the copy applying all priority fixes from the analysis. Follow these rules:
- Integrate the target keyword naturally into the H1, first paragraph, and at least 2 subheadings
- Include semantic / LSI terms highlighted in the analysis
- Fix any thin content sections by expanding them
- Correct the heading hierarchy
- Match the search intent perfectly
- Write a suggested title tag (50–60 chars) and meta description (140–160 chars) at the top

Format the output as:
**Title Tag:** [your suggested title]
**Meta Description:** [your suggested meta description]

---

[Full rewritten copy with headings in markdown format]

Maintain the client's voice and any factual details from the original. Do not invent \
specific claims, prices or credentials that weren't in the original."""

BUILD_PROMPT = """Write a full {page_type} optimised for search using the keyword research below.

--- KEYWORD BRIEF ---
{keyword_brief}
--- END KEYWORD BRIEF ---

{audit_context_section}
Additional context: {prompt}

Write a complete, publish-ready {page_type} following these rules:
- H1 must contain the primary keyword
- Include all secondary keywords and LSI terms naturally throughout
- Structure with clear H2 sections that answer the key questions from the brief
- Recommended word count: {word_count} words
- Match the search intent: {search_intent}
- Include a strong CTA section at the end
- Write a suggested title tag (50–60 chars) and meta description (140–160 chars) at the top

Format the output as:
**Title Tag:** [your suggested title]
**Meta Description:** [your suggested meta description]

---

[Full page copy with headings in markdown format]

Write in a professional but approachable tone. Be specific — include relevant details \
for this type of page. Avoid generic filler content."""


async def run(
    mode: str,
    page_type: str,
    # Review mode
    original_copy: str = "",
    target_keyword: str = "",
    analysis: str = "",
    # Build mode
    prompt: str = "",
    keyword_data: dict = None,
    keyword_brief: str = "",
    audit_context: str = "",
    api_key: str = "",
):
    """
    Stream the copywritten output.
    mode: "review" | "build"
    Yields: ("chunk", str) then ("done", None) or ("error", str)
    """
    if keyword_data is None:
        keyword_data = {}

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    if mode == "review":
        full_prompt = REWRITE_PROMPT.format(
            page_type=page_type or "General page",
            target_keyword=target_keyword or "not specified",
            original_copy=original_copy,
            analysis=analysis,
        )
    else:
        import json as _json
        brief_str = keyword_brief or _json.dumps(keyword_data, indent=2)
        audit_context_section = ""
        if audit_context.strip():
            audit_context_section = f"SEO Audit context:\n{audit_context}\n"

        full_prompt = BUILD_PROMPT.format(
            page_type=page_type or "service page",
            keyword_brief=brief_str,
            audit_context_section=audit_context_section,
            prompt=prompt,
            word_count=keyword_data.get("recommended_word_count", 800),
            search_intent=keyword_data.get("search_intent", "transactional"),
        )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=COPYWRITER_SYSTEM_PROMPT,
                    temperature=0.5,
                ),
            ):
                if chunk.text:
                    result_queue.put(("chunk", chunk.text))
            result_queue.put(("done", None))
        except Exception as exc:
            result_queue.put(("error", str(exc)))

    loop = asyncio.get_event_loop()
    thread = threading.Thread(target=_run_sync, daemon=True)
    thread.start()

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=120)
            )
        except queue.Empty:
            yield ("error", "Copywriter timed out")
            return

        if kind == "chunk":
            yield ("chunk", value)
        elif kind == "done":
            yield ("done", None)
            return
        elif kind == "error":
            yield ("error", value)
            return
