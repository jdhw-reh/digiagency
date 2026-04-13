"""
Shared Gemini streaming helper with automatic retry on transient errors.

All agents call stream_with_retry() inside their _stream_to_queue / _run_sync
thread function instead of calling generate_content_stream directly.
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

_MAX_RETRIES = 3
_BASE_DELAY_SECS = 2  # delay doubles each attempt: 2 s → 4 s


def stream_with_retry(client, model, contents, config, result_queue, parts_list=None):
    """
    Call client.models.generate_content_stream with automatic retry on transient
    503 / overloaded / rate-limit errors.

    Puts tuples onto result_queue:
      ("chunk", text)  — for each streamed text chunk
      ("done", None)   — when the stream completes successfully
      ("error", str)   — on non-retryable failure (also followed by ("done", None))

    If parts_list is provided, each chunk text is also appended to it.
    Only call this from a non-async thread (i.e. a threading.Thread target).
    """
    last_error = None
    for attempt in range(_MAX_RETRIES):
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
            return  # success
        except Exception as exc:
            last_error = str(exc)
            retryable = any(k in last_error.lower() for k in _RETRYABLE)
            if retryable and not chunks_sent and attempt < _MAX_RETRIES - 1:
                time.sleep(_BASE_DELAY_SECS * (attempt + 1))  # 2 s, then 4 s
                continue
            break

    result_queue.put(("error", last_error or "Unknown error"))
    result_queue.put(("done", None))
