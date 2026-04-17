"""
Prompt injection defence utilities for user-controlled inputs.

Two public functions:

sanitise_user_input(text, user_id=None) -> str
    Strips, removes control chars, truncates, XML-escapes angle brackets,
    wraps in a [USER_INPUT_START]/[USER_INPUT_END] delimiter block, and
    logs a warning when suspicious injection patterns are detected.

validate_url(url) -> str
    Checks the URL has an http or https scheme; raises HTTPException(422)
    for javascript:, file:, data:, or any other scheme.
"""

import logging
import re
from urllib.parse import urlparse

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Maximum number of characters accepted from any single user input field.
MAX_INPUT_LENGTH = 2000

# Substrings that suggest a prompt-injection attempt (case-insensitive).
_SUSPICIOUS_PATTERNS = [
    "ignore previous",
    "ignore your",
    "disregard",
    "instead of the above",
    "new instructions",
    "you are now",
    "act as",
    "jailbreak",
    "system prompt",
]

# Matches non-printable control characters while preserving standard whitespace
# (space 0x20, tab 0x09, LF 0x0A, CR 0x0D, FF 0x0C, VT 0x0B).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def sanitise_user_input(text: str, user_id: str | None = None) -> str:
    """
    Sanitise a user-supplied string before it is interpolated into a Gemini prompt.

    Steps applied in order:
    1. Cast to str and strip leading/trailing whitespace.
    2. Remove null bytes (0x0B is vertical-tab / kept, 0x0C form-feed / kept).
       Specifically removes: 0x00–0x08, 0x0E–0x1F, 0x7F.
    3. Truncate to MAX_INPUT_LENGTH characters.
    4. XML-escape & < > so any HTML/XML markup is inert.
    5. Wrap in a clearly labelled delimiter block to signal that the content
       is data, not instruction.
    6. Log a warning (never block) if a suspicious injection substring is found;
       records user_id and the matched term.
    """
    if not isinstance(text, str):
        text = str(text)

    # 1 — strip
    text = text.strip()

    # 2 — remove non-printable control chars (null bytes and friends)
    text = _CONTROL_CHAR_RE.sub("", text)
    text = text.replace("\x00", "")  # belt-and-braces null-byte removal

    # 3 — truncate
    if len(text) > MAX_INPUT_LENGTH:
        text = text[:MAX_INPUT_LENGTH]

    # 4 — XML-escape angle brackets (& must be escaped first)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 5 — check for suspicious patterns before wrapping
    lower = text.lower()
    for pattern in _SUSPICIOUS_PATTERNS:
        if pattern in lower:
            logger.warning(
                "Possible prompt injection | user_id=%s | matched=%r | excerpt=%.120r",
                user_id or "unknown",
                pattern,
                text,
            )
            break  # one warning per call is sufficient

    # 6 — wrap in delimiter block
    return f"[USER_INPUT_START]\n{text}\n[USER_INPUT_END]"


def validate_url(url: str) -> str:
    """
    Validate that *url* uses an http or https scheme.

    Raises HTTPException(422) for javascript:, file:, data:, ftp:, or any
    other scheme that is not http/https.  Returns the stripped URL on success.

    Note: this function does NOT wrap the URL in USER_INPUT tags because several
    agents also use the URL to make live HTTP requests (e.g. the SEO auditor's
    technical crawl).  Scheme validation is the correct defence for URL fields;
    prompt-injection via a URL path is negligible compared to scheme abuse.
    """
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=422,
            detail="Invalid URL: only http and https schemes are accepted.",
        )
    return url
