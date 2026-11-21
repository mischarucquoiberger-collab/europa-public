"""Charts on /api/ask: built by code from facts or Massive closes, only when the question asks for one."""
from backend import charts, facts


def test_no_chart_unless_asked():
    assert charts.make_charts("AAPL", "What was Apple's revenue in fiscal 2026?") == []
    assert not charts.wanted("How has the stock done?")
    assert charts.wanted("show me a chart of Apple revenue")


def test_strip_chart_words_keeps_the_question():
    assert charts.strip_chart_words("Show me a chart of Apple revenue") == "Apple revenue"
    assert charts.strip_chart_words("What was revenue?") == "What was revenue?"
    assert charts.strip_chart_words("chart") == "Chart"


def test_apple_bar_chart_uses_the_checked_facts():
    out = charts.make_charts("AAPL", "chart of Apple revenue")
    assert out and out[0]["type"] == "bar"
    F = facts.FACTS["AAPL"]
    assert [p["y"] for p in out[0]["points"]] == [F["revenue_fy2025"]["value"], F["revenue_fy2026"]["value"]]


def test_price_chart_without_massive_is_a_note_not_a_crash():
    out = charts.charts_for("NVDA", "chart the stock price")   # tests run with no Massive key
    assert out and out[0]["type"] == "none"


def test_ask_endpoint_adds_charts_only_when_asked(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import app as appmod
    seen = {}

    def fake(ticker, q):
        seen["q"] = q
        return {"status": "ANSWERED", "answer": "ok", "claims": []}
    monkeypatch.setattr(appmod.ask_agent, "answer", fake)
    c = TestClient(appmod.app)
    r = c.post("/api/ask", json={"ticker": "AAPL", "question": "Show me a chart of Apple revenue"}).json()
    assert r["charts"][0]["type"] == "bar" and seen["q"] == "Apple revenue"
    r = c.post("/api/ask", json={"ticker": "AAPL", "question": "What was Apple revenue?"}).json()
    assert "charts" not in r and seen["q"] == "What was Apple revenue?"


def test_news_summary_is_verbatim_two_sentences_and_drops_pitches():
    from backend import specialists
    d = "Shares fell after a report. The company declined to comment. A third sentence follows."
    assert specialists._news_summary(d) == "Shares fell after a report. The company declined to comment."
    assert specialists._news_summary(None) == ""
    assert specialists._news_summary("Here is why you should buy this stock now.") == ""
