"""Scenario arithmetic: each function against hand-computed numbers, the grid's shape, the facts
it adds, and the rule that it informs and never advises (no per-share value, no opinion words)."""
import json
import math
import re
from datetime import date, timedelta

import pytest

from backend import format as fmt
from backend.analysis import ratios, scenarios
from backend.ledger import Fact, Ledger, Source

K24 = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24.htm",
             title="Form 10-K, filed 2025-02-01", date="2025-02-01")
YE, PRIOR_YE = "2024-12-31", "2023-12-31"
ENDS = {"FY2024": YE, "FY2023": PRIOR_YE, "FY2022": "2022-12-31", "FY2021": "2021-12-31",
        "FY2020": "2020-12-31"}

# revenue rises 10% a year from FY2022 (1210 -> 1331 -> 1464.1), so the 2-year rate is easy to check
BASE = {
    ("revenue", "FY2024"): 1464.1, ("revenue", "FY2023"): 1331.0, ("revenue", "FY2022"): 1210.0,
    ("revenue", "FY2021"): 1150.0, ("revenue", "FY2020"): 1100.0,
    ("operating_income", "FY2024"): 230.0,
    ("operating_cash_flow", "FY2024"): 310.0, ("capex", "FY2024"): 45.0,       # FCF 265
    ("long_term_debt", YE): 780.0, ("long_term_debt", PRIOR_YE): 820.0,      # average 800
    ("cash", YE): 200.0,                                                     # net debt 580
    ("shareholders_equity", YE): 520.0,
}
DEBT_COST = {("interest_expense", "FY2024"): 32.0,                           # 32 / 800 = 4%
             ("income_tax_expense", "FY2024"): 25.0, ("pretax_income", "FY2024"): 125.0}  # 20%

BANNED = ("undervalued", "overvalued", "upside", "target", "fair value", "buy", "sell")


def _ledger(values=None, *, ends=ENDS, extra=None):
    ledger = Ledger()
    sid = ledger.add_source(K24)
    for (key, period), value in {**(BASE if values is None else values), **(extra or {})}.items():
        ledger.add_fact(Fact(key=key, period=period, value=value, unit="USD", source_ids=(sid,)))
    for period, end in (ends or {}).items():
        ledger.set_period_end(period, end)
    return ledger


def _without(*refs):
    return {k: v for k, v in BASE.items() if k not in refs}


def _visible_strings(obj):
    """Every string in the result with HTML tags removed (a link's target="_blank" attribute is
    markup, not text the reader sees)."""
    if isinstance(obj, str):
        yield re.sub(r"<[^>]+>", " ", obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _visible_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _visible_strings(v)


# ---- revenue growth ------------------------------------------------------------------------------
def test_growth_blend_with_positional_years():
    ledger = _ledger(ends=None)
    short = (1464.1 / 1210.0) ** (1 / 2) - 1          # 0.10
    long = (1464.1 / 1100.0) ** (1 / 4) - 1           # 1.331 ^ 0.25 - 1
    assert short == pytest.approx(0.10)
    assert scenarios.revenue_growth_estimate(ledger) == pytest.approx(0.6 * short + 0.4 * long)


def test_growth_blend_uses_the_period_end_dates():
    ledger = _ledger()
    short = (1464.1 / 1210.0) ** (365.25 / 731) - 1   # 2022-12-31 -> 2024-12-31 is 731 days
    long = (1464.1 / 1100.0) ** (365.25 / 1461) - 1   # 1461 days = exactly 4.0 years
    assert scenarios.revenue_growth_estimate(ledger) == pytest.approx(0.6 * short + 0.4 * long)


def test_growth_uses_the_one_rate_there_is():
    ledger = _ledger(_without(("revenue", "FY2020")), ends=None)
    assert scenarios.revenue_growth_estimate(ledger) == pytest.approx(0.10)
    # a non-positive older revenue refuses the 2-year rate; the 4-year one is used alone
    ledger = _ledger({**BASE, ("revenue", "FY2022"): -5.0}, ends=None)
    assert scenarios.revenue_growth_estimate(ledger) == pytest.approx((1464.1 / 1100.0) ** 0.25 - 1)


def test_growth_falls_back_to_the_year_on_year_mean():
    values = {("revenue", "FY2024"): 1464.1, ("revenue", "FY2023"): 1331.0}
    assert scenarios.revenue_growth_estimate(_ledger(values, ends=None)) == pytest.approx(0.10)


def test_growth_refuses_misordered_dates_and_missing_history():
    ends = {**ENDS, "FY2022": "2025-06-30"}           # FY2022 "ends" after FY2024
    ledger = _ledger(_without(("revenue", "FY2020"), ("revenue", "FY2021"), ("revenue", "FY2023")),
                     ends=ends)
    assert scenarios.revenue_growth_estimate(ledger) is None
    assert scenarios.revenue_growth_estimate(_ledger({("revenue", "FY2024"): 10.0})) is None
    assert scenarios.revenue_growth_estimate(Ledger()) is None


def test_growth_estimate_adds_nothing():
    ledger = _ledger()
    before = ledger.to_json()
    scenarios.revenue_growth_estimate(ledger)
    assert ledger.to_json() == before


# ---- beta ------------------------------------------------------------------------------------
def _market(n, start=date(2024, 1, 2)):
    closes, c = [], 100.0
    returns = [0.01 * math.sin(i) + 0.002 * ((i * 7) % 5 - 2) for i in range(n - 1)]
    closes.append(c)
    for r in returns:
        c *= 1 + r
        closes.append(c)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n)]
    return dates, closes, returns


