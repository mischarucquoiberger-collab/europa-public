"""A report job's live events as server-sent events.

Ported from the original product's GET /stream/{job_id} handler (app/main.py) and its
keepalive wrapper (app/sse.py): every retained event of the job is sent once, in order, as
`event: {type}` / `data: {json}`; a `: keepalive` comment goes out after `keepalive_seconds`
without output (proxies cut silent responses after about 100 s); the stream ends with
`event: done` and the job's status once it is complete, warning or error, with `event: error`
for an unknown job, and after `max_seconds` (the original's wall-clock cap) so a wedged job
never pins a connection. The cursor is absolute (job.event_offset + index), so a reader that
falls behind the 200-event window resumes at the oldest retained event.

`stream` is the plain iterator; `astream` is the same loop for the HTTP route, sleeping
without holding a worker thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator, Iterator

from backend import contract

log = logging.getLogger(__name__)

KEEPALIVE = ": keepalive\n\n"
MAX_SECONDS = 600.0
_TYPE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def format_event(type: str, data: dict) -> str:
    """One SSE message. An event type outside [A-Za-z0-9_.-] becomes "message"."""
    name = type if isinstance(type, str) and _TYPE_RE.fullmatch(type) else "message"
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


class _Cursor:
    def __init__(self, job_id: str, registry):
        self.job_id = job_id
        self.registry = registry
        self.next_index: int | None = None

    def poll(self) -> tuple[list[str], bool]:
        """(messages to send now, whether the stream is over)."""
        try:
            job = self.registry.get(self.job_id)
        except Exception:
            log.exception("stream %s: the job could not be read", self.job_id)
            return [format_event("error", {"message": "The report status is unavailable."})], True
        if job is None:
            return [format_event("error", {"message": "Job not found."}),
                    format_event("done", {"status": "error", "html_file": None, "error": "Job not found."})], True
        start = int(job.event_offset or 0)
        if self.next_index is None:
            self.next_index = start
        retained = list(job.events or [])
        fresh = retained[max(0, self.next_index - start):]
        self.next_index = start + len(retained)
        out = [format_event(ev.get("type"), ev) for ev in fresh if isinstance(ev, dict)]
        if job.status in contract.TERMINAL:
            out.append(format_event("done", {"status": job.status, "html_file": job.html_file,
                                             "error": job.error}))
            return out, True
        return out, False


def _timeout() -> str:
    return format_event("error", {"message": "The stream timed out; reconnect to continue."})


def stream(job_id: str, registry, *, poll_seconds: float = 0.5, keepalive_seconds: float = 15,
           max_seconds: float | None = MAX_SECONDS) -> Iterator[str]:
    cursor = _Cursor(job_id, registry)
    began = last_sent = time.monotonic()
    while True:
        chunks, over = cursor.poll()
        yield from chunks
        now = time.monotonic()
        if chunks:
            last_sent = now
        if over:
            return
        if max_seconds is not None and now - began >= max_seconds:
            yield _timeout()
            return
        if now - last_sent >= keepalive_seconds:
            yield KEEPALIVE
            last_sent = now
        time.sleep(poll_seconds)


async def astream(job_id: str, registry, *, poll_seconds: float = 0.5, keepalive_seconds: float = 15,
                  max_seconds: float | None = MAX_SECONDS) -> AsyncIterator[str]:
    from starlette.concurrency import run_in_threadpool

    cursor = _Cursor(job_id, registry)
    began = last_sent = time.monotonic()
    while True:
        chunks, over = await run_in_threadpool(cursor.poll)
        for chunk in chunks:
            yield chunk
        now = time.monotonic()
        if chunks:
            last_sent = now
        if over:
            return
        if max_seconds is not None and now - began >= max_seconds:
            yield _timeout()
            return
        if now - last_sent >= keepalive_seconds:
            yield KEEPALIVE
            last_sent = now
        await asyncio.sleep(poll_seconds)
