"""The one door to the model for the backend.

Every backend model call goes through `ask` (or `ask_json`), which calls `llm.call_llm` under one
process-wide gate: all report jobs together never run more than `settings.MODEL_CONCURRENCY`
model calls at the same time, however many branches and readers ask at once. A call that fails
with HTTP 429, HTTP 5xx or "unreachable" is tried again twice (after 2 s, then 5 s, through the
injected `sleep`, with the gate released while waiting); any other failure is raised at once.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable

import llm
from backend import settings

RETRY_PAUSES = (2.0, 5.0)

_RETRYABLE = re.compile(r"HTTP (?:429|5\d\d)|unreachable", re.IGNORECASE)
_GATE = threading.BoundedSemaphore(max(1, int(settings.MODEL_CONCURRENCY)))
_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)```", re.DOTALL)
_OPEN_TO_CLOSE = {"[": "]", "{": "}"}


def retryable(exc: BaseException) -> bool:
    """True for a model failure worth another try: HTTP 429, HTTP 5xx or unreachable."""
    return isinstance(exc, llm.LLMError) and bool(_RETRYABLE.search(str(exc)))


def ask(messages: list[dict], *, session_id: str, sleep: Callable[[float], None] = time.sleep,
        **params) -> str:
    """The model's reply text ("" for an empty reply). Raises llm.LLMError when the model failed
    (after the retries, for a retryable failure)."""
    attempt = 0
    while True:
        try:
            with _GATE:
                reply = llm.call_llm(messages, session_id=session_id, **params)
        except llm.LLMError as exc:
            if attempt < len(RETRY_PAUSES) and retryable(exc):
                sleep(RETRY_PAUSES[attempt])     # outside the gate: a waiting call holds no slot
                attempt += 1
                continue
            raise
        if reply is None:
            return ""
        return reply if isinstance(reply, str) else str(reply)


def ask_json(messages: list[dict], *, session_id: str, sleep: Callable[[float], None] = time.sleep,
             **params) -> list | dict | None:
    """`ask`, then the reply parsed as JSON: a list or an object, or None when the reply holds
    neither. Model failures are raised as by `ask`."""
    return parse_json(ask(messages, session_id=session_id, sleep=sleep, **params))


def parse_json(text) -> list | dict | None:
    """A JSON array or object from a model reply, defensively: the whole reply, else the inside of
    a ```json fence, else the first balanced [...] or {...} that parses. None when none does."""
    if not isinstance(text, str) or not text.strip():
        return None
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for candidate in candidates:
        try:
            value = json.loads(candidate.strip())
        except ValueError:
            continue
        if isinstance(value, (list, dict)):
            return value
    for candidate in candidates:
        value = _first_balanced(candidate)
        if value is not None:
            return value
    return None


def _first_balanced(text: str) -> list | dict | None:
    for start, ch in enumerate(text):
        if ch not in _OPEN_TO_CLOSE:
            continue
        end = _balanced_end(text, start)
        if end is None:
            continue
        try:
            value = json.loads(text[start:end + 1])
        except ValueError:
            continue
        if isinstance(value, (list, dict)):
            return value
    return None


def _balanced_end(text: str, start: int) -> int | None:
    """Index of the bracket that closes the one at `start` (strings and escapes respected), or
    None when it is never closed or closed by the wrong kind."""
    stack: list[str] = []
    in_string = escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _OPEN_TO_CLOSE:
            stack.append(_OPEN_TO_CLOSE[ch])
        elif ch in "]}":
            if not stack or stack.pop() != ch:
                return None
            if not stack:
                return i
    return None