def _bars(dates, closes):
    return [{"date": d, "close": c} for d, c in zip(dates, closes)]


def _scaled_stock(dates, returns, k):
    closes, c = [50.0], 50.0
    for r in returns:
        c *= 1 + k * r
        closes.append(c)
    return _bars(dates, closes)


def test_beta_of_exactly_twice_the_market_is_two():
    dates, closes, returns = _market(121)
    market = _bars(dates, closes)
    assert scenarios.beta_from_bars(_scaled_stock(dates, returns, 2.0), market) == pytest.approx(2.0, abs=1e-9)


def test_beta_is_clipped_like_the_original():
    dates, closes, returns = _market(121)
    market = _bars(dates, closes)
    assert scenarios.beta_from_bars(_scaled_stock(dates, returns, 3.0), market) == 2.5
    assert scenarios.beta_from_bars(_scaled_stock(dates, returns, 0.1), market) == 0.3


def test_beta_needs_sixty_aligned_returns():
    dates, closes, returns = _market(61)              # 61 shared closes -> 60 returns
    market = _bars(dates, closes)
    stock = _scaled_stock(dates, returns, 1.5)
    assert scenarios.beta_from_bars(stock, market) == pytest.approx(1.5, abs=1e-9)
    assert scenarios.beta_from_bars(stock[:60], market) is None       # 59 returns
    assert scenarios.beta_from_bars(stock, market[:30]) is None
    assert scenarios.beta_from_bars([], market) is None


def test_beta_aligns_by_date():
    dates, closes, returns = _market(121)
    market = _bars(dates, closes)
    stock = _scaled_stock(dates, returns, 2.0)
    # days only the stock traded, with wild closes: not shared, so not used
    odd = [{"date": f"2023-0{m}-15", "close": 999.0 * m} for m in range(1, 10)]
    assert scenarios.beta_from_bars(odd + stock, market) == pytest.approx(2.0, abs=1e-9)
    # a market holiday: one date missing from the market; both returns then span the same two days
    assert scenarios.beta_from_bars(stock, market[:50] + market[51:]) == pytest.approx(2.0, abs=0.01)


def test_beta_of_a_flat_market_is_none():
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(100)]
    market = _bars(dates, [100.0] * 100)
    stock = _bars(dates, [50.0 + i for i in range(100)])
    assert scenarios.beta_from_bars(stock, market) is None


# ---- cost of equity --------------------------------------------------------------------------
def test_cost_of_equity_capm_and_floor():
    assert scenarios.cost_of_equity(0.043, 1.2, 0.05) == pytest.approx(0.103)
    assert scenarios.cost_of_equity(0.043, None, 0.05) == pytest.approx(0.093)       # beta 1.0
    assert scenarios.cost_of_equity(0.043, None) == pytest.approx(0.093)             # ERP default 5%
    # 0.043 + 0.3 x 0.05 = 5.8% is under the floor max(4%, 4.3% + 2.5%) = 6.8%
    assert scenarios.cost_of_equity(0.043, 0.3, 0.05) == pytest.approx(0.068)
    # 1% + 0.3 x 5% = 2.5% is under max(4%, 3.5%) = 4%
    assert scenarios.cost_of_equity(0.01, 0.3, 0.05) == pytest.approx(0.04)


