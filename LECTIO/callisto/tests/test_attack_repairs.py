"""Attack round, 2026-11-21: bypasses and false blocks reported by adversarial verifiers.

Pure code: no network, no model calls. Each "cut" test passed a wrong sentence before the fix; each "kept"
test blocked (or risked blocking) a correct sentence. Fail closed, but do not cut what is true.
"""
import pytest

from backend import agents, checker, desk, gate
from backend.gate import FALLBACK, final_check, sweep


def mfact(label, value, kind, as_of="2026-11-20"):
    return {"label": label, "value": value, "kind": kind, "source": "Massive daily bars", "as_of": as_of,
            "provider": "massive", "display": str(value)}


def pack(agent, **kw):
    p = {"agent": agent, "status": "ok", "reason": "", "source": "test", "as_of": "2026-11-20", "facts": {},
         "exclude": [], "sheet": "x", "allow_text": [], "allow_dates": [], "items": [], "crosscheck": [],
         "seconds": 0.0}
    p.update(kw)
    return p


FILINGS = pack("filings", as_of=None, allow_dates=["2026-09-26", "2025-09-27", "2026-11-03"])
MARKET = pack("market", allow_text=["52-week"], allow_dates=["2026-11-20"], facts={
    "px_close_last": mfact("Closing price, last trading day", 268.47, "usd_per_share"),
    "px_open_last": mfact("Opening price, last trading day", 271.10, "usd_per_share"),
    "px_close_prior": mfact("Closing price, trading day before", 273.67, "usd_per_share"),
    "px_52w_high": mfact("52-week high (intraday)", 288.62, "usd_per_share"),
    "px_52w_low": mfact("52-week low (intraday)", 169.21, "usd_per_share"),
    "ret_1d_pct": mfact("Price return, one day", -1.9, "pct"),
    "ret_1m_pct": mfact("Price return, one month", -1.6, "pct"),
    "ret_3m_pct": mfact("Price return, three months", 10.4, "pct"),
    "ret_1y_pct": mfact("Price return, one year", 12.3, "pct"),
    "market_cap": mfact("Market capitalization", 3.98e12, "usd", as_of="2026-11-21"),
})
PACKS = [FILINGS, MARKET]


def run(answer, claims=None, packs=PACKS):
    return final_check("AAPL", {"status": "ANSWERED", "answer": answer, "claims": claims or []}, packs)


def assert_cut(answer, claims=None):
    res = run(answer, claims)
    assert res["answer"] == FALLBACK and res["status"] == "I_DONT_KNOW", res
    assert res["blocked"], res


def assert_kept(answer, claims=None):
    res = run(answer, claims)
    assert res["answer"] == answer and not res["blocked"], res
    assert all(c["status"] == "VERIFIED" for c in res["claims"]), res


# ---------------------------------------------------------------- wrong metric: the number belongs to another line
@pytest.mark.parametrize("answer,claims", [
    ("Apple's net income in fiscal 2026 was $478.8 billion.", None),          # that is revenue
    ("Apple's revenue in fiscal 2026 was $132.2 billion.", None),             # that is net income
    ("Net income was $478.8 billion and revenue was $132.2 billion.", None),  # swapped inside one sentence
    ("R&D rose 15.1% in fiscal 2026.", [{"fact_id": "revenue_change_pct", "value": "15.1%"}]),
    ("R&D rose 15.1% in fiscal 2026.", None),
    ("Revenue grew 1% in fiscal 2026.", None),                                # 1% is cash growth
    ("Apple's diluted EPS was $268.47.", None),                               # a stock price
    ("Apple's 52-week high was $268.47.", None),                              # the last close
    ("Apple stock returned 18.0% over the past year.", None),                 # net income growth
    ("Market cap was $132.2 billion.", None),                                 # net income
    ("The stock closed at $271.10.", None),                                   # the opening price
    ("The stock opened at $268.47.", None),                                   # the closing price
    ("The 52-week low was $288.62.", None),                                   # the 52-week high
])
def test_number_must_belong_to_the_metric_the_sentence_names(answer, claims):
    assert_cut(answer, claims)


# ---------------------------------------------------------------- wrong year, period or date
@pytest.mark.parametrize("answer", [
    "Revenue in fiscal 2025 was $478.8 billion.",
    "FY2025 revenue was $478.8 billion.",
    "Apple's revenue in fiscal 2025 was $478.8 billion.",
    "Net sales were $416.2 billion in fiscal 2026.",
    "Over the past month the stock returned +12.3%.",            # that is the one-year return
    "The 3-month return was -1.6%.",                             # that is the one-month return
    "Apple stock closed at $268.47 on November 3, 2026.",        # the 10-K filing date, not the trading day
    "Apple stock closed at $268.47 on November 20, 2025.",       # right day, wrong year
])
def test_number_must_belong_to_the_year_period_and_date_named(answer):
    assert_cut(answer)


