"""ask.answer() dispatch: multi -> desk, single -> old path, any desk error -> single_fallback. No network."""
from fastapi.testclient import TestClient

from backend import ask, desk
from backend.app import app

OLD_KEYS = {"answer", "claims", "status", "blocked", "company", "prism_session_id", "models", "checker",
            "seconds", "data_note", "disclaimer"}


def _fake_write(monkeypatch):
    def write(inp, config=None):
        return {**inp, "draft": {"status": "ANSWERED", "answer": "Net sales were $478.8 billion in fiscal 2026.",
                                 "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]}}
    monkeypatch.setattr(ask, "WRITE", ask.RunnableLambda(write, name="write_answer"))


def test_single_switch_uses_old_path(monkeypatch):
    _fake_write(monkeypatch)
    out = ask.answer("AAPL", "What were Apple's net sales in fiscal 2026?")
    assert out["pipeline"] == "single" and out["status"] == "ANSWERED"
    assert OLD_KEYS <= set(out)


def test_multi_calls_desk(monkeypatch):
    monkeypatch.setenv("EUROPA_PIPELINE", "multi")
    monkeypatch.setattr(desk, "answer", lambda t, q: {"pipeline": "multi", "called": (t, q)})
    assert ask.answer("AAPL", "hi")["called"] == ("AAPL", "hi")


def test_desk_error_falls_back_to_single(monkeypatch):
    monkeypatch.setenv("EUROPA_PIPELINE", "multi")
    _fake_write(monkeypatch)

    def boom(t, q):
        raise RuntimeError("desk broke")
    monkeypatch.setattr(desk, "answer", boom)
    out = ask.answer("AAPL", "What were Apple's net sales in fiscal 2026?")
    assert out["pipeline"] == "single_fallback"
    assert out["status"] == "ANSWERED" and all(c["status"] == "VERIFIED" for c in out["claims"])
    assert OLD_KEYS <= set(out)


def test_status_endpoint_booleans_only():
    body = TestClient(app).get("/api/status").json()
    assert set(body) == {"pipeline", "massive", "prism", "nicrron"}
    assert body["massive"] is False and isinstance(body["prism"], bool)


# ---- real specialists + real gate, fake models, mocked Massive (no network) ----

def _real_desk(monkeypatch, draft, income_rows=None, income_status=200):
    """desk.Deps with the real code steps (specialists, gate) and fake model steps."""
    import httpx
    from langchain_core.runnables import RunnableLambda

    from backend import gate, massive, specialists

    seen = {}

    def handler(req):
        if req.url.path == "/stocks/financials/v1/income-statements":
            return httpx.Response(income_status, json={"results": income_rows or []})
        return httpx.Response(404)

    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setenv("EUROPA_PIPELINE", "multi")
    monkeypatch.delenv("EUROPA_CHECKER", raising=False)
    monkeypatch.delenv("EUROPA_SKEPTIC", raising=False)
    monkeypatch.setattr(massive, "_TRANSPORT", httpx.MockTransport(handler))
    massive.clear_cache()

    def writer(inp):
        seen["sheets"] = inp["sheets"]
        return {"draft": dict(draft), "model": "anthropic/fake-writer"}

    deps = desk.Deps(
        guard=desk.GUARD,
        router=RunnableLambda(lambda i: {"specialists": ["filings", "fundamentals"], "advice": False, "reason": "",
                                         "model": "anthropic/fake-router", "fallback": False}, name="desk_router"),
        specialists=dict(specialists.SPECIALISTS),
        news_picker=RunnableLambda(lambda i: {"ids": [], "model": None}, name="news_picker"),
        writer=RunnableLambda(writer, name="write_answer"),
        skeptic=RunnableLambda(lambda i: {"status": "ok", "verdicts": [], "model": "openai/fake-skeptic"},
                               name="skeptic_review"),
        gate=gate.GATE)
    return deps, seen


def _income_rows(rev_factor):
    from backend import facts
    F = facts.FACTS["AAPL"]
    return [{"period_end": pe, "timeframe": "annual",
             "revenue": F[f"revenue_{fy}"]["value"] * (rev_factor if fy == "fy2026" else 1.0),
             "gross_profit": F[f"gross_margin_{fy}"]["value"],
             "research_development": F[f"rnd_{fy}"]["value"],
             "operating_income": F[f"operating_income_{fy}"]["value"],
             "consolidated_net_income_loss": F[f"net_income_{fy}"]["value"],
             "diluted_earnings_per_share": F[f"eps_diluted_{fy}"]["value"]}
            for fy, pe in [("fy2026", "2026-09-26"), ("fy2025", "2025-09-27")]]


def test_two_sources_disagree_quarantines_revenue_end_to_end(monkeypatch):
    """Massive revenue 1% off the SEC figure: the fact leaves the writer's sheet and the gate cuts the sentence."""
    draft = {"status": "ANSWERED",
             "answer": "Net sales were $478.8 billion in fiscal 2026. Diluted earnings per share were $8.98.",
             "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"},
                        {"value": "$8.98", "fact_id": "eps_diluted_fy2026"}]}
    deps, seen = _real_desk(monkeypatch, draft, _income_rows(1.01))
    out = desk.answer("AAPL", "Does a second source confirm fiscal 2026 revenue?", deps=deps)
    filings_sheet = seen["sheets"][0]
    for fid in ("revenue_fy2026", "revenue_change_pct", "revenue_change_amount", "gross_margin_pct_fy2026"):
        assert f"{fid} |" not in filings_sheet, fid
    assert "eps_diluted_fy2026 |" in filings_sheet
    assert "478.8" not in out["answer"] and "$8.98" in out["answer"]
    assert any("478.8" in b["text"] for b in out["blocked"])
    assert "Two sources disagreed" in out["answer"]
    assert OLD_KEYS <= set(out) and out["pipeline"] == "multi"
    assert out["models"] == ["anthropic/fake-router", "anthropic/fake-writer", "openai/fake-skeptic"]