# ---- WACC ------------------------------------------------------------------------------------
def test_wacc_with_market_weights_and_filed_costs():
    ledger = _ledger(extra=DEBT_COST)
    before = ledger.to_json()
    rate, detail = scenarios.wacc(ledger, 2024, cost_of_equity=0.093, market_cap=3120.0)
    # E 3120, D 780 -> 80% / 20%; Kd 32 / 800 = 4%; t 25 / 125 = 20%; after tax 3.2%
    assert rate == pytest.approx(0.8 * 0.093 + 0.2 * 0.032)
    assert detail["method"] == "weighted" and detail["reason"] is None
    assert detail["pre_tax_cost_of_debt"] == pytest.approx(0.04)
    assert detail["tax_rate"] == pytest.approx(0.20) and detail["tax_basis"] == "effective"
    assert detail["equity_weight"] == pytest.approx(0.8) and detail["debt_weight"] == pytest.approx(0.2)
    assert {f.key for f in detail["facts"]} == {"pre_tax_cost_of_debt", "effective_tax_rate"}
    assert ledger.to_json() == before                 # wacc itself adds nothing


def test_wacc_with_book_weights():
    ledger = _ledger(extra=DEBT_COST)
    rate, detail = scenarios.wacc(ledger, 2024, cost_of_equity=0.093, market_cap=None)
    # E 520, D 780 -> 40% / 60%
    assert rate == pytest.approx(0.4 * 0.093 + 0.6 * 0.032)
    assert detail["equity_basis"] == "book equity at the fiscal year end"
    assert detail["equity_ref"] == ("shareholders_equity", YE)


def test_wacc_statutory_tax_when_no_effective_rate_is_filed():
    ledger = _ledger(extra={("interest_expense", "FY2024"): 32.0})
    rate, detail = scenarios.wacc(ledger, 2024, cost_of_equity=0.093, market_cap=3120.0)
    assert rate == pytest.approx(0.8 * 0.093 + 0.2 * 0.04 * (1 - 0.21))
    assert detail["tax_basis"] == "statutory" and "not in the sources" in detail["tax_reason"]


def test_wacc_year_end_debt_when_no_prior_balance():
    ledger = _ledger(_without(("long_term_debt", PRIOR_YE)), extra=DEBT_COST)
    _rate, detail = scenarios.wacc(ledger, 2024, cost_of_equity=0.093, market_cap=None)
    assert detail["pre_tax_cost_of_debt"] == pytest.approx(32.0 / 780.0)


@pytest.mark.parametrize("values,extra,market_cap,word", [
    (BASE, None, 3120.0, "interest expense"),                                      # no interest
    (_without(("long_term_debt", YE)), DEBT_COST, 3120.0, "long-term debt"),       # no debt
    ({**BASE, ("shareholders_equity", YE): -10.0}, DEBT_COST, None, "book equity"),  # negative book
])
def test_wacc_falls_back_to_the_cost_of_equity_and_says_why(values, extra, market_cap, word):
    rate, detail = scenarios.wacc(_ledger(values, extra=extra), 2024, cost_of_equity=0.093,
                                  market_cap=market_cap)
    assert rate == pytest.approx(0.093)
    assert detail["method"] == "cost_of_equity_only"
    assert word in detail["reason"]


# ---- the projection --------------------------------------------------------------------------
def test_two_stage_dcf_matches_a_hand_number():
    # growth = discount = 10%: each year's present value is 100, so 5 x 100 = 500; the terminal
    # value 100 x 1.1^5 x 1.02 / 0.08 x 0.95, discounted 5 years, is 100 x 1.02 / 0.08 x 0.95
    assert scenarios.two_stage_dcf(100.0, 0.10, 0.10, 0.02) == pytest.approx(500 + 1211.25)


def test_two_stage_dcf_second_stage_fades_to_the_midpoint():
    # years 6 and 7 grow at (10% + 2%) / 2 = 6%
    pv6 = 100 * 1.06 / 1.1
    pv7 = 100 * 1.06 ** 2 / 1.1 ** 2
    terminal = pv7 * 1.02 / 0.08 * 0.95
    assert scenarios.two_stage_dcf(100.0, 0.10, 0.10, 0.02, years=7) == pytest.approx(500 + pv6 + pv7 + terminal)


def test_two_stage_dcf_haircut_is_a_parameter():
    assert scenarios.two_stage_dcf(100.0, 0.10, 0.10, 0.02, terminal_haircut=1.0) == pytest.approx(500 + 1275.0)


@pytest.mark.parametrize("args", [
    (100.0, 0.05, 0.02, 0.02),        # discount = terminal growth
    (100.0, 0.05, 0.01, 0.02),        # discount below terminal growth
    (0.0, 0.05, 0.09, 0.02),          # no free cash flow
    (-50.0, 0.05, 0.09, 0.02),        # negative free cash flow
    (100.0, float("nan"), 0.09, 0.02),
])
def test_two_stage_dcf_none_cases(args):
    assert scenarios.two_stage_dcf(*args) is None


