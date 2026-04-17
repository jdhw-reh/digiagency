"""
Personal Assistant agent: uses Gemini 2.5 Flash for multi-turn conversation.

Capabilities:
- Google Search grounding (cites sources in replies)
- File understanding: images, PDFs, documents via Gemini File API
- Multi-turn conversation with rolling 40-message window

Same thread+queue streaming pattern as all other agents.
"""

import asyncio
import os
import queue
import threading

from google import genai
from google.genai import types
from agents.gemini_stream import stream_with_retry
from utils.prompts import get_system_prompt


async def run(
    conversation_history: list[dict],
    activity_context: str | None = None,
    file_refs: list[dict] | None = None,
    api_key: str = "",
):
    """
    Async generator yielding str text chunks.

    conversation_history: list of {role: "user"|"model", content: "..."} dicts.
    file_refs: list of {uri, mime_type, display_name} dicts for attached files.
    Sends the last 40 messages to Gemini.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY", ""))

    # Rolling window — keep last 40 messages
    window = conversation_history[-40:]

    # Prepend activity context as the first user turn if provided
    if activity_context:
        context_message = {
            "role": "user",
            "content": (
                "[Agency activity log — read silently, do not mention unless asked]\n"
                + activity_context
            ),
        }
        window = [context_message] + window

    # Build Gemini multi-turn contents
    # For the last user message, attach any uploaded files as parts
    contents = []
    for i, item in enumerate(window):
        is_last = i == len(window) - 1
        if is_last and item["role"] == "user" and file_refs:
            parts = [
                types.Part(
                    file_data=types.FileData(
                        file_uri=ref["uri"],
                        mime_type=ref["mime_type"],
                    )
                )
                for ref in file_refs
            ]
            parts.append(types.Part(text=item["content"]))
            contents.append(types.Content(role="user", parts=parts))
        else:
            contents.append(
                types.Content(
                    role=item["role"],
                    parts=[types.Part(text=item["content"])],
                )
            )

    text_queue: queue.Queue = queue.Queue()

    def _stream_to_queue():
        stream_with_retry(
            client,
            "gemini-2.5-flash",
            contents,
            types.GenerateContentConfig(
                system_instruction=get_system_prompt("assistant/assistant"),
                temperature=0.6,
            ),
            text_queue,
        )

    threading.Thread(target=_stream_to_queue, daemon=True).start()

    while True:
        try:
            msg_type, value = text_queue.get(timeout=0.05)
        except queue.Empty:
            await asyncio.sleep(0.01)
            continue

        if msg_type == "chunk":
            yield value
        elif msg_type == "error":
            yield {"type": "error", "message": value}
            break
        elif msg_type == "done":
            break