def test_two_sources_agree_says_confirmed(monkeypatch):
    draft = {"status": "ANSWERED", "answer": "Net sales were $478.8 billion in fiscal 2026.",
             "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]}
    deps, _ = _real_desk(monkeypatch, draft, _income_rows(1.0))
    out = desk.answer("AAPL", "Does a second source confirm fiscal 2026 revenue?", deps=deps)
    assert out["status"] == "ANSWERED" and not out["blocked"]
    assert all(c["status"] == "VERIFIED" for c in out["claims"])
    assert "confirmed by a second source" in out["answer"]


def test_nothing_compared_never_says_confirmed(monkeypatch):
    """Massive rows with unknown field names (every row NOT_COMPARED), or only a fiscal 2025 row:
    the code must not write 'confirmed'. It says the check was incomplete only if the user asked."""
    draft = {"status": "ANSWERED", "answer": "Net sales were $478.8 billion in fiscal 2026.",
             "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]}
    unknown = [{"period_end": pe, "timeframe": "annual", "revenues_total": 1.0}
               for pe in ("2026-09-26", "2025-09-27")]
    only_2025 = [r for r in _income_rows(1.0) if r["period_end"] == "2025-09-27"]
    for rows in (unknown, only_2025):
        deps, _ = _real_desk(monkeypatch, draft, rows)
        asked = desk.answer("AAPL", "Does a second source confirm fiscal 2026 revenue?", deps=deps)
        assert "were confirmed by a second source" not in asked["answer"]
        assert "can't say the annual figures were confirmed" in asked["answer"]
        assert "$478.8 billion" in asked["answer"] and all(c["status"] == "VERIFIED" for c in asked["claims"])
        plain = desk.answer("AAPL", "How much did net sales grow?", deps=deps)
        assert "confirmed" not in plain["answer"] and "second source" not in plain["answer"]


def test_second_source_notice_only_when_asked(monkeypatch):
    """Plan without income statements (HTTP 403): the answer says so only if the user asked for a second source.
    The sources and unavailable lists always say it."""
    draft = {"status": "ANSWERED", "answer": "Net sales were $478.8 billion in fiscal 2026.",
             "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]}
    deps, _ = _real_desk(monkeypatch, draft, income_status=403)
    plain = desk.answer("AAPL", "How much did net sales grow?", deps=deps)
    assert plain["status"] == "ANSWERED" and "unavailable" not in plain["answer"]
    assert plain["unavailable"][0]["agent"] == "fundamentals"
    assert [s["status"] for s in plain["sources"]] == ["ok", "unavailable"]
    asked = desk.answer("AAPL", "Does a second data source confirm Apple's fiscal 2026 revenue?", deps=deps)
    assert "second-source check did not respond just now" in asked["answer"]
    assert all(c["status"] == "VERIFIED" for c in asked["claims"])


def test_headline_pointer_sentence_not_repeated():
    out = desk._notices({"answer": "Net sales were $478.8 billion. Recent headlines are listed below.",
                         "packs": [], "claims": [], "news": [{"title": "x"}], "writer_ran": True, "question": "q"})
    assert out["answer"] == "Net sales were $478.8 billion. Recent headlines are listed below, unverified."


def test_pitch_style_headlines_are_dropped():
    from backend.specialists import ADVICE_HEADLINE
    for bad in ["The S&P 500 Just Entered Correction Territory. Here's What It Means for Investors Right Now.",
                "Here's What $1,000 in VOO Could Have Become.", "3 Stocks to Watch This Week",
                "Is Apple a Buy After Earnings?", "My Top Prediction for 2027",
                "After Plummeting 62% This Year, Could Buying Intel Stock Today Set You Up for Life?",
                "This Dividend ETF Could Supercharge Your Passive Income. Here's How.",
                "Where Will VOO Be in 30 Years? Here's What History Says."]:
        assert ADVICE_HEADLINE.search(bad), bad
    for ok in ["Stock Market Today, Nov. 20: Stocks Plunge as AI Trade Unwinds",
               "Apple reports record services revenue", "Apple Unveils New Chip at Developer Event",
               "Stock Market Today, Nov. 20: Amazon Shares Slide on AI and Mega-Cap Tech Sell-Off"]:
        assert not ADVICE_HEADLINE.search(ok), ok
