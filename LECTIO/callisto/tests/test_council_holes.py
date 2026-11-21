"""Codex council review holes 1, 5-9 (2026-11-21). Mocked, no network."""
from langchain_core.runnables import RunnableLambda

from backend import council, desk
from tests.test_desk import Fakes

REV = {"value": "$478.8 billion", "fact_id": "revenue_fy2026"}
EPS = {"value": "$8.98", "fact_id": "eps_diluted_fy2026"}


def d(answer, claims, status="ANSWERED"):
    return {"status": status, "answer": answer, "claims": claims}


def test_1_skeptic_timeout_fails_closed():
    f = Fakes(draft=d("Apple paid a dividend of $8.98.", [EPS]))
    f.deps.skeptic = RunnableLambda(lambda i: {"status": "timeout", "model": "m-skeptic"}, name="skeptic_review")
    desk.answer("AAPL", "What dividend?", deps=f.deps)
    v = f.calls["gate"][0]["verdicts"]
    assert any(x["i"] == 1 and x["verdict"] == "UNSUPPORTED" for x in v)


def _merge(drafts, rewriter):
    cmp = council.compare(drafts)
    models = {k: k for k in drafts}
    return council._merge({"drafts": drafts, "compare": cmp, "models": models,
                           "writer_input": {"ticker": "AAPL", "company": "Apple", "question": "q", "sheets": [],
                                            "unavailable": [], "has_news": False}}, None, rewriter)


def test_5_merge_single_draft_or_timeout_never_publishes_one_vote():
    drafts = {"A": d("Revenue was $478.8 billion.", [REV]), "B": d("EPS was $8.98.", [EPS]),
              "C": d("Other.", [{"value": "1", "fact_id": "x_fy2026"}])}
    one = RunnableLambda(lambda i: {"draft": drafts["B"], "model": "m"})
    out = _merge(drafts, one)
    assert out["draft"] is None or "8.98" not in out["draft"]["answer"]

    def boom(i):
        raise TimeoutError()
    out = _merge(drafts, RunnableLambda(boom))
    assert out["draft"] is None


def test_6_label_not_applied_when_prose_has_unconfirmed_digits():
    drafts = {"A": d("Revenue was $478.8 billion and EPS was $8.98.", [REV]),
              "B": d("Revenue was $478.8 billion.", [REV]), "C": d("Revenue was $478.8 billion.", [REV])}
    cmp = council.compare(drafts)
    assert not council.is_clean("A", drafts["A"], cmp)


def test_7_sign_and_scale_not_agreed():
    for a, b in (("-4.76%", "+4.76%"), ("8.98", "$8.98 million")):
        cmp = council.compare({"A": d("x", [{"value": a, "fact_id": "f"}]),
                               "B": d("x", [{"value": b, "fact_id": "f"}])})
        assert cmp["facts"]["f"]["status"] != "AGREED"


def test_8_idk_claims_are_not_votes():
    cmp = council.compare({"A": d("r", [REV]), "B": d("e", [EPS]), "C": d("idk", [REV], status="I_DONT_KNOW")})
    assert cmp["facts"]["revenue_fy2026"]["status"] == "SOLO"


def test_9_second_source_regex_only_explicit():
    rx = desk._SECOND_SOURCE_RX
    for q in ("Can you confirm revenue?", "Verify EPS", "Do they agree?"):
        assert not rx.search(q), q
    for q in ("Use a second source", "cross-check it", "another source please", "an independent source"):
        assert rx.search(q), q
