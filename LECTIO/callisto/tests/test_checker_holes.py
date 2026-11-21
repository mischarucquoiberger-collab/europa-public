"""Holes found in review on 2026-11-21, one test (or more) per hole. Pure code: no network, no model calls.

Each test here failed before the fix and passes after it. Fail closed: a wrong metric, sign, direction,
unit or date must cut the sentence.
"""
from datetime import date, datetime, timedelta

import httpx
import pytest
from langchain_core.runnables import RunnableLambda

from backend import checker, desk, gate, massive, specialists as sp


def mfact(label, value, kind, as_of="2026-11-20"):
    return {"label": label, "value": value, "kind": kind, "source": "Massive daily bars", "as_of": as_of,
            "provider": "massive", "display": str(value)}


MARKET_FACTS = {
    "px_close_last": mfact("Closing price, last trading day", 342.56, "usd_per_share"),
    "ret_1d_pct": mfact("Price return, one day", -1.9043, "pct"),
    "ret_3m_pct": mfact("Price return, three months", 10.4127, "pct"),
}


def claim_status(res):
    return [(c["text"], c["status"]) for c in res["claims"]]


# ---------------------------------------------------------------- hole 1: wrong metric
def test_h1_cited_fact_must_be_the_one_that_matches():
    res = checker.check("AAPL", "FY2026 revenue was $112.0 billion.",
                        [{"value": "$112.0 billion", "fact_id": "revenue_fy2026"}])
    assert claim_status(res) == [("$112.0 billion", "MISMATCH")]
    assert res["answer"] == "" and len(res["blocked"]) == 1


def test_h1_cited_fact_that_does_not_exist_is_cut():
    res = checker.check("AAPL", "Net sales were $478.8 billion.",
                        [{"value": "$478.8 billion", "fact_id": "made_up_fact"}])
    assert res["answer"] == "" and res["claims"][0]["status"] != "VERIFIED"


def test_h1_right_citation_and_uncited_numbers_still_pass():
    cited = checker.check("AAPL", "Net sales were $478.8 billion.",
                          [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}])
    assert claim_status(cited) == [("$478.8 billion", "VERIFIED")] and cited["claims"][0]["fact_id"] == "revenue_fy2026"
    uncited = checker.check("AAPL", "Net income was $112.0 billion in fiscal 2025.", [])
    assert claim_status(uncited) == [("$112.0 billion", "VERIFIED")]


# ---------------------------------------------------------------- hole 2: signed claim values
@pytest.mark.parametrize("value", ["-1.9%", "−1.9%", "+1.9%", " - 1.9 %"])
def test_h2_signed_claim_value_still_maps_to_its_fact(value):
    res = checker.check("AAPL", "Apple shares fell 1.9% in one day.", [{"value": value, "fact_id": "ret_1d_pct"}],
                        MARKET_FACTS)
    assert claim_status(res) == [("1.9%", "VERIFIED")]
    assert res["claims"][0]["fact_id"] == "ret_1d_pct" and res["claims"][0]["provider"] == "massive"


def test_h2_signed_claim_cannot_fall_through_to_an_sec_fact():
    # no market facts loaded: the cited id is unknown, so it must not be "verified" by gross margin points
    res = checker.check("AAPL", "Apple shares fell 1.9%.", [{"value": "-1.9%", "fact_id": "ret_1d_pct"}])
    assert res["answer"] == "" and res["claims"][0]["status"] != "VERIFIED"


