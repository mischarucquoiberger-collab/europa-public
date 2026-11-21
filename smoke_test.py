"""PRISM-only smoke test. Makes NO model call (no Nicrron, no credits).

Sends two clearly labelled traces through the normal redact() -> prism.send_trace()
path under one session you can search for in the PRISM dashboard.

    python3 smoke_test.py
"""
import json
import sys
import time

import config
import prism
from redact import redact

MODEL_LABEL = "smoke-test (no model call)"

TURNS = [
    ("SMOKE TEST turn 1. Fake details: email jane.doe@example.com, phone +1 (415) 555-0132.",
     "SMOKE TEST reply 1 (canned text, not from a model)."),
    ("SMOKE TEST turn 2. Fake key sk-test-9f8e7d6c5b4a39281706f5e4, fake order 123456789012.",
     "SMOKE TEST reply 2 (canned text, not from a model)."),
]


def main() -> int:
    session_id = "smoke-" + time.strftime("%Y%m%d-%H%M%S")
    messages = [{"role": "system", "content": "Smoke test system prompt (hidden in PRISM)."}]
    statuses = []
    for user_text, canned_reply in TURNS:
        messages.append({"role": "user", "content": user_text})
        payload = redact(messages, canned_reply, model=MODEL_LABEL, session_id=session_id,
                         agent_id=config.AGENT_ID, project_id=config.secret("PRISMTRACE_PROJECT_ID"))
        prism.send_trace(payload)
        prism.flush()
        statuses.append(prism.last_sent["status"] if prism.last_sent else "nothing sent")
        messages.append({"role": "assistant", "content": canned_reply})

    print("Search PRISM for this session id:", session_id)
    print("Agent:", config.AGENT_ID, "| model label:", MODEL_LABEL)
    print("PRISM response per trace:", statuses)
    print("\nLast body sent:")
    print(json.dumps(json.loads(prism.last_sent["body"]), ensure_ascii=False, indent=2))
    ok = all(s == 200 for s in statuses)
    print("\nSMOKE TEST", "PASSED — both traces stored by PRISM." if ok else "FAILED — see statuses above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
