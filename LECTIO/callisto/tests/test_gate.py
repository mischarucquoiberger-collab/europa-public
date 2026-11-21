"""Tests for the checker extension and the final number gate. Pure code: no network, no model calls."""
from backend import checker, gate
from backend.gate import GATE, FALLBACK, expand_dates, final_check, sweep


def pack(agent="market", status="ok", facts=None, exclude=None, allow_text=None, allow_dates=None):
    return {"agent": agent, "status": status, "reason": "", "source": "test", "as_of": "2026-11-20",
            "facts": facts or {}, "exclude": exclude or [], "sheet": "x", "allow_text": allow_text or [],
            "allow_dates": allow_dates or [], "items": [], "crosscheck": None, "seconds": 0.0}


def mfact(label, value, kind, fid_as_of="2026-11-20"):
    return {"label": label, "value": value, "kind": kind, "source": "Massive daily bars",
            "as_of": fid_as_of, "provider": "massive", "display": str(value)}


MARKET = pack(facts={
    "px_close_last": mfact("Last close", 229.87, "usd_per_share"),
    "ret_1m_pct": mfact("1-month price return (%)", -3.2187, "pct"),
    "volume_last": mfact("Volume, last day", 52312456, "count"),
    "market_cap": mfact("Market cap", 3.4612e12, "usd"),
}, allow_text=["52-week"], allow_dates=["2026-11-20"])


def draft(answer, status="ANSWERED", claims=None):
    return {"status": status, "answer": answer, "claims": claims or []}


def statuses(res):
    return [c["status"] for c in res["claims"]]


# 1
def test_old_behaviour_unchanged():
    res = checker.check("AAPL", "Net sales were $478.8 billion.", [])
    assert res["claims"][0]["status"] == "VERIFIED"
    assert set(res["claims"][0]) == {"text", "status", "source", "sec_value", "fact_id"}
    assert res["answer"] == "Net sales were $478.8 billion."
    bad = checker.check("AAPL", "Net sales were $999.9 billion.", [])
    assert bad["claims"][0]["note"] == "No SEC fact matches this number."
    assert checker.find_numbers("$5 billion and 7%")[0]["dollar"] is True
    assert checker.find_numbers("$5 billion and 7%")[1]["dollar"] is False


# 2
def test_market_close_verified_with_as_of_and_provider():
    res = final_check("AAPL", draft("The stock closed at $229.87."), [MARKET])
    assert res["status"] == "ANSWERED" and res["answer"] == "The stock closed at $229.87."
    c = res["claims"][0]
    assert c["status"] == "VERIFIED" and c["as_of"] == "2026-11-20" and c["provider"] == "massive"
    assert c["fact_id"] == "px_close_last"


def test_market_close_wrong_number_blocked():
    res = final_check("AAPL", draft("Apple reports in fiscal 2026. The stock closed at $231.10."), [MARKET])
    assert "NOT_FOUND" in statuses(res)
    assert res["answer"] == "Apple reports in fiscal 2026."
    assert any("$231.10" in b["text"] for b in res["blocked"])


# 3
def test_pct_return():
    ok = final_check("AAPL", draft("The stock fell 3.2% over one month."), [MARKET])
    assert statuses(ok) == ["VERIFIED"]
    bad = final_check("AAPL", draft("The stock fell 4.1% over one month."), [MARKET])
    assert bad["status"] == "I_DONT_KNOW" and bad["blocked"]


# 4
def test_count_fact():
    ok = final_check("AAPL", draft("About 52.3 million shares traded."), [MARKET])
    assert ok["claims"][0]["status"] == "VERIFIED" and ok["claims"][0]["fact_id"] == "volume_last"
    num = checker.find_numbers("$52.3 million")[0]
    fid, _ = checker.match_fact("AAPL", num, extra_facts=MARKET["facts"])
    assert fid != "volume_last"
    assert checker._kind_ok("usd", "count", dollar=True) is False
    assert checker._kind_ok("usd", "count", dollar=False) is True
    assert checker._kind_ok("pct", "count", dollar=False) is False