def test_two_stage_dcf_needs_a_year():
    assert scenarios.two_stage_dcf(100.0, 0.05, 0.09, 0.02, years=0) is None


# ---- compute ---------------------------------------------------------------------------------
def _computed_ledger(**kw):
    ledger = _ledger(**kw)
    ratios.compute(ledger)
    return ledger


def test_compute_shape_and_cells():
    ledger = _computed_ledger()
    out = scenarios.compute(ledger)
    assert out["title"] == "Scenario arithmetic"
    assert out["columns"] == ["terminal growth 1.5%", "2.0%", "2.5%"]
    # no interest expense in the ledger: the discount rate is the cost of equity, 4.3% + 1.0 x 5%
    assert [r["label"] for r in out["rows"]] == ["discount rate 8.3%", "discount rate 9.3%",
                                                 "discount rate 10.3%"]
    g = scenarios.revenue_growth_estimate(ledger)
    for row, r in zip(out["rows"], (0.083, 0.093, 0.103)):
        assert len(row["cells"]) == 3
        for cell, tg in zip(row["cells"], (0.015, 0.02, 0.025)):
            ev = scenarios.two_stage_dcf(265.0, g, r, tg, years=7)
            assert cell == fmt.fact(Fact(key="x", period="FY2024", value=ev, unit="USD"))
            assert re.fullmatch(r"\$\d[\d,]*(\.\d)?( (million|billion|trillion))?", cell)
            assert "per share" not in cell.lower()
    assert "Arithmetic under stated assumptions, not an opinion of value." in out["note"]
    # the note is plain text (the renderer escapes it): net debt as text, its link in the assumptions
    assert "Net debt: $580 as of 31 Dec 2024" in out["note"]
    assert not re.search(r"[<>&'\"]", out["note"])
    labels = [a["label"] for a in out["assumptions"]]
    for wanted in ("Risk-free rate", "Equity risk premium", "Beta", "Cost of equity",
                   "Discount rate", "Revenue growth", "Terminal growth"):
        assert wanted in labels
    by_label = {a["label"]: a["value_html"] for a in out["assumptions"]}
    for plain in ("Risk-free rate", "Equity risk premium", "Terminal growth", "Beta"):
        assert "assumption" in by_label[plain]
    assert by_label["Risk-free rate"].startswith("4.3%")
    assert 'href="#calc-revenue_growth_estimate-FY2024"' in by_label["Revenue growth"]
    assert 'href="#calc-free_cash_flow-FY2024"' in by_label["Base free cash flow"]
    assert 'href="#calc-net_debt-FY2024"' in by_label["Net debt"]
    assert "cost of equity alone" in by_label["Discount rate"] and "interest expense" in by_label["Discount rate"]


def test_compute_adds_computed_facts_with_inputs_in_the_ledger():
    ledger = _computed_ledger()
    scenarios.compute(ledger)
    expected = {"revenue_cagr_2y": (1464.1 / 1210.0) ** (365.25 / 731) - 1,
                "revenue_cagr_4y": (1464.1 / 1100.0) ** 0.25 - 1,
                "net_debt": 780.0 - 200.0}
    for key, value in expected.items():
        f = ledger.get(key, "FY2024")
        assert f is not None and f.is_computed and f.value == pytest.approx(value)
        assert all(ledger.get(*ref) is not None for ref in f.inputs)
        assert ledger.cite(f) and all(s.url.startswith("https://") for s in ledger.cite(f))
    assert ledger.get("net_debt", "FY2024").inputs == (("long_term_debt", YE), ("cash", YE))
    est = ledger.get("revenue_growth_estimate", "FY2024")
    assert est.formula == "0.6 x revenue_cagr_2y + 0.4 x revenue_cagr_4y"
    assert est.inputs == (("revenue_cagr_2y", "FY2024"), ("revenue_cagr_4y", "FY2024"))
    # no debt-cost facts without their inputs
    assert ledger.get("pre_tax_cost_of_debt", "FY2024") is None
    # the ledger still round-trips (from_json re-adds inputs first, so compare without order)
    again = Ledger.from_json(json.loads(json.dumps(ledger.to_json())))
    order = lambda facts: sorted(facts, key=lambda f: (f.key, f.period))  # noqa: E731
    assert order(again.facts()) == order(ledger.facts())


