"""PRISM tracing shim. In prism-nicrron every model call goes through the repo-root call_llm(), which
already sends a redacted trace to PRISM. So this module only keeps the old names (handler, callbacks,
session, close) and remembers the current request's session id, which backend/llm.py passes on to
call_llm() so one user request shows as one PRISM session. Nothing here imports prismtrace or langchain.
"""
import contextlib
import contextvars
import os

from backend._env import load_env

load_env()

_needed = ("PRISMTRACE_PROJECT_ID", "PRISMTRACE_API_KEY")


class _RootTracer:
    """Truthy marker: tracing is on (done by the root call_llm). Keeps `prism_session_id` in replies."""

    def close(self):
        pass


handler = _RootTracer() if all(os.environ.get(k) for k in _needed) else None

_SID: contextvars.ContextVar = contextvars.ContextVar("callisto_session_id", default=None)
_last_sid = None  # fallback for worker threads that do not copy the context (council pool)


def callbacks() -> list:
    """Kept for the old call sites (config={"callbacks": ...}). The root call_llm traces instead."""
    return []


@contextlib.contextmanager
def session(session_id: str):
    """Group one user request's model calls into one PRISM session: `with session(id): ...`"""
    global _last_sid
    token = _SID.set(session_id)
    _last_sid = session_id
    try:
        yield
    finally:
        _SID.reset(token)


def current_session():
    return _SID.get() or _last_sid


def close():
    pass