# ---------------------------------------------------------------- hole 3: direction flips
@pytest.mark.parametrize("text,claims,extra", [
    ("Buybacks increased 4.8%.", [], None),
    ("Buybacks increased 4.8%.", [{"value": "4.8%", "fact_id": "buybacks_change_pct"}], None),
    ("Share repurchases rose by $4.3 billion.", [], None),
    ("Buybacks changed by +4.8%.", [], None),
    ("Apple shares rose 1.9%.", [{"value": "1.9%", "fact_id": "ret_1d_pct"}], MARKET_FACTS),
    ("Apple shares were up 1.9% in one day.", [], MARKET_FACTS),
    ("The one-day return was 1.9%.", [], MARKET_FACTS),            # minus sign dropped
    ("Apple shares fell 10.4% over three months.", [], MARKET_FACTS),
    ("Net sales fell 15.1%.", [], None),
    ("Net sales grew 15.1% and buybacks grew 4.8%.", [], None),
])
def test_h3_direction_that_contradicts_the_sign_is_cut(text, claims, extra):
    res = checker.check("AAPL", text, claims, extra)
    assert res["answer"] == "", res
    assert any(c["status"] == "MISMATCH" for c in res["claims"])


@pytest.mark.parametrize("text,extra", [
    ("Apple spent less on buybacks in fiscal 2026. Cash paid for share repurchases was $86.4 billion, compared "
     "with $90.7 billion in fiscal 2025, a decrease of $4.3 billion or 4.8%.", None),
    ("Net sales grew 15.1% while buybacks fell 4.8%.", None),
    ("Buybacks were down 4.8%, while net sales were up 15.1%.", None),
    ("Buybacks changed by -4.8%.", None),
    ("Buybacks changed by −4.8%.", None),
    ("That is up from $416.2 billion in fiscal 2025, an increase of +15.1%.", None),
    ("Apple's stock price return was -1.9% over the past day.", MARKET_FACTS),
    ("Apple shares fell 1.9% in one day.", MARKET_FACTS),
    ("The last close was $342.56, which was a one-day return of -1.9%.", MARKET_FACTS),
    ("Over the past three months, the return was +10.4%.", MARKET_FACTS),
    ("That was down from $90.7 billion in fiscal 2025.", None),   # a level, not a change: no direction check
])
def test_h3_correct_directions_are_kept(text, extra):
    res = checker.check("AAPL", text, [], extra)
    assert res["answer"] == text and not res["blocked"]
    assert all(c["status"] == "VERIFIED" for c in res["claims"])


# ---------------------------------------------------------------- hole 4: units and partial tokens
def test_h4_percent_does_not_match_a_percentage_point_fact():
    res = checker.check("AAPL", "Gross margin rose 1.9%.", [])
    assert res["answer"] == "" and claim_status(res) == [("1.9%", "NOT_FOUND")]
    cited = checker.check("AAPL", "Gross margin rose 1.9%.",
                          [{"value": "1.9%", "fact_id": "gross_margin_pct_change_pts"}])
    assert cited["answer"] == "" and claim_status(cited) == [("1.9%", "MISMATCH")]
    ok = checker.check("AAPL", "Gross margin rose 1.9 percentage points.", [])
    assert claim_status(ok) == [("1.9 percentage points", "VERIFIED")]


def test_h4_leading_decimal_is_not_cut_off():
    nums = checker.find_numbers("Margin moved .5% and cost $.75 million.")
    assert [(n["text"], n["value"]) for n in nums] == [(".5%", 0.5), ("$.75 million", 750000.0)]
    # ".1%" used to be read as "1%" and matched cash growth (1.03%)
    res = checker.check("AAPL", "Cash grew .1%.", [])
    assert res["answer"] == "" and res["claims"][0]["status"] == "NOT_FOUND"


# ---------------------------------------------------------------- hole 5: wrong date
TODAY = date(2026, 11, 21)  # Saturday; the last bar is Friday 2026-11-20


def _ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=massive.ET).timestamp() * 1000)


