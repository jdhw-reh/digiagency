"""
SEO Auditor agent: crawls the target URL for technical signals, then uses
Gemini 2.5 Flash with Google Search grounding to audit competitive visibility.

Phase 1 — Technical crawl (httpx + BeautifulSoup):
  Fetches the homepage and extracts on-page signals without calling the LLM.

Phase 2 — Competitive audit (Gemini + Google Search):
  Uses real-time search to assess rankings, gaps, and competitors, with full
  awareness of the technical findings from Phase 1.
"""

import asyncio
import json
import os
import queue
import re
import threading

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

AUDITOR_SYSTEM_PROMPT = """You are a senior technical SEO consultant with 15 years of experience. \
You audit websites for SEO performance and identify concrete opportunities for improvement.

You have access to real-time Google Search AND a pre-crawled technical report of the site. \
Use both to produce a complete, evidence-based audit.

Use Google Search to:
1. Check what the target domain currently ranks for
2. Identify what competitors rank for that the target doesn't
3. Find keyword gaps and missed opportunities
4. Assess the competitive landscape in the niche

Be specific and ground every observation in actual findings — not assumptions.

You are part of Digi Agency — an AI marketing platform. Never refer to yourself or this platform by any other name."""

AUDITOR_PROMPT = """Audit this website for SEO performance:

URL: {url}
Business context: {context}
Detected CMS: {cms}

--- TECHNICAL CRAWL RESULTS ---
{technical_summary}
--- END TECHNICAL CRAWL ---

Now conduct a live competitive audit using Google Search. Investigate:
1. What does this domain currently rank for? Search brand name and key service terms.
2. What are their top 3–5 competitors ranking for that they're missing?
3. What high-value keywords in this niche have low-to-medium competition?
4. Are there obvious content gaps or quick wins based on the technical issues above?

Write a 4–5 paragraph audit commentary covering both the technical findings and \
competitive landscape. Reference specific issues from the crawl where relevant.

Then output your structured findings as JSON enclosed in <audit_data> and </audit_data> tags:

<audit_data>
{{
  "domain": "example.com",
  "cms": "{cms}",
  "technical_score": 7,
  "technical_issues": [
    {{"issue": "Missing meta description", "severity": "high"}},
    {{"issue": "No schema markup detected", "severity": "medium"}}
  ],
  "technical_signals": {{
    "title": "Page title here",
    "title_length": 45,
    "meta_description": "Description here or null",
    "meta_description_length": 120,
    "h1_count": 1,
    "h1_texts": ["Main heading"],
    "h2_count": 4,
    "canonical": "https://example.com/",
    "robots_meta": "index, follow",
    "schema_types": ["Organization"],
    "og_title": "OG title or null",
    "images_missing_alt": 3,
    "total_images": 12,
    "internal_links": 24,
    "external_links": 5,
    "https": true,
    "has_viewport": true,
    "word_count_estimate": 450
  }},
  "target_keywords": ["kw1", "kw2"],
  "missing_keywords": ["kw3", "kw4"],
  "top_competitors": ["competitor1.com", "competitor2.com"],
  "authority_gaps": ["topic area 1", "topic area 2"],
  "quick_wins": ["specific action 1", "specific action 2", "specific action 3"]
}}
</audit_data>"""


# ---------------------------------------------------------------------------
# Phase 1 — Technical crawl
# ---------------------------------------------------------------------------

def _detect_cms(soup: BeautifulSoup, html: str) -> str:
    """Detect the CMS from HTML signals."""
    if "/wp-content/" in html or "/wp-includes/" in html:
        return "WordPress"
    generator = soup.find("meta", attrs={"name": "generator"})
    if generator:
        content = generator.get("content", "").lower()
        if "wordpress" in content:
            return "WordPress"
        if "wix" in content:
            return "Wix"
        if "squarespace" in content:
            return "Squarespace"
        if "shopify" in content:
            return "Shopify"
        if "webflow" in content:
            return "Webflow"
        if "drupal" in content:
            return "Drupal"
        if "joomla" in content:
            return "Joomla"
    if "shopify" in html.lower() and "cdn.shopify.com" in html:
        return "Shopify"
    if "squarespace" in html.lower():
        return "Squarespace"
    return "Unknown"


