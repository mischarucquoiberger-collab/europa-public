from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"ok": True}


def test_compare_has_contract_keys():
    r = client.post("/api/compare", json={"ticker": "aapl"}).json()
    for key in ("company", "cik", "filings", "changes", "blocked", "cost_usd", "models",
                "prism_session_id", "disclaimer"):
        assert key in r


def test_ask_declines_advice():
    r = client.post("/api/ask", json={"ticker": "AAPL", "question": "Should I buy this stock?"}).json()
    assert r["status"] == "DECLINED_ADVICE"