def _market_pack(monkeypatch):
    days, d = [], date(2026, 11, 20)
    while len(days) < 30:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days = days[::-1]
    closes = [300.0 + i for i in range(29)] + [342.56]

    def handler(req):
        if "/v2/aggs/" in req.url.path:
            return httpx.Response(200, json={"results": [
                {"t": _ms(day), "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 50_000_000}
                for day, c in zip(days, closes)]})
        return httpx.Response(200, json={"results": {"market_cap": 4.98e12,
                                                     "weighted_shares_outstanding": 1.45e10}})

    old = massive._TRANSPORT
    massive.clear_cache()
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(massive, "today_et", lambda: TODAY)
    massive._TRANSPORT = httpx.MockTransport(handler)
    try:
        return sp.market({"ticker": "AAPL"})
    finally:
        massive._TRANSPORT = old
        massive.clear_cache()


def test_h5_market_pack_allows_only_the_last_trading_day(monkeypatch):
    p = _market_pack(monkeypatch)
    assert p["status"] == "ok" and p["as_of"] == "2026-11-20"
    assert p["allow_dates"] == ["2026-11-20", "2026-11-19"]   # last bar, plus the prior close's own bar date


def test_h5_close_on_todays_date_is_cut(monkeypatch):
    p = _market_pack(monkeypatch)
    wrong = gate.final_check("AAPL", {"status": "ANSWERED", "answer": "Apple closed at $342.56 on 2026-11-21.",
                                      "claims": [{"value": "$342.56", "fact_id": "px_close_last"}]}, [p])
    # 2026-11-21 (attack round): the checker now ties the close to its date, so this is cut one step earlier
    assert wrong["status"] == "I_DONT_KNOW" and wrong["blocked"][0]["status"] in ("BLOCKED", "UNCHECKABLE")
    right = gate.final_check("AAPL", {"status": "ANSWERED", "answer": "Apple closed at $342.56 on 2026-11-20.",
                                      "claims": [{"value": "$342.56", "fact_id": "px_close_last"}]}, [p])
    assert right["status"] == "ANSWERED" and not right["blocked"]


# ---------------------------------------------------------------- hole 6: desk
def _pack(agent, status="ok", **kw):
    base = {"agent": agent, "status": status, "reason": None, "source": None, "as_of": None, "facts": {},
            "exclude": [], "sheet": "", "allow_text": [], "allow_dates": [], "items": [], "crosscheck": [],
            "seconds": 0.01}
    return {**base, **kw}


FILINGS_SHEET = "FACTS (id | what | value):\nrevenue_fy2026 | Net sales (revenue), fiscal 2026 | $478.8 billion"
GOOD_DRAFT = {"status": "ANSWERED", "answer": "Net sales were $478.8 billion in fiscal 2026.",
              "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]}


def _deps(packs, writer_out=None, skeptic_out=None, the_gate=None):
    route = {"specialists": list(packs), "advice": False, "reason": "", "model": "m-router", "fallback": False}
    writer_out = writer_out if writer_out is not None else {"draft": dict(GOOD_DRAFT), "model": "m-writer"}
    skeptic_out = skeptic_out if skeptic_out is not None else {"status": "ok", "verdicts": [], "model": "m-skeptic"}
    return desk.Deps(
        guard=desk.GUARD,
        router=RunnableLambda(lambda i: route, name="desk_router"),
        specialists={n: RunnableLambda(lambda i, n=n: packs[n], name=f"specialist_{n}") for n in packs},
        news_picker=RunnableLambda(lambda i: {"ids": [], "model": None}, name="news_picker"),
        writer=RunnableLambda(lambda i: writer_out, name="write_answer"),
        skeptic=RunnableLambda(lambda i: skeptic_out, name="skeptic_review"),
        gate=the_gate or gate.GATE)


@pytest.fixture
def _desk_env(monkeypatch):
    monkeypatch.delenv("EUROPA_CHECKER", raising=False)
    monkeypatch.delenv("EUROPA_SKEPTIC", raising=False)


def test_h6_exclusions_from_a_pack_that_is_not_ok_still_apply(_desk_env):
    packs = {"filings": _pack("filings", sheet=FILINGS_SHEET),
             "fundamentals": _pack("fundamentals", status="unavailable", reason="lost connection half way",
                                   exclude=["revenue_fy2026"])}
    out = desk.answer("AAPL", "What were net sales?", deps=_deps(packs))
    assert "$478.8 billion" not in out["answer"]
    assert out["status"] == "I_DONT_KNOW" and out["blocked"]


def test_h6_gate_takes_exclusions_from_every_pack():
    packs = [_pack("filings", sheet=FILINGS_SHEET),
             _pack("fundamentals", status="unavailable", reason="x", exclude=["revenue_fy2026"])]
    res = gate.final_check("AAPL", dict(GOOD_DRAFT), packs)
    assert res["status"] == "I_DONT_KNOW" and "$478.8 billion" not in res["answer"]
    # facts from a pack that is not ok are still ignored
    bad = [_pack("market", status="unavailable", reason="x", facts={"px_close_last": MARKET_FACTS["px_close_last"]})]
    res = gate.final_check("AAPL", {"status": "ANSWERED", "answer": "Apple closed at $342.56.", "claims": []}, bad)
    assert res["status"] == "I_DONT_KNOW"


def test_h6_raw_error_reason_never_reaches_the_answer(_desk_env):
    packs = {"filings": _pack("filings", sheet=FILINGS_SHEET),
             "market": _pack("market", status="unavailable", reason="HTTP 503 from upstream, retry in 30 seconds")}
    out = desk.answer("AAPL", "What were net sales and the stock price?", deps=_deps(packs))
    assert "503" not in out["answer"] and "30 seconds" not in out["answer"] and "HTTP" not in out["answer"]
    assert "Market data did not respond just now, so that part is left out rather than guessed." in out["answer"]
    assert "$478.8 billion" in out["answer"]
    assert out["unavailable"] == [{"agent": "market", "reason": "HTTP 503 from upstream, retry in 30 seconds"}]


@pytest.mark.parametrize("writer_out", [
    {"draft": {"status": "ANSWERED", "answer": 478.8, "claims": []}, "model": "m"},
    {"draft": {"status": "ANSWERED", "answer": ["Net sales were $1 billion."], "claims": []}, "model": "m"},
    {"draft": {"status": "ANSWERED", "answer": None, "claims": "x"}, "model": "m"},
    {"draft": "Net sales were $1 billion.", "model": "m"},
    {"draft": {"answer": "Net sales were $478.8 billion in fiscal 2026.", "claims": None}, "model": "m"},
    "not a dict",
])
def test_h6_bad_writer_output_does_not_raise(_desk_env, monkeypatch, writer_out):
    packs = {"filings": _pack("filings", sheet=FILINGS_SHEET)}
    for checker_mode in ("on", "off"):
        monkeypatch.setenv("EUROPA_CHECKER", checker_mode)
        out = desk.answer("AAPL", "What were net sales?", deps=_deps(packs, writer_out=writer_out))
        assert out["status"] in ("ANSWERED", "I_DONT_KNOW") and isinstance(out["answer"], str)
        assert "$1 billion" not in out["answer"]


@pytest.mark.parametrize("skeptic_out", [
    {"status": "ok", "verdicts": ["UNSUPPORTED", 3, None], "model": "m"},
    {"status": "ok", "verdicts": "UNSUPPORTED", "model": "m"},
    {"status": "ok", "verdicts": {"i": 1}, "model": "m"},
    "not a dict",
    None,
])
def test_h6_bad_skeptic_output_does_not_raise(_desk_env, monkeypatch, skeptic_out):
    packs = {"filings": _pack("filings", sheet=FILINGS_SHEET)}
    for mode in ("enforce", "advisory"):
        monkeypatch.setenv("EUROPA_SKEPTIC", mode)
        deps = _deps(packs)
        deps.skeptic = RunnableLambda(lambda i: skeptic_out, name="skeptic_review")
        out = desk.answer("AAPL", "What were net sales?", deps=deps)
        assert isinstance(out["answer"], str)
        if mode == "enforce" and not (isinstance(skeptic_out, dict) and skeptic_out.get("status") == "ok"):
            # skeptic broken in enforce mode: fail closed, the number sentence is withheld
            assert "$478.8 billion" not in out["answer"]
            continue
        assert out["status"] == "ANSWERED" and "$478.8 billion" in out["answer"]
        assert all(c["status"] == "VERIFIED" for c in out["claims"])