# 5
def test_market_cap():
    res = final_check("AAPL", draft("Market cap is $3.46 trillion."), [MARKET])
    assert res["claims"][0]["status"] == "VERIFIED" and res["claims"][0]["fact_id"] == "market_cap"


# 6
def test_exclude_quarantines_sec_fact():
    p = pack(agent="fundamentals", exclude=["revenue_fy2026"])
    res = final_check("AAPL", draft("Net sales were $478.8 billion."), [p])
    assert statuses(res) == ["NOT_FOUND"] and res["status"] == "I_DONT_KNOW"
    # 2026-11-21 (review hole 6): a pack that is not ok still quarantines; this used to pin the opposite
    res2 = final_check("AAPL", draft("Net sales were $478.8 billion."), [{**p, "status": "unavailable"}])
    assert statuses(res2) == ["NOT_FOUND"] and res2["status"] == "I_DONT_KNOW"


# 7
def test_sweep_rules():
    assert sweep("The stock closed at 229.87.") == ["229.87"]
    assert sweep("In fiscal 2026 the 10-K Item 1A changed, and FY2027 and 2027 and Q3 too.") == []
    assert sweep("Data as of 2026-11-20.") != []
    assert sweep("Data as of 2026-11-20.", allow_dates=["2026-11-20"]) == []
    assert sweep("Data as of November 20, 2026.") != []
    assert sweep("Data as of November 20, 2026.", allow_dates=["2026-11-20"]) == []
    assert sweep("It hit a 52-week high.") == ["52"]
    assert sweep("It hit a 52-week high.", allow_text=["52-week"]) == []
    assert sweep("It rose over 30 days.") == ["30"]
    assert sweep("It rose 15.1% to $478.8 billion.") == []
    assert "November 20, 2026" in expand_dates(["2026-11-20"]) and expand_dates(["nope"]) == []
    assert expand_dates(["2026-11-05"])[1] == "November 5, 2026"


def test_sweep_in_final_check():
    res = final_check("AAPL", draft("The stock closed at 229.87. It hit a 52-week high as of November 20, 2026. "
                                    "It rose over 30 days."), [MARKET])
    assert res["answer"] == "It hit a 52-week high as of November 20, 2026."
    unc = [c for c in res["claims"] if c["status"] == "UNCHECKABLE"]
    assert {c["text"] for c in unc} == {"229.87", "30"}
    assert all(c["source"] is None and c["sec_value"] is None for c in unc)
    assert [b["status"] for b in res["blocked"]] == ["UNCHECKABLE", "UNCHECKABLE"]
    # without the market pack, the date and 52-week are not allowed
    res2 = final_check("AAPL", draft("It hit a 52-week high as of November 20, 2026."), [])
    assert res2["status"] == "I_DONT_KNOW"


# 8
def test_skeptic_verdicts():
    text = "Net sales were $478.8 billion. Net income was $132.2 billion. Diluted EPS was $8.98."
    res = final_check("AAPL", draft(text), [], [{"i": 2, "verdict": "UNSUPPORTED", "why": "x"},
                                                {"i": 99, "verdict": "UNSUPPORTED", "why": "bad"},
                                                {"i": "zz", "verdict": "ADVICE"}, "junk"])
    assert res["answer"] == "Net sales were $478.8 billion. Diluted EPS was $8.98."
    assert res["blocked"] == [{"text": "Net income was $132.2 billion.", "status": "REFUTED",
                               "note": "Skeptic (second model): x"}]
    assert final_check("AAPL", draft(text), [], None)["answer"] == text


# 9
def test_advice_phrase():
    res = final_check("AAPL", draft("Net sales were $478.8 billion. You should buy the stock."), [])
    assert res["answer"] == "Net sales were $478.8 billion."
    assert res["blocked"][0]["status"] == "ADVICE"
    assert res["blocked"][0]["note"] == "Europa does not give investment advice."


