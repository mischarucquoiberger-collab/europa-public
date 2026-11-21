"""Ticker from the question, key-stat tiles and automatic price charts on /api/ask. All code-built, never a model."""
from backend import charts, snapshot, tickers


def test_ticker_comes_from_the_question_with_the_box_as_fallback():
    assert tickers.pick_ticker("what happened to nvidia yesterday", "AAPL") == "NVDA"
    assert tickers.pick_ticker("should i buy $TSLA", "AAPL") == "TSLA"
    assert tickers.pick_ticker("how is the stock doing", "MSFT") == "MSFT"
    assert tickers.pick_ticker("What is EPS and what was it?", "AAPL") == "AAPL"   # EPS is not a ticker


def test_auto_chart_only_for_price_move_questions():
    assert charts.auto_wanted("How has Apple stock done this year?")
    assert charts.auto_wanted("what happened to nvidia yesterday")
    assert not charts.auto_wanted("What was Apple's revenue in fiscal 2026?")
    assert not charts.auto_wanted("chart of the stock price")          # an asked-for chart is the other path
    assert charts.auto_charts("NVDA", "what happened to nvidia yesterday") == []   # no Massive key in tests


def test_stats_tiles_use_the_pack_display_values(monkeypatch):
    from backend import specialists
    pack = {"status": "ok", "as_of": "2026-11-20", "facts": {
        "px_close_last": {"display": "$125.53"}, "ret_1d_pct": {"display": "-14.0%"},
        "px_52w_low": {"display": "$124.50"}, "px_52w_high": {"display": "$243.37"}}}
    monkeypatch.setattr(specialists, "market", lambda inp: pack)
    out = snapshot.stats("NVDA")
    assert [t["label"] for t in out] == ["Price", "Day change", "52-week range"]
    assert out[0]["value"] == "$125.53" and out[0]["note"] == "close, 2026-11-20"
    assert out[2]["value"] == "$124.50 to $243.37"
    monkeypatch.setattr(specialists, "market", lambda inp: {"status": "unavailable"})
    assert snapshot.stats("NVDA") == []


def test_ask_endpoint_resolves_the_ticker_and_never_breaks_on_extras(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import app as appmod
    seen = {}

    def fake(ticker, q):
        seen["t"] = ticker
        return {"status": "ANSWERED", "answer": "ok", "claims": []}
    monkeypatch.setattr(appmod.ask_agent, "answer", fake)
    monkeypatch.setattr(appmod.snapshot, "stats", lambda t: (_ for _ in ()).throw(RuntimeError("boom")))
    r = TestClient(appmod.app).post("/api/ask", json={"ticker": "AAPL", "question": "how is nvidia doing"}).json()
    assert seen["t"] == "NVDA" and r["ticker"] == "NVDA" and r["answer"] == "ok" and "stats" not in r


def test_market_pack_allows_the_prior_close_date(monkeypatch):
    import inspect
    from backend import specialists
    src = inspect.getsource(specialists)
    assert "allow_dates=[as_of, *prior_dates, *div_dates]" in src


def test_prior_close_date_is_allowed_only_with_the_prior_close(monkeypatch):
    from backend import gate
    from tests.test_checker_holes import _market_pack
    p = _market_pack(monkeypatch)
    prior = p["facts"]["px_close_prior"]
    assert p["allow_dates"][:2] == [p["as_of"], prior["as_of"]]
    right = gate.final_check("AAPL", {"status": "ANSWERED", "claims": [],
        "answer": f"Apple closed at $342.56 on {p['as_of']}, up from {prior['display']} on {prior['as_of']}."}, [p])
    assert right["status"] == "ANSWERED" and not right["blocked"]
    wrong = gate.final_check("AAPL", {"status": "ANSWERED", "claims": [],
        "answer": f"Apple closed at $342.56 on {prior['as_of']}."}, [p])
    assert wrong["status"] == "I_DONT_KNOW"      # the last close on the day-before date is still cut
    swapped = gate.final_check("AAPL", {"status": "ANSWERED", "claims": [],
        "answer": f"Closing price was {prior['display']} on {p['as_of']}."}, [p])
    assert swapped["status"] == "I_DONT_KNOW"    # and the prior close on the latest date


def test_ordinary_words_never_go_to_the_name_search(monkeypatch):
    searched = []
    monkeypatch.setattr(tickers, "_search_one", lambda p: searched.append(p) or None)
    monkeypatch.setattr(tickers.massive, "available", lambda: True)
    for q in ["how do i start investing with $100?", "is my data stored?", "tell me one stock that is guaranteed to go up",
              "who checks the numbers?", "can you be wrong?"]:
        assert tickers.pick_ticker(q, "AAPL") == "AAPL"
    if tickers._WORDS:                       # the system word list is present on this machine
        assert searched == []
    assert tickers.pick_ticker("how did the market do this week?", "AAPL") == "SPY"
    assert tickers.pick_ticker("how is the dow doing?", "AAPL") == "DIA"
    assert tickers.pick_ticker("is tesla beating the market", "AAPL") == "TSLA"