def test_compute_weighted_discount_rate():
    ledger = _computed_ledger(extra=DEBT_COST)
    out = scenarios.compute(ledger, market_cap=3120.0)
    # 0.8 x 9.3% + 0.2 x 4% x (1 - 20%) = 8.08%
    assert [r["label"] for r in out["rows"]] == ["discount rate 7.1%", "discount rate 8.1%",
                                                 "discount rate 9.1%"]
    assert ledger.get("pre_tax_cost_of_debt", "FY2024").value == pytest.approx(0.04)
    assert ledger.get("effective_tax_rate", "FY2024").value == pytest.approx(0.20)
    discount = {a["label"]: a["value_html"] for a in out["assumptions"]}["Discount rate"]
    assert discount.startswith("8.1% (weighted")
    assert 'href="#calc-pre_tax_cost_of_debt-FY2024"' in discount
    assert 'href="#calc-effective_tax_rate-FY2024"' in discount
    assert "market capitalisation" in discount and "(market data)" in discount


def test_compute_beta_supplied_clipped_and_the_floor():
    ledger = _computed_ledger()
    out = scenarios.compute(ledger, beta=3.0)
    by_label = {a["label"]: a["value_html"] for a in out["assumptions"]}
    assert by_label["Beta"].startswith("2.50 against the market index (market data")
    assert by_label["Cost of equity"].startswith("16.8%")          # 4.3% + 2.5 x 5%
    out = scenarios.compute(ledger, beta=0.3)
    by_label = {a["label"]: a["value_html"] for a in out["assumptions"]}
    assert by_label["Cost of equity"].startswith("6.8% (the floor")
    assert out["rows"][1]["label"] == "discount rate 6.8%"


def test_compute_bounds_growth_and_labels_the_no_history_assumption():
    fast = {**BASE, ("revenue", "FY2022"): 400.0, ("revenue", "FY2020"): 100.0}
    ledger = _computed_ledger(values=fast)
    out = scenarios.compute(ledger)
    growth = {a["label"]: a["value_html"] for a in out["assumptions"]}["Revenue growth"]
    assert "bounded to 25.0% for the projection" in growth
    g_used = 0.25
    assert out["rows"][1]["cells"][1] == fmt.fact(Fact(key="x", period="FY2024", unit="USD",
                                                       value=scenarios.two_stage_dcf(265.0, g_used, 0.093, 0.02, years=7)))
    single = {k: v for k, v in BASE.items() if k[0] != "revenue" or k[1] == "FY2024"}
    ledger = _computed_ledger(values=single)
    out = scenarios.compute(ledger)
    growth = {a["label"]: a["value_html"] for a in out["assumptions"]}["Revenue growth"]
    assert growth.startswith("3.0% (assumption")
    assert ledger.get("revenue_growth_estimate", "FY2024") is None


def test_compute_runs_twice():
    ledger = _computed_ledger(extra=DEBT_COST)
    first = scenarios.compute(ledger, market_cap=3120.0)
    assert scenarios.compute(ledger, market_cap=3120.0) == first


def test_compute_never_advises_and_never_prices_a_share():
    for kwargs in ({}, {"market_cap": 3120.0, "beta": 1.4}):
        ledger = _computed_ledger(extra=DEBT_COST)
        out = scenarios.compute(ledger, **kwargs)
        for text in _visible_strings(out):
            low = text.lower()
            assert "per share" not in low
            for word in BANNED:
                assert word not in low, (word, text)


def test_compute_none_without_positive_free_cash_flow():
    for values in (_without(("operating_cash_flow", "FY2024")),
                   {**BASE, ("operating_cash_flow", "FY2024"): 30.0}):      # FCF 30 - 45 < 0
        ledger = _computed_ledger(values=values)
        before = ledger.to_json()
        assert scenarios.compute(ledger) is None
        assert ledger.to_json() == before
    assert scenarios.compute(Ledger()) is None


def test_compute_without_net_debt_says_so():
    ledger = _computed_ledger(values=_without(("cash", YE)))
    out = scenarios.compute(ledger)
    assert "Net debt: Not available in the sources" in out["note"]
    assert ledger.get("net_debt", "FY2024") is None
    assert "Net debt" not in [a["label"] for a in out["assumptions"]]


def test_grid_cell_too_close_to_terminal_growth_is_na():
    ledger = _computed_ledger()
    out = scenarios.compute(ledger, risk_free=0.01, equity_risk_premium=0.02)   # floor 4%
    # discount 4% - 1 point = 3%: exactly 1.5 points above 1.5% (kept), less above 2.0% and 2.5%
    assert out["rows"][0]["label"] == "discount rate 3.0%"
    first, *rest = out["rows"][0]["cells"]
    assert first.startswith("$")
    assert all(c.startswith("n/a") for c in rest)
    assert all(c.startswith("$") for c in out["rows"][1]["cells"])