# ---------------------------------------------------------------- direction on level figures
@pytest.mark.parametrize("answer", [
    "Apple posted a net loss of $132.2 billion.",
    "Revenue was down from $478.8 billion in fiscal 2026 to $416.2 billion in fiscal 2025.",
    "Buybacks rose to $86.4 billion, a 4.8% decrease.",
    "Net sales fell to $478.8 billion in fiscal 2026.",
    "That was up from $90.7 billion in fiscal 2025.",            # buybacks fell
    "The stock rose to $268.47.",                                # it fell from $273.67
    "Revenue change was (15.1%).",                               # accounting brackets mean minus
    "Buybacks were not lower; they changed 4.8%.",
    "Net sales did not grow 15.1%.",
])
def test_direction_words_are_checked_on_levels_brackets_and_negation(answer):
    assert_cut(answer)


# ---------------------------------------------------------------- numbers the checker cannot read
@pytest.mark.parametrize("answer", [
    "Revenue roughly doubled to $478.8 billion.",
    "Net income tripled.",
    "Revenue was about five hundred billion dollars.",
    "Revenue grew fifty percent, per the 10-K.",
    "Apple has 2026 retail stores.",
    "Apple had 1999 lawsuits pending.",
    "Revenue was $" + "".join(chr(0xFF10 + int(d)) for d in "478") + ".8 billion.",   # fullwidth digits
    "Net income was $0 trillion.",
])
def test_unreadable_or_invented_numbers_are_cut(answer):
    assert_cut(answer)


def test_years_and_time_windows_still_pass_the_sweep():
    assert sweep("In fiscal 2026 and FY2025, from 2025 to 2026, since 2025, Apple's 2026 10-K (2026) said so.") == []
    assert sweep("2026 was the later year. The data does not cover March 2026 or fiscal 2027.") == []
    assert sweep("The 1-year and 12-month windows, the 3-month window and 5 trading days.") == []
    assert sweep("It rose over 30 days.") == ["30"]
    assert sweep("Apple has 2026 retail stores.") == ["2026"]
    # 'Nov 2' must not swallow the front of 'Nov 20'
    assert sweep("Data as of Nov 20.", allow_dates=["2026-11-02"]) == ["20"]


# ---------------------------------------------------------------- quotes nobody declared
def test_quote_not_in_the_filing_is_cut_even_when_not_declared():
    assert_cut('The 10-K says "we expect revenue to double next year."')
    assert_cut('The 10-K says "We expect strong sales. Margins will also rise sharply next year."')


def test_real_quote_passes_without_a_declared_claim():
    text = ('The fiscal 2025 filing said results depend on the ability to "obtain components in sufficient '
            'quantities".')
    res = run(text)
    assert res["answer"] == text and not res["blocked"]
    assert [c["status"] for c in res["claims"]] == ["VERIFIED"]


# ---------------------------------------------------------------- correct sentences that used to be blocked
@pytest.mark.parametrize("answer", [
    "Buybacks were 4.8% below last year.",
    "Revenue rose 15.1% while buybacks were cut 4.8%.",
    "Revenue was 15.06 per cent higher.",
    "Gross margin rose 188 bps.",
    "Gross margin rose 188 basis points.",
    "The 1-year return was 12.3%.",
    "Over the last 12 months the stock returned 12.3%.",
])
def test_correct_sentences_that_were_blocked_now_pass(answer):
    assert_kept(answer)


