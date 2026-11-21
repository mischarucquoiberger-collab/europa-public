"""The two PRISM verify checks from the integration brief. Prints results, never the key.

    python3 verify.py
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import config


def _call(method: str, url: str, body: dict | None = None):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", "X-PRISMtrace-Key": config.secret("PRISMTRACE_API_KEY")},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return None, type(exc).__name__


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def main() -> int:
    key, project = config.secret("PRISMTRACE_API_KEY"), config.secret("PRISMTRACE_PROJECT_ID")
    missing = [n for n, v in (("PRISMTRACE_API_KEY", key), ("PRISMTRACE_PROJECT_ID", project)) if not v]
    if missing:
        print("CREDENTIAL FAIL — not set in .env:", ", ".join(missing))
        return 1

    print("Check 1: handshake")
    status, text = _call("POST", config.PRISMTRACE_HOST + "/api/setup-doctor/handshake",
                         {"project_id": project, "send_test_trace": True})
    data = _json(text)
    detail = (data or {}).get("detail", text[:300]) if status != 200 else "ok"
    print("  status:", status, "| detail:", detail)
    if status != 200:
        print(f"CREDENTIAL FAIL — {detail}")
        return 1
    print("CREDENTIAL OK")

    print("Check 2: setup doctor")
    status, text = _call("GET", config.PRISMTRACE_HOST + "/api/setup-doctor?project_id=" + urllib.parse.quote(project))
    data = _json(text) or {}
    print("  status:", status)
    for field in ("live_connected", "app_connected", "blocked_step"):
        print(f"  {field}: {data.get(field)}")
    if data.get("app_connected") or data.get("live_connected"):
        print("LIVE CONNECTED — PRISM is receiving live traces from the Nicrron wrapper (llm.call_llm).")
        return 0
    print(f"WAITING FOR LIVE — {data.get('blocked_step')} — run: python3 main.py --once, then this again.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