# ---- bear / base / bull --------------------------------------------------------------------------
def test_case_inputs_follow_the_original_rules():
    c = scenarios.case_inputs(0.08, 0.18)
    assert c["bull"]["growth"] == pytest.approx(0.10) and c["bull"]["margin"] == pytest.approx(0.19)
    assert c["bear"]["growth"] == pytest.approx(0.06) and c["bear"]["margin"] == pytest.approx(0.17)
    assert c["base"] == {"growth": 0.08, "margin": 0.18}
    # the bear cut stops at -5%, and a rate already below -5% is not cut (never raised either)
    assert scenarios.case_inputs(-0.04, 0.1)["bear"]["growth"] == pytest.approx(-0.05)
    assert scenarios.case_inputs(-0.08, 0.1)["bear"]["growth"] == pytest.approx(-0.08)
    assert scenarios.case_inputs(0.25, 0.1)["bull"]["growth"] == pytest.approx(0.27)
    # margins: +1 point to at most 30%, never below the base; -1 point with a 1% floor, never above
    assert scenarios.case_inputs(0.05, 0.295)["bull"]["margin"] == pytest.approx(0.30)
    assert scenarios.case_inputs(0.05, 0.40)["bull"]["margin"] == pytest.approx(0.40)
    assert scenarios.case_inputs(0.05, 0.40)["bear"]["margin"] == pytest.approx(0.39)
    assert scenarios.case_inputs(0.05, 0.015)["bear"]["margin"] == pytest.approx(0.01)
    assert scenarios.case_inputs(0.05, 0.005)["bear"]["margin"] == pytest.approx(0.005)
    assert scenarios.case_inputs(0.05, None)["bull"]["margin"] is None


@pytest.mark.parametrize("g", [-0.10, -0.06, -0.05, -0.035, 0.0, 0.03, 0.12, 0.25])
@pytest.mark.parametrize("m", [None, 0.005, 0.012, 0.1, 0.295, 0.31, 0.6])
def test_case_inputs_keep_bear_below_base_below_bull(g, m):
    c = scenarios.case_inputs(g, m)
    assert c["bear"]["growth"] <= c["base"]["growth"] <= c["bull"]["growth"]
    if m is not None:
        assert c["bear"]["margin"] <= c["base"]["margin"] <= c["bull"]["margin"]


def test_compute_cases_shape_and_hand_numbers():
    ledger = _computed_ledger()
    out = scenarios.compute(ledger)
    cases = out["cases"]
    assert [c["key"] for c in cases] == ["bear", "base", "bull"]
    assert [c["label"] for c in cases] == ["Bear case", "Base case", "Bull case"]
    fields = {"key", "label", "growth", "growth_text", "fcf_margin", "fcf_margin_text", "assumption",
              "low", "base", "high", "low_text", "base_text", "high_text"}
    assert all(set(c) == fields for c in cases)
    bear, base, bull = cases
    g = scenarios.revenue_growth_estimate(ledger)
    assert base["growth"] == pytest.approx(g)
    assert bear["growth"] == pytest.approx(g - 0.02) and bull["growth"] == pytest.approx(g + 0.02)
    assert bear["growth"] <= base["growth"] <= bull["growth"]
    # the base case is the grid's middle cell; low / high are the discount rate +1 / -1 point
    assert base["base_text"] == out["rows"][1]["cells"][1]
    assert base["low_text"] == out["rows"][2]["cells"][1] and base["high_text"] == out["rows"][0]["cells"][1]
    # bull: FCF = revenue x (margin + 1 point) = 265 + 14.641; bear: 265 - 14.641
    assert bull["base"] == pytest.approx(scenarios.two_stage_dcf(279.641, g + 0.02, 0.093, 0.02, years=7))
    assert bear["base"] == pytest.approx(scenarios.two_stage_dcf(250.359, g - 0.02, 0.093, 0.02, years=7))
    assert bull["fcf_margin"] == pytest.approx(265 / 1464.1 + 0.01)
    for c in cases:
        assert c["low"] <= c["base"] <= c["high"]
        assert c["base_text"] == fmt.fact(Fact(key="x", period="FY2024", value=c["base"], unit="USD"))
        assert c["growth_text"].endswith("%") and c["assumption"].endswith(".")
        assert not re.search(r"[<>&'\"]", c["assumption"])
    assert bear["base"] <= base["base"] <= bull["base"]
    assert "plus two points" in bull["assumption"] and "less up to two points" in bear["assumption"]


def test_cases_none_under_the_spread_rule():
    ledger = _computed_ledger()
    out = scenarios.compute(ledger, risk_free=0.01, equity_risk_premium=0.02)  # discount 4%
    for c in out["cases"]:
        # 4% - 1 point = 3% is less than 1.5 points above 2.0% terminal growth
        assert c["high"] is None and c["high_text"] is None
        assert c["base"] is not None and c["low"] is not None and c["low"] <= c["base"]


