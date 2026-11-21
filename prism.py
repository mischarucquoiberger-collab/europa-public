"""Manual PRISM sender: one POST /api/traces per call, already redacted.

No SDK, no auto-instrumentation, no proxy. A failure here is swallowed: it can
never raise into the app and never adds latency (the POST runs on a daemon thread
with a short timeout).
"""
import atexit
import json
import sys
import threading
import urllib.error
import urllib.request

import config

_threads: list[threading.Thread] = []
_lock = threading.Lock()
last_sent: dict | None = None  # {"url", "body" (exact JSON string), "status"} for the most recent trace


def _warn(msg: str) -> None:
    try:
        print(f"[prism] {msg}", file=sys.stderr)
    except Exception:
        pass


def _post(body: str, record: dict) -> None:
    try:
        request = urllib.request.Request(
            record["url"],
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-PRISMtrace-Key": config.secret("PRISMTRACE_API_KEY"),
            },
        )
        with urllib.request.urlopen(request, timeout=config.PRISM_TIMEOUT_S) as response:
            record["status"] = response.status
    except urllib.error.HTTPError as exc:
        record["status"] = exc.code
        _warn(f"ingest answered {exc.code}")
    except Exception as exc:  # timeout, DNS, refused, anything
        record["status"] = f"failed: {type(exc).__name__}"
        _warn(f"ingest failed ({type(exc).__name__}); the app continues")


def send_trace(payload: dict) -> None:
    """Send one already-redacted payload. Never raises."""
    global last_sent
    try:
        if not config.PRISM_ENABLED:
            return
        if not config.secret("PRISMTRACE_API_KEY") or not payload.get("project_id"):
            _warn("PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID not set; trace not sent")
            last_sent = {"url": None, "body": json.dumps(payload, ensure_ascii=False, indent=2), "status": "not sent: keys missing"}
            return
        body = json.dumps(payload, ensure_ascii=False)
        record = {"url": config.PRISMTRACE_HOST + "/api/traces", "body": body, "status": "pending"}
        last_sent = record
        thread = threading.Thread(target=_post, args=(body, record), daemon=True)
        with _lock:
            _threads[:] = [t for t in _threads if t.is_alive()]
            _threads.append(thread)
        thread.start()
    except Exception as exc:
        _warn(f"trace skipped ({type(exc).__name__}); the app continues")


def flush(timeout: float | None = None) -> None:
    """Wait (bounded) for in-flight traces, e.g. before the process exits. Never raises."""
    try:
        with _lock:
            pending = list(_threads)
        for thread in pending:
            thread.join(timeout if timeout is not None else config.PRISM_TIMEOUT_S + 0.5)
    except Exception:
        pass


atexit.register(flush)