# 10
def test_everything_removed_and_idk_kept():
    res = final_check("AAPL", draft("The stock will rise. It closed at 1."), [])
    assert res["status"] == "I_DONT_KNOW" and res["answer"] == FALLBACK
    idk = final_check("AAPL", draft("I don't know.", status="I_DONT_KNOW"), [])
    assert idk["status"] == "I_DONT_KNOW" and idk["answer"] == "I don't know." and idk["blocked"] == []
    assert final_check("AAPL", draft("Net sales were $478.8 billion.", status="weird"), [])["status"] == "ANSWERED"


# 11
def test_gate_runnable():
    inp = {"ticker": "AAPL", "draft": draft("The stock closed at $229.87."), "packs": [MARKET], "verdicts": None}
    out = GATE.invoke(inp)
    assert out["result"] == final_check("AAPL", inp["draft"], [MARKET], None)
    assert out["ticker"] == "AAPL"
    assert GATE.name == "number_gate"


# 12 regression: real answers from test-runs/run4-checker-on.md (A1, A4, A7)
A1 = ("Apple's net sales in fiscal 2026 were $478.8 billion. That is up 15.1% from $416.2 billion in fiscal 2025, "
      "an increase of $62.7 billion.")
A4 = ("Gross margin as a percentage of net sales rose to 48.8% in fiscal 2026 from 46.9% in fiscal 2025. "
      "That is an increase of 1.9 percentage points.")
A7 = ("The fiscal 2026 10-K added a new risk factor that was not in fiscal 2025: \"Issues related to artificial "
      "intelligence may result in reputational, competitive and financial harm to the Company, regulatory action, "
      "legal liability, and other adverse effects to the Company's business.\" Two existing risks were also changed: "
      "the supply risk now also covers compute capacity and storage resources, and the product defect risk now names "
      "artificial intelligence technologies and features.")
A7_QUOTE = ("Issues related to artificial intelligence may result in reputational, competitive and financial harm to "
            "the Company, regulatory action, legal liability, and other adverse effects to the Company's business.")


def test_regression_past_answers():
    filings = pack(agent="filings", allow_dates=["2026-09-26", "2025-09-27", "2026-11-03"])
    for text, claims in ((A1, []), (A4, []), (A7, [{"type": "quote", "text": A7_QUOTE, "filing": "FY2026"}])):
        res = final_check("AAPL", draft(text, claims=claims), [filings])
        assert res["blocked"] == [], (text, res["blocked"])
        assert res["status"] == "ANSWERED" and res["answer"] == text
        assert all(c["status"] == "VERIFIED" for c in res["claims"])


# 13
def test_garbage_never_raises():
    for args in ((None, None, None, None), ("AAPL", "x", "y", "z"), ("AAPL", {}, [None, 3, "p"], [1, None]),
                 ("AAPL", {"answer": 5, "claims": "no", "status": None}, [{"status": "ok", "facts": {"a": "b"}}], {}),
                 ("AAPL", {"answer": "Close $1.", "claims": [{"fact_id": ["list"], "value": "$1"}]},
                  [{"status": "ok", "facts": {"f": {"value": "nan?", "kind": "usd"}}}], None)):
        res = final_check(*args)
        assert set(res) == {"status", "answer", "claims", "blocked"}
        assert res["status"] in ("ANSWERED", "I_DONT_KNOW")
    assert final_check(None, None, None)["answer"] == FALLBACK
    assert gate.ADVICE_PHRASES


def test_idk_draft_cut_by_sweep_gets_plain_idk_text():
    from backend.gate import IDK_FALLBACK
    res = final_check("AAPL", {"status": "I_DONT_KNOW", "answer": "The data has no closing price for 2026-11-18.",
                               "claims": []}, [])
    assert res["status"] == "I_DONT_KNOW" and res["answer"] == IDK_FALLBACK
    assert [b["status"] for b in res["blocked"]] == ["UNCHECKABLE"]