def test_cases_hold_the_margin_without_revenue():
    ledger = _computed_ledger(values=_without(("revenue", "FY2024")))
    cases = scenarios.compute(ledger)["cases"]
    assert all(c["fcf_margin"] is None and c["fcf_margin_text"] is None for c in cases)
    assert "held at the base" in cases[0]["assumption"] and "held at the base" in cases[2]["assumption"]
    # growth still comes from history: the year-on-year rates FY2021-FY2023 (the original's fallback)
    assert "historical" in cases[1]["assumption"]
    assert cases[0]["base"] < cases[1]["base"] < cases[2]["base"]  # growth alone moves them


# ---- the market reference ----------------------------------------------------------------------
def test_market_reference_with_and_without_a_market_cap():
    out = scenarios.compute(_computed_ledger(), market_cap=3120.0)
    assert out["market"] == {"enterprise_value": pytest.approx(3120.0 + 580.0), "text": "$3,700",
                             "note": "Market capitalisation (as given) plus net debt", "reason": None}
    out = scenarios.compute(_computed_ledger())
    assert out["market"] == {"enterprise_value": None, "text": None,
                             "note": "Market capitalisation (as given) plus net debt",
                             "reason": "No market enterprise value is drawn: no market capitalisation was available."}
    out = scenarios.compute(_computed_ledger(values=_without(("cash", YE))), market_cap=3120.0)
    assert out["market"]["enterprise_value"] is None and out["market"]["text"] is None
    assert out["market"]["reason"].startswith("No market enterprise value is drawn: net debt is not available")


def test_market_reference_is_a_value_only():
    out = scenarios.compute(_computed_ledger(), market_cap=3120.0)
    assert set(out["market"]) == {"enterprise_value", "text", "note", "reason"}
    assert "%" not in out["market"]["text"] + out["market"]["note"]
    # nothing anywhere relates a case to the market figure
    for text in _visible_strings({k: v for k, v in out.items() if k != "assumptions"}):
        low = text.lower()
        for word in BANNED + ("difference", "premium to", "discount to", "implied upside"):
            assert word not in low, (word, text)


# ---- the discount rate on live metrics ----------------------------------------------------------
def _entry(val, end, start=None):
    e = {"end": end, "val": val, "accn": "0000000001-25-000001", "fy": 2024, "fp": "FY",
         "form": "10-K", "filed": "2025-02-01"}
    if start:
        e["start"] = start
    return e


def _company_facts(with_debt_costs=True):
    fy = ("2024-01-01", "2024-12-31")
    flows = {"Revenues": 1464.1, "NetCashProvidedByUsedInOperatingActivities": 310.0,
             "PaymentsToAcquirePropertyPlantAndEquipment": 45.0, "OperatingIncomeLoss": 230.0}
    if with_debt_costs:
        flows.update({"InterestExpense": 31.2, "IncomeTaxExpenseBenefit": 25.0,
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 125.0})
    balances = {"LongTermDebt": 780.0, "CashAndCashEquivalentsAtCarryingValue": 200.0,
                "StockholdersEquity": 520.0}
    gaap = {tag: {"units": {"USD": [_entry(v, fy[1], fy[0])]}} for tag, v in flows.items()}
    gaap.update({tag: {"units": {"USD": [_entry(v, fy[1])]}} for tag, v in balances.items()})
    return {"cik": 1, "entityName": "Test Co", "facts": {"us-gaap": gaap}}


def _live_ledger(with_debt_costs=True):
    from backend.facts import select
    ledger = Ledger()
    summary = select.statement_facts(_company_facts(with_debt_costs), [], ledger, cik="0000000001")
    ratios.compute(ledger)
    return ledger, summary


def test_wacc_from_the_new_metrics():
    ledger, summary = _live_ledger()
    assert summary["tags"]["interest_expense"] == "us-gaap:InterestExpense"
    assert summary["tags"]["income_tax_expense"] == "us-gaap:IncomeTaxExpenseBenefit"
    assert summary["tags"]["pretax_income"].startswith("us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes")
    out = scenarios.compute(ledger, market_cap=3120.0)
    # Kd = 31.2 / 780 = 4% (no prior year end), t = 25 / 125 = 20%: 0.8 x 9.3% + 0.2 x 3.2% = 8.08%
    assert out["rows"][1]["label"] == "discount rate 8.1%"
    assert ledger.get("pre_tax_cost_of_debt", "FY2024").value == pytest.approx(0.04)
    assert ledger.get("effective_tax_rate", "FY2024").value == pytest.approx(0.20)
    discount = {a["label"]: a["value_html"] for a in out["assumptions"]}["Discount rate"]
    assert discount.startswith("8.1% (weighted")


