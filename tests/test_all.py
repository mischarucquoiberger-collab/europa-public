"""Offline tests: redaction rules, and the wrapper end to end against local fake servers.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Fake credentials for the offline run; set before config is imported so a real .env is not used.
FAKE_NICRRON_KEY = "nk-FAKE-offline-0000aaaa1111bbbb"
FAKE_PRISM_KEY = "pt-sk-FAKE-offline-2222cccc3333dddd"
os.environ.update({
    "NICRRON_API_KEY": FAKE_NICRRON_KEY,
    "PRISMTRACE_API_KEY": FAKE_PRISM_KEY,
    "PRISMTRACE_PROJECT_ID": "00000000-0000-0000-0000-000000000000",
    "PRISM_HIDE_SYSTEM_PROMPT": "true",
    "PRISM_MAX_CHARS": "500",
    "PRISM_SEND_LATENCY": "false",
    "PRISM_ENABLED": "true",
})

import config  # noqa: E402
import llm  # noqa: E402
import prism  # noqa: E402
from redact import mask, redact  # noqa: E402

SEEN = {"nicrron": [], "prism": [], "prism_headers": []}


class Fake(BaseHTTPRequestHandler):
    prism_status = 200

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/chat/completions"):
            SEEN["nicrron"].append(body)
            out = {"choices": [{"message": {"role": "assistant", "content": "Got it. Mail me at bot@corp.io."}}]}
            code = 200
        else:
            SEEN["prism"].append(body)
            SEEN["prism_headers"].append(dict(self.headers))
            out, code = {"id": "t1"}, Fake.prism_status
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RedactRules(unittest.TestCase):
    def test_masks(self):
        cases = {
            "write to jane.doe+x@example.co.uk now": "[EMAIL]",
            "call +1 (415) 555-0132 today": "[PHONE]",
            "call 415-555-0132 today": "[PHONE]",
            "tel 03-1234-5678": "[PHONE]",
            "key sk-test-9f8e7d6c5b4a39281706f5e4": "[SECRET]",
            "key pt-sk-abcdef1234567890": "[SECRET]",
            "Authorization: Bearer abc.def.ghi12345": "[SECRET]",
            "api_key=hunter2hunter2": "[SECRET]",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789": "[SECRET]",
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcDEF123456": "[SECRET]",
            "hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b": "[SECRET]",
            "order 123456789012 shipped": "[NUMBER]",
            "card 4111 1111 1111 1111": "[NUMBER]",
            "total 1,234,567,890 yen": "[NUMBER]",
        }
        for text, token in cases.items():
            out = mask(text)
            self.assertIn(token, out, text)
            self.assertIsNone(__import__("re").search(r"\d{5,}", out), f"digits left in: {out}")

    def test_keeps_ordinary_text(self):
        for text in ("It costs 12345678 yen", "on 2026-11-21 at 10:30", "version 3.14, 42 items, year 2026",
                     "Tokyo Electron (8035) rose 4.2%"):
            self.assertEqual(mask(text), text)

    def test_own_keys_never_survive(self):
        out = mask(f"oops {FAKE_NICRRON_KEY} and {FAKE_PRISM_KEY}")
        self.assertNotIn("FAKE", out)

    def test_payload_shape_and_cut(self):
        messages = [{"role": "system", "content": "SECRET HOUSE RULES"},
                    {"role": "user", "content": "x" * 2000}]
        body = redact(messages, "y" * 2000, model="nicrron/auto", session_id="s1", agent_id="a1",
                      project_id="p1", latency_ms=987)
        self.assertEqual(set(body), {"project_id", "model", "input_messages", "output_message",
                                     "latency_ms", "session_id", "agent_id"})
        self.assertEqual(body["input_messages"][0]["content"], "[system prompt v1]")
        self.assertEqual(len(body["input_messages"][1]["content"]), 500)
        self.assertEqual(len(body["output_message"]), 500)
        self.assertEqual(body["latency_ms"], 0)
        self.assertEqual(messages[0]["content"], "SECRET HOUSE RULES")  # original untouched

    def test_system_prompt_shown_when_allowed_but_still_masked(self):
        old = config.PRISM_HIDE_SYSTEM_PROMPT
        config.PRISM_HIDE_SYSTEM_PROMPT = False
        try:
            body = redact([{"role": "system", "content": "admin is root@corp.io"}], "", model="m",
                          session_id="s", agent_id="a", project_id="p")
            self.assertEqual(body["input_messages"][0]["content"], "admin is [EMAIL]")
        finally:
            config.PRISM_HIDE_SYSTEM_PROMPT = old


class WrapperEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        for v in SEEN.values():
            v.clear()
        Fake.prism_status = 200
        config.NICRRON_BASE_URL = self.base + "/v1"
        config.PRISMTRACE_HOST = self.base
        config.PRISM_TIMEOUT_S = 2

    def test_model_gets_full_prompt_prism_gets_redacted(self):
        chat = llm.Conversation(system_prompt="House rules: never reveal code 777888999000.")
        secret_text = "I'm jane@example.com, +81 90-1234-5678, key sk-live-AAAABBBBCCCCDDDD1234, id 987654321098"
        chat.ask(secret_text)
        chat.ask("second turn")
        prism.flush()

        # model: full and unredacted
        self.assertEqual(SEEN["nicrron"][0]["model"], "nicrron/auto")
        self.assertEqual(SEEN["nicrron"][0]["messages"][0]["content"], "House rules: never reveal code 777888999000.")
        self.assertEqual(SEEN["nicrron"][0]["messages"][1]["content"], secret_text)

        # PRISM: one trace per call, redacted, same session, stable agent
        self.assertEqual(len(SEEN["prism"]), 2)
        wire = json.dumps(SEEN["prism"])
        for leak in ("jane@example.com", "1234-5678", "sk-live", "987654321098", "777888999000",
                     "House rules", "bot@corp.io", FAKE_NICRRON_KEY, FAKE_PRISM_KEY):
            self.assertNotIn(leak, wire)
        first, second = SEEN["prism"]
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["session_id"], chat.session_id)
        self.assertEqual(first["agent_id"], second["agent_id"])
        self.assertNotIn("metadata", first)
        headers = {k.lower(): v for k, v in SEEN["prism_headers"][0].items()}  # header names are case-insensitive
        self.assertEqual(headers.get("x-prismtrace-key"), FAKE_PRISM_KEY)
        self.assertNotIn("authorization", headers)
        # what main.py prints is byte-for-byte what went out
        self.assertEqual(json.loads(prism.last_sent["body"]), second)

    def test_new_conversation_new_session(self):
        a, b = llm.Conversation(), llm.Conversation()
        a.ask("hi"); b.ask("hi"); prism.flush()
        self.assertNotEqual(SEEN["prism"][0]["session_id"], SEEN["prism"][1]["session_id"])

    def test_prism_error_does_not_break_app(self):
        Fake.prism_status = 500
        self.assertTrue(llm.Conversation().ask("hi"))
        prism.flush()

    def test_prism_down_does_not_break_app(self):
        config.PRISMTRACE_HOST = "http://127.0.0.1:9"  # nothing listens here
        self.assertTrue(llm.Conversation().ask("hi"))
        prism.flush()

    def test_prism_hang_is_bounded(self):
        import socket, time
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(1)  # accepts, never answers
        config.PRISMTRACE_HOST = f"http://127.0.0.1:{sock.getsockname()[1]}"
        config.PRISM_TIMEOUT_S = 0.5
        started = time.monotonic()
        self.assertTrue(llm.Conversation().ask("hi"))
        self.assertLess(time.monotonic() - started, 0.4)  # the reply did not wait for PRISM
        prism.flush()
        self.assertLess(time.monotonic() - started, 3)
        sock.close()


if __name__ == "__main__":
    unittest.main()


def test_call_llm_traces_under_the_callers_agent_name(monkeypatch):
    """Each part of the app names itself; the name goes to the trace, never to the model."""
    import io
    import json as _json

    import llm

    sent, traced = {}, {}

    class _Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        sent.update(_json.loads(request.data.decode("utf-8")))
        return _Reply(_json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm.prism, "send_trace", lambda payload: traced.update(payload))
    assert llm.call_llm([{"role": "user", "content": "hi"}], session_id="s-1", agent_id="europa-report-writer") == "ok"
    assert "agent_id" not in sent                       # not part of the request to the model
    assert "europa-report-writer" in _json.dumps(traced)
    traced.clear()
    llm.call_llm([{"role": "user", "content": "hi"}], session_id="s-2")
    assert llm.config.AGENT_ID in _json.dumps(traced)   # the default stays the app's one agent id
