"""A message with personal or account data: the data is removed in code and the answer says so
(PRISM's review flagged an agent that took such data and carried on without a word about it)."""
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import privacy


def _client(monkeypatch, seen):
    def fake_answer(ticker, text):
        seen.append(text)
        return {"status": "ANSWERED", "answer": "Revenue was $478.8 billion.", "claims": [], "blocked": [], "news": [],
                "agent": "Callisto"}
    monkeypatch.setattr(app_module.ask_agent, "answer", fake_answer)
    return TestClient(app_module.app)


def test_chat_address_removes_the_data_and_opens_with_the_note(monkeypatch):
    seen = []
    client = _client(monkeypatch, seen)
    r = client.post("/api/chat", json={"message": "My card is 4111 1111 1111 1111. What was Apple's revenue?", "ticker": "AAPL"}).json()
    assert r["answer"].startswith("Please don't share personal or account details here.")
    assert "a payment card number" in r["answer"] and "4111" not in r["answer"]
    assert r["answer"].endswith("Revenue was $478.8 billion.") and r["reply"] == r["answer"] == r["response"]
    assert seen and "4111" not in seen[0] and privacy.REMOVED in seen[0]          # never reaches the pipeline


def test_only_personal_data_gets_the_note_and_no_pipeline_call(monkeypatch):
    seen = []
    client = _client(monkeypatch, seen)
    r = client.post("/api/chat", json={"message": "my SSN is 123-45-6789", "ticker": "AAPL"}).json()
    assert r["status"] == "CHAT" and r["kind"] == "privacy" and seen == []
    assert "a Social Security number" in r["answer"] and "123-45" not in r["answer"]


def test_an_ordinary_question_is_untouched(monkeypatch):
    seen = []
    client = _client(monkeypatch, seen)
    r = client.post("/api/chat", json={"message": "What was Apple's revenue in fiscal 2025?", "ticker": "AAPL"}).json()
    assert r["answer"] == "Revenue was $478.8 billion." and seen == ["What was Apple's revenue in fiscal 2025?"]