def _crawl_url(url: str) -> dict:
    """
    Fetch the URL and extract technical SEO signals.
    Returns a dict of signals + a plain-text summary.
    """
    signals = {}
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SEOAuditBot/1.0)"},
        )
        final_url = str(resp.url)
        signals["https"] = final_url.startswith("https://")

        soup = BeautifulSoup(resp.text, "lxml")
        html = resp.text

        # CMS detection
        signals["cms"] = _detect_cms(soup, html)

        # Title
        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else None
        signals["title"] = title_text
        signals["title_length"] = len(title_text) if title_text else 0

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        desc_content = meta_desc.get("content", "").strip() if meta_desc else None
        signals["meta_description"] = desc_content if desc_content else None
        signals["meta_description_length"] = len(desc_content) if desc_content else 0

        # Headings
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        signals["h1_count"] = len(h1_tags)
        signals["h1_texts"] = [h.get_text(strip=True)[:80] for h in h1_tags[:3]]
        signals["h2_count"] = len(h2_tags)

        # Canonical
        canonical = soup.find("link", attrs={"rel": "canonical"})
        signals["canonical"] = canonical.get("href") if canonical else None

        # Robots meta
        robots_meta = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        signals["robots_meta"] = robots_meta.get("content") if robots_meta else "not set"

        # Open Graph
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        signals["og_title"] = og_title.get("content") if og_title else None
        signals["og_description"] = og_desc.get("content") if og_desc else None

        # Schema markup
        schema_scripts = soup.find_all("script", type="application/ld+json")
        schema_types = []
        for s in schema_scripts:
            try:
                data = json.loads(s.string or "")
                if isinstance(data, dict):
                    t = data.get("@type")
                    if t:
                        schema_types.append(t if isinstance(t, str) else str(t))
                elif isinstance(data, list):
                    for item in data:
                        t = item.get("@type") if isinstance(item, dict) else None
                        if t:
                            schema_types.append(t)
            except (json.JSONDecodeError, AttributeError):
                pass
        signals["schema_types"] = schema_types

        # Viewport
        viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        signals["has_viewport"] = viewport is not None

        # Images
        images = soup.find_all("img")
        missing_alt = sum(1 for img in images if not img.get("alt", "").strip())
        signals["total_images"] = len(images)
        signals["images_missing_alt"] = missing_alt

        # Links
        from urllib.parse import urlparse
        base_domain = urlparse(final_url).netloc
        all_links = soup.find_all("a", href=True)
        internal = sum(
            1 for a in all_links
            if urlparse(a["href"]).netloc in ("", base_domain)
        )
        signals["internal_links"] = internal
        signals["external_links"] = len(all_links) - internal

        # Word count estimate (body text)
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        body_text = soup.get_text(separator=" ", strip=True)
        signals["word_count_estimate"] = len(body_text.split())

        signals["crawl_error"] = None

    except Exception as exc:
        signals["crawl_error"] = str(exc)
        signals.setdefault("cms", "Unknown")
        signals.setdefault("https", url.startswith("https://"))

    return signals