# ---------------------------------------------------------------- correct sentences that must keep passing
@pytest.mark.parametrize("answer", [
    # real answers from test-runs/run10-claude-after-fixes.md (market numbers swapped for this file's pack)
    "Apple's net sales in fiscal 2026 were $478.8 billion. That is up from $416.2 billion in fiscal 2025, "
    "an increase of +15.1%.",
    "Net sales grew from $416.2 billion in fiscal 2025 to $478.8 billion in fiscal 2026. That is an increase of "
    "$62.7 billion, or +15.1%.",
    "Diluted earnings per share were $8.98 per share in fiscal 2026, compared with $7.46 per share in fiscal 2025. "
    "That is an increase of $1.52 per share, or +20.4%.",
    "Gross margin as a percentage of net sales was 48.8% in fiscal 2026, compared with 46.9% in fiscal 2025. "
    "That is an increase of +1.9 percentage points.",
    "Research and development expense rose to $45.8 billion in fiscal 2026 from $34.6 billion in fiscal 2025. "
    "That is an increase of $11.2 billion, or +32.5%.",
    "Apple spent less on buybacks in fiscal 2026. Cash paid for share repurchases was $86.4 billion, compared "
    "with $90.7 billion in fiscal 2025, a decrease of $4.3 billion or 4.8%.",
    "The data here doesn't cover forecasts for fiscal 2027, so I can't say what Apple's revenue will be. The "
    "evidence only shows reported results, including net sales of $478.8 billion in fiscal 2026 and $416.2 billion "
    "in fiscal 2025.",
    "The data here doesn't cover monthly figures, so Apple's revenue for March 2026 alone isn't available. The "
    "evidence only includes annual figures, such as net sales of $478.8 billion for fiscal 2026.",
    "Apple's closing price on the last trading day (as of 2026-11-20) was $268.47. That was down from $273.67 the "
    "trading day before.",
    "Apple's stock price return was -1.6% over the past month. The last close on 2026-11-20 was $268.47. Over the "
    "past three months, the return was +10.4%.",
    "Apple's market capitalization was $3.98 trillion as of 2026-11-20, based on end-of-day market data.",
    "Apple's net sales in fiscal 2026 were $478.8 billion, up from $416.2 billion in fiscal 2025. As of 2026-11-20, "
    "the last close was $268.47, which was a one-day return of -1.9%.",
    # other natural phrasings
    "Net sales rose from $416.2 billion to $478.8 billion in fiscal 2026.",
    "Net sales were $478.8 billion in fiscal 2026, compared with $416.2 billion a year earlier.",
    "In fiscal 2026 and fiscal 2025, net sales were $478.8 billion and $416.2 billion, respectively.",
    "Fiscal 2026 net sales of $478.8 billion compare with fiscal 2025 net sales of $416.2 billion.",
    "Earnings were $8.98 per share.",
    "Net income rose 18.0%, on $478.8 billion of revenue.",
    "Revenue rose to $478.8 billion (15.1%).",
    "Buybacks fell to $86.4 billion in fiscal 2026.",
    "EPS grew faster than net income: 20.4% versus 18.0%.",
    "The stock closed at $268.47 on November 20, 2026, below its 52-week high of $288.62 and above its 52-week "
    "low of $169.21.",
    "Apple's market cap is $4 trillion.",
    "The stock opened at $271.10 and closed at $268.47.",
    "The 52-week range is $169.21 to $288.62.",
    "Apple shares traded between $169.21 and $288.62 in their 52-week range.",
])
def test_correct_sentences_keep_passing(answer):
    assert_kept(answer)


def test_cited_fact_still_wins_and_binding_reports_a_mismatch():
    res = checker.check("AAPL", "R&D rose 15.1% in fiscal 2026.", [{"fact_id": "revenue_change_pct", "value": "15.1%"}])
    assert res["answer"] == "" and [c["status"] for c in res["claims"]] == ["MISMATCH"]
    assert "Net sales" in res["claims"][0]["note"]


# ---------------------------------------------------------------- skeptic must know which company the sheets are for
def test_skeptic_is_told_which_company_the_evidence_is_for(monkeypatch):
    seen = {}

    def fake(models, system, human, config=None, need_key=None):
        seen["human"], seen["system"] = human, system
        return {"verdicts": [{"i": 1, "verdict": "SUPPORTED", "why": ""}]}, "m"

    monkeypatch.setattr(agents, "call_json", fake)
    out = agents.review({"ticker": "AAPL", "company": "Apple Inc.", "question": "What is MSFT's latest price?",
                         "sheets": ["px_close_last | Closing price | $342.56"],
                         "sentences": ["The data here covers only Apple (AAPL)."]})
    assert out["status"] == "ok"
    assert "Apple Inc. (AAPL)" in seen["human"].split("EVIDENCE SHEET")[0]
    assert "only" in seen["system"] and "another company" in seen["system"]


def test_desk_passes_ticker_and_company_to_the_skeptic():
    from langchain_core.runnables import RunnableLambda
    seen = {}

    def skeptic(inp):
        seen.update(inp)
        return {"status": "ok", "verdicts": [], "model": "m"}

    deps = desk.Deps(
        guard=desk.GUARD,
        router=RunnableLambda(lambda i: {"specialists": ["filings"], "advice": False, "reason": "", "model": "m",
                                         "fallback": False}),
        specialists={"filings": RunnableLambda(lambda i: FILINGS)},
        news_picker=RunnableLambda(lambda i: {"ids": [], "model": None}),
        writer=RunnableLambda(lambda i: {"draft": {"status": "ANSWERED", "answer": "Net sales were $478.8 billion.",
                                                   "claims": []}, "model": "m"}),
        skeptic=RunnableLambda(skeptic), gate=gate.GATE)
    out = desk.answer("AAPL", "What were net sales?", deps)
    assert out["status"] == "ANSWERED"
    assert seen["ticker"] == "AAPL" and seen["company"] == "Apple Inc."
