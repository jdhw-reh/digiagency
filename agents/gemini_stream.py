"""
Shared Gemini streaming helper with automatic retry and model fallback.

All agents call stream_with_retry() inside their _stream_to_queue / _run_sync
thread function instead of calling generate_content_stream directly.

Retry strategy:
  1. Try the primary model (gemini-2.5-flash) up to _MAX_RETRIES times
     with exponential backoff on 503/overloaded/rate-limit errors.
  2. If all primary retries fail, automatically fall back to gemini-2.0-flash
     (the stable high-availability model) with its own retry window.
"""

import time

# Error substrings that indicate a transient server-side failure worth retrying.
_RETRYABLE = (
    "503",
    "unavailable",
    "overloaded",
    "resource_exhausted",
    "resource exhausted",
    "429",
    "rate limit",
)

_MAX_RETRIES = 4        # attempts per model
_BASE_DELAY_SECS = 3    # delay per attempt: 3 s → 6 s → 9 s → 12 s
_FALLBACK_MODEL = "gemini-2.0-flash"


def _try_model(client, model, contents, config, result_queue, parts_list, max_retries):
    """
    Attempt to stream from a single model with retry.
    Returns True on success, False if all retries failed with a retryable error,
    or raises immediately on a non-retryable error.
    """
    for attempt in range(max_retries):
        chunks_sent = False
        try:
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    chunks_sent = True
                    result_queue.put(("chunk", chunk.text))
                    if parts_list is not None:
                        parts_list.append(chunk.text)
            result_queue.put(("done", None))
            return True  # success
        except Exception as exc:
            error_str = str(exc)
            retryable = any(k in error_str.lower() for k in _RETRYABLE)
            if retryable and not chunks_sent and attempt < max_retries - 1:
                time.sleep(_BASE_DELAY_SECS * (attempt + 1))
                continue
            if retryable and not chunks_sent:
                # Exhausted retries on a retryable error — signal caller to try fallback
                return False
            # Non-retryable or chunks already sent — surface error immediately
            result_queue.put(("error", error_str))
            result_queue.put(("done", None))
            return True  # "handled" — don't double-emit error


def stream_with_retry(client, model, contents, config, result_queue, parts_list=None):
    """
    Call client.models.generate_content_stream with automatic retry on transient
    503 / overloaded / rate-limit errors, then fall back to gemini-2.0-flash if
    the primary model (usually gemini-2.5-flash) is persistently unavailable.

    Puts tuples onto result_queue:
      ("chunk", text)  — for each streamed text chunk
      ("done", None)   — when the stream completes successfully
      ("error", str)   — on non-retryable failure (also followed by ("done", None))

    If parts_list is provided, each chunk text is also appended to it.
    Only call this from a non-async thread (i.e. a threading.Thread target).
    """
    # Phase 1: try the requested model
    success = _try_model(client, model, contents, config, result_queue, parts_list, _MAX_RETRIES)
    if success:
        return

    # Phase 2: primary model exhausted — try fallback model
    fallback = _FALLBACK_MODEL
    if model == fallback:
        # Already on the fallback model, nothing left to try
        result_queue.put(("error", f"Gemini ({model}) is temporarily unavailable. Please try again in a moment."))
        result_queue.put(("done", None))
        return

    success = _try_model(client, fallback, contents, config, result_queue, parts_list, _MAX_RETRIES)
    if not success:
        result_queue.put(("error", "Gemini is temporarily unavailable. Please try again in a moment."))
        result_queue.put(("done", None))
