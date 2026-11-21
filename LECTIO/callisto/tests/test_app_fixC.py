import json

from fastapi.testclient import TestClient

from backend.app import app
from backend import ask as ask_agent

client = TestClient(app, raise_server_exceptions=False)
H = {"content-type": "application/json"}


def _post(path, raw):
    return client.post(path, content=raw, headers=H)


def test_lone_surrogate_ask_is_not_500(monkeypatch):
    seen = []
    monkeypatch.setattr(ask_agent, "answer", lambda t, q: seen.append(q) or {"answer": q.encode("utf-8").decode(), "status": "ANSWERED", "claims": [], "blocked": []})
    r = _post("/api/ask", b'{"ticker":"AAPL","question":"\\ud800 revenue?"}')
    assert r.status_code == 200
    assert seen == ["revenue?"]


def test_lone_surrogate_chat_is_not_500(monkeypatch):
    monkeypatch.setattr(ask_agent, "answer", lambda t, q: {"answer": q.encode("utf-8").decode(), "status": "ANSWERED", "claims": [], "blocked": []})
    r = _post("/api/chat", b'{"message":"\\udc00 revenue?"}')
    assert r.status_code == 200
    assert r.json()["reply"] == "revenue?"


def test_only_surrogate_question_is_blank_path():
    for path in ("/api/ask", "/api/chat"):
        r = _post(path, b'{"ticker":"AAPL","question":"\\ud800","message":"\\ud800"}')
        assert r.status_code == 200
        assert r.json()["status"] == "I_DONT_KNOW"


def test_surrogate_ticker_is_bad_ticker_200():
    r = _post("/api/ask", b'{"ticker":"\\ud800","question":"revenue?"}')
    assert r.status_code == 200 and r.json()["status"] == "I_DONT_KNOW"


def test_compare_stub_is_never_verified():
    r = client.post("/api/compare", json={"ticker": "aapl"})
    assert r.status_code == 200
    d = r.json()
    for ch in d["changes"]:
        for c in ch["claims"]:
            assert c["status"] != "VERIFIED"
            assert "SYNTHETIC" in c["text"]
    assert "SYNTHETIC" in json.dumps(d["blocked"])