def _build_technical_summary(signals: dict) -> str:
    """Convert raw signals dict into a readable summary for the LLM."""
    if signals.get("crawl_error"):
        return f"Crawl failed: {signals['crawl_error']}"

    issues = []
    if not signals.get("title"):
        issues.append("MISSING title tag")
    elif signals.get("title_length", 0) > 60:
        issues.append(f"Title too long ({signals['title_length']} chars — ideal ≤60): \"{signals['title']}\"")
    elif signals.get("title_length", 0) < 30:
        issues.append(f"Title too short ({signals['title_length']} chars): \"{signals['title']}\"")
    else:
        issues.append(f"Title OK ({signals['title_length']} chars): \"{signals['title']}\"")

    if not signals.get("meta_description"):
        issues.append("MISSING meta description")
    elif signals.get("meta_description_length", 0) > 160:
        issues.append(f"Meta description too long ({signals['meta_description_length']} chars — ideal ≤160)")
    elif signals.get("meta_description_length", 0) < 70:
        issues.append(f"Meta description too short ({signals['meta_description_length']} chars)")
    else:
        issues.append(f"Meta description OK ({signals['meta_description_length']} chars)")

    h1 = signals.get("h1_count", 0)
    if h1 == 0:
        issues.append("MISSING H1 tag")
    elif h1 > 1:
        issues.append(f"Multiple H1 tags ({h1}) — should be exactly 1")
    else:
        h1_texts = signals.get("h1_texts", [])
        issues.append(f"H1 OK: \"{h1_texts[0] if h1_texts else ''}\"")

    issues.append(f"H2 tags: {signals.get('h2_count', 0)}")

    if not signals.get("canonical"):
        issues.append("No canonical tag set")
    else:
        issues.append(f"Canonical: {signals['canonical']}")

    schema = signals.get("schema_types", [])
    if not schema:
        issues.append("No JSON-LD schema markup detected")
    else:
        issues.append(f"Schema markup present: {', '.join(schema)}")

    if not signals.get("og_title"):
        issues.append("Missing Open Graph tags (og:title, og:description)")
    else:
        issues.append("Open Graph tags present")

    missing_alt = signals.get("images_missing_alt", 0)
    total_imgs = signals.get("total_images", 0)
    if missing_alt > 0:
        issues.append(f"{missing_alt} of {total_imgs} images missing alt text")
    elif total_imgs > 0:
        issues.append(f"All {total_imgs} images have alt text")

    issues.append(f"HTTPS: {'Yes' if signals.get('https') else 'NO — site is HTTP only'}")
    issues.append(f"Mobile viewport tag: {'Present' if signals.get('has_viewport') else 'MISSING'}")
    issues.append(f"Internal links: {signals.get('internal_links', 0)} | External links: {signals.get('external_links', 0)}")
    issues.append(f"Estimated word count (homepage): {signals.get('word_count_estimate', 0)}")
    issues.append(f"Detected CMS: {signals.get('cms', 'Unknown')}")
    issues.append(f"robots meta: {signals.get('robots_meta', 'not set')}")

    return "\n".join(f"- {i}" for i in issues)


# ---------------------------------------------------------------------------
# Phase 2 — LLM competitive audit
# ---------------------------------------------------------------------------

async def run(url: str, context: str, api_key: str = ""):
    """
    Stream the SEO audit.
    Yields: ("technical_signals", dict), ("chunk", str), ("audit_data", dict)
    """
    # Phase 1 — crawl (blocking, run in thread)
    loop = asyncio.get_event_loop()
    signals = await loop.run_in_executor(None, _crawl_url, url)

    # Emit technical signals immediately so the UI can show the score
    yield ("technical_signals", signals)

    cms = signals.get("cms", "Unknown")
    technical_summary = _build_technical_summary(signals)

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    prompt = AUDITOR_PROMPT.format(
        url=url,
        context=context,
        cms=cms,
        technical_summary=technical_summary,
    )

    result_queue: queue.Queue = queue.Queue()

    def _run_sync():
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=AUDITOR_SYSTEM_PROMPT,
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

    full_text = ""

    while True:
        try:
            kind, value = await loop.run_in_executor(
                None, lambda: result_queue.get(timeout=90)
            )
        except queue.Empty:
            yield ("error", "Auditor timed out")
            return

        if kind == "chunk":
            full_text += value
            yield ("chunk", value)
        elif kind == "done":
            audit_data = {}
            match = re.search(r"<audit_data>(.*?)</audit_data>", full_text, re.DOTALL)
            if match:
                try:
                    audit_data = json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass
            # Merge crawled technical signals into audit_data
            if "technical_signals" not in audit_data:
                audit_data["technical_signals"] = signals
            audit_data.setdefault("cms", cms)
            yield ("audit_data", audit_data)
            return
        elif kind == "error":
            yield ("error", value)
            return