def test_without_the_new_tags_the_rate_is_the_cost_of_equity_with_its_reason():
    ledger, summary = _live_ledger(with_debt_costs=False)
    assert {"interest_expense", "income_tax_expense", "pretax_income"} <= set(summary["metrics_missing"])
    out = scenarios.compute(ledger, market_cap=3120.0)
    assert out["rows"][1]["label"] == "discount rate 9.3%"
    discount = {a["label"]: a["value_html"] for a in out["assumptions"]}["Discount rate"]
    assert "cost of equity alone" in discount and "interest expense is not reported as its own figure" in discount


def test_an_implausible_cost_of_debt_is_not_used():
    ledger = _ledger(extra={**DEBT_COST, ("interest_expense", "FY2024"): 200.0})   # 25% of debt
    rate, detail = scenarios.wacc(ledger, 2024, cost_of_equity=0.093, market_cap=3120.0)
    assert rate == pytest.approx(0.093) and detail["method"] == "cost_of_equity_only"
    assert "more than 15.0% of long-term debt" in detail["reason"]


# ---- review round: short-term investments, the floor, no internal wording ------------------------
def test_net_debt_with_short_term_investments_and_a_net_cash_company():
    ledger = _computed_ledger(extra={("short_term_investments", YE): 900.0})
    out = scenarios.compute(ledger, market_cap=3120.0)
    nd = ledger.get("net_debt", "FY2024")
    assert nd.value == pytest.approx(780.0 - 200.0 - 900.0)               # 320 of net cash
    assert nd.inputs == (("long_term_debt", YE), ("cash", YE), ("short_term_investments", YE))
    assert nd.formula == "long_term_debt - cash - short_term_investments at year end"
    assert out["market"]["enterprise_value"] == pytest.approx(3120.0 - 320.0)   # below the market cap
    by_label = {a["label"]: a["value_html"] for a in out["assumptions"]}
    assert "long-term debt less cash and short-term investments" in by_label["Net debt"]
    assert "Net debt: -$320 as of 31 Dec 2024 (long-term debt less cash and short-term investments" in out["note"]


def test_net_debt_without_short_term_investments_keeps_two_inputs():
    ledger = _computed_ledger()
    scenarios.compute(ledger)
    nd = ledger.get("net_debt", "FY2024")
    assert nd.inputs == (("long_term_debt", YE), ("cash", YE)) and nd.formula == "long_term_debt - cash at year end"
    assert "only cash is subtracted" in nd.note


def test_weighted_rate_below_the_cost_of_equity_floor_says_why():
    # beta 0.30: CAPM 5.8% is under the 6.8% floor, so the cost of equity is 6.8%; with cheap debt
    # the weighted rate is 0.8 x 6.8% + 0.2 x 3.2% = 6.08%, below the floor
    out = scenarios.compute(_computed_ledger(extra=DEBT_COST), market_cap=3120.0, beta=0.3)
    by_label = {a["label"]: a["value_html"] for a in out["assumptions"]}
    assert by_label["Cost of equity"].startswith("6.8% (the floor")
    assert by_label["Discount rate"].startswith("6.1% (weighted")
    assert "the weighted rate is below the cost of equity because debt is cheaper" in by_label["Discount rate"]
    assert "debt is cheaper than equity, so rows can sit under the 6.8% cost-of-equity floor" in out["note"]


def test_a_grid_row_under_the_floor_is_called_a_sensitivity():
    out = scenarios.compute(_computed_ledger(), beta=0.3)                 # cost of equity alone, 6.8%
    assert [r["label"] for r in out["rows"]][0] == "discount rate 5.8%"
    assert "The row at 5.8% is under the 6.8% cost-of-equity floor and is shown as a sensitivity only." in out["note"]
    out = scenarios.compute(_computed_ledger())                          # 8.3% lowest row: no sentence
    assert "floor" not in out["note"]


def test_no_output_names_the_original_product():
    fast = {**BASE, ("revenue", "FY2022"): 400.0, ("revenue", "FY2020"): 100.0}
    single = {k: v for k, v in BASE.items() if k[0] != "revenue" or k[1] == "FY2024"}
    for kw in ({}, {"values": fast}, {"values": single}, {"extra": DEBT_COST}):
        ledger = _computed_ledger(**kw)
        for out in (scenarios.compute(ledger), scenarios.compute(ledger, market_cap=3120.0, beta=0.3)):
            for text in _visible_strings(out):
                assert "original" not in text.lower(), text
