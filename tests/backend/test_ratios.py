"""Ratios are computed facts: hand-checked values, formulas and inputs, None with a reason."""
import json
from pathlib import Path

import pytest

from backend.analysis import ratios
from backend.facts import select
from backend.ledger import Fact, Ledger, Source

FIXTURES = Path(__file__).resolve().parent / "fixtures"
K24 = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24.htm",
             title="Form 10-K, filed 2024-11-01", date="2024-11-01")
K23 = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k23.htm",
             title="Form 10-K, filed 2023-11-03", date="2023-11-03")
YE = "2024-09-28"

# a tiny company, numbers chosen so that every ratio is easy to check by hand
BASE = {
    ("revenue", "FY2024"): 1000.0, ("revenue", "FY2023"): 800.0, ("revenue", "FY2022"): 500.0,
    ("gross_profit", "FY2024"): 420.0,
    ("operating_income", "FY2024"): 230.0,
    ("net_income", "FY2024"): 130.0, ("net_income", "FY2023"): 100.0,
    ("operating_cash_flow", "FY2024"): 310.0, ("capex", "FY2024"): 45.0,
    ("shareholders_equity", YE): 520.0, ("shareholders_equity", "2024-06-29"): 999.0,
    ("total_assets", YE): 2600.0, ("long_term_debt", YE): 780.0,
}


def _ledger(values=None, *, period_end=True, units=None):
    ledger = Ledger()
    s24, s23 = ledger.add_source(K24), ledger.add_source(K23)
    for (key, period), value in (BASE if values is None else values).items():
        sid = s23 if period == "FY2023" else s24
        unit = (units or {}).get(key, "USD")
        ledger.add_fact(Fact(key=key, period=period, value=value, unit=unit, source_ids=(sid,)))
    if period_end:
        ledger.set_period_end("FY2024", YE)
        ledger.set_period_end("FY2023", "2023-09-30")
    return ledger


def _with(**changes):
    values = dict(BASE)
    for name, value in changes.items():
        key, period = name.rsplit("__", 1)
        period = YE if period == "YE" else period
        if value is None:
            values.pop((key, period), None)
        else:
            values[(key, period)] = value
    return values


def test_each_ratio_matches_a_hand_computed_number():
    ledger = _ledger()
    ratios.compute(ledger)
    expected = {
        "gross_margin": 420 / 1000,          # 0.42
        "operating_margin": 230 / 1000,      # 0.23
        "net_margin": 130 / 1000,            # 0.13
        "revenue_growth": 1000 / 800 - 1,    # 0.25
        "net_income_growth": 130 / 100 - 1,  # 0.30
        "return_on_equity": 130 / 520,       # 0.25, with equity on the year-end date (not 999)
        "return_on_assets": 130 / 2600,      # 0.05
        "debt_to_equity": 780 / 520,         # 1.5
        "free_cash_flow": 310 - 45,          # 265
        "fcf_margin": (310 - 45) / 1000,     # 0.265
    }
    for key, value in expected.items():
        fact = ledger.get(key, "FY2024")
        assert fact is not None, key
        assert fact.value == pytest.approx(value), key
        assert fact.note is None, key
    assert ledger.get("free_cash_flow", "FY2024").unit == "USD"
    assert ledger.get("gross_margin", "FY2024").unit == "ratio"


def test_formulas_and_inputs():
    ledger = _ledger()
    ratios.compute(ledger)
    gm = ledger.get("gross_margin", "FY2024")
    assert gm.formula == "gross_profit / revenue"
    assert gm.inputs == (("gross_profit", "FY2024"), ("revenue", "FY2024"))
    roe = ledger.get("return_on_equity", "FY2024")
    assert roe.inputs == (("net_income", "FY2024"), ("shareholders_equity", YE))
    assert ledger.get("free_cash_flow", "FY2024").formula == "operating_cash_flow - capex"


def test_revenue_growth_uses_the_prior_fiscal_year():
    ledger = _ledger()
    ratios.compute(ledger)
    growth = ledger.get("revenue_growth", "FY2024")
    assert growth.inputs == (("revenue", "FY2024"), ("revenue", "FY2023"))
    assert growth.value == pytest.approx(0.25)                    # not 1000 / 500 - 1
    assert ledger.get("revenue_growth", "FY2023").value == pytest.approx(800 / 500 - 1)
    assert ledger.get("revenue_growth", "FY2022") is None        # no FY2021


def test_every_computed_fact_has_a_formula_and_inputs_that_exist():
    ledger = _ledger()
    added = ratios.compute(ledger)
    assert added
    for fact in added:
        assert fact.is_computed and fact.formula and fact.inputs
        for key, period in fact.inputs:
            assert ledger.get(key, period) is not None, (fact.key, key, period)
        assert ledger.cite(fact)                                   # always reaches a filing


def test_a_missing_input_adds_nothing():
    ledger = _ledger(_with(gross_profit__FY2024=None, capex__FY2024=None,
                           shareholders_equity__YE=None))
    ratios.compute(ledger)
    for key in ("gross_margin", "free_cash_flow", "fcf_margin", "return_on_equity", "debt_to_equity"):
        assert ledger.get(key, "FY2024") is None, key
    assert ledger.get("net_margin", "FY2024").value == pytest.approx(0.13)


def test_balance_ratios_need_the_year_end_date():
    ledger = _ledger(period_end=False)
    ratios.compute(ledger)
    for key in ("return_on_equity", "return_on_assets", "debt_to_equity"):
        assert ledger.get(key, "FY2024") is None, key
    assert ledger.get("gross_margin", "FY2024") is not None


def test_negative_equity_gives_none_with_a_reason():
    ledger = _ledger(_with(shareholders_equity__YE=-150.0))
    ratios.compute(ledger)
    for key in ("return_on_equity", "debt_to_equity"):
        fact = ledger.get(key, "FY2024")
        assert fact is not None and fact.value is None, key
        assert fact.note == "shareholders' equity is negative"
        assert fact.inputs and fact.formula


def test_zero_denominators_give_none_with_a_reason():
    ledger = _ledger(_with(revenue__FY2024=0.0, net_income__FY2023=-20.0, shareholders_equity__YE=0.0))
    ratios.compute(ledger)
    for key in ("gross_margin", "operating_margin", "net_margin", "fcf_margin"):
        fact = ledger.get(key, "FY2024")
        assert fact.value is None and fact.note == "revenue is zero or negative", key
    growth = ledger.get("net_income_growth", "FY2024")
    assert growth.value is None and "prior-year net income" in growth.note
    assert ledger.get("return_on_equity", "FY2024").note == "shareholders' equity is zero"
    # a zero numerator is a real value, not a missing one
    assert ledger.get("revenue_growth", "FY2024").value == pytest.approx(-1.0)


def test_inputs_in_different_currencies_are_never_divided():
    ledger = _ledger(units={"gross_profit": "EUR"})
    ratios.compute(ledger)
    fact = ledger.get("gross_margin", "FY2024")
    assert fact.value is None and "different units" in fact.note


def test_fcf_margin_cites_through_two_levels():
    ledger = _ledger()
    ratios.compute(ledger)
    fcf_margin = ledger.get("fcf_margin", "FY2024")
    assert fcf_margin.inputs == (("free_cash_flow", "FY2024"), ("revenue", "FY2024"))
    assert [s.title for s in ledger.cite(fcf_margin)] == ["Form 10-K, filed 2024-11-01"]


def test_compute_twice_gives_the_same_ledger():
    ledger = _ledger()
    ratios.compute(ledger)
    first = ledger.to_json()
    ratios.compute(ledger)
    assert ledger.to_json() == first


def test_ratios_on_the_selected_fixture_facts():
    doc = json.loads((FIXTURES / "facts_three_years.json").read_text())
    ledger = Ledger()
    select.statement_facts(doc, [], ledger, cik="9999001")
    ratios.compute(ledger)
    assert ledger.get("gross_margin", "FY2024").value == pytest.approx(180_683 / 391_035)
    assert ledger.get("revenue_growth", "FY2024").value == pytest.approx(391_035 / 383_285 - 1)
    assert ledger.get("return_on_equity", "FY2024").inputs[1] == ("shareholders_equity", "2024-09-28")
    assert ledger.get("debt_to_equity", "FY2024").value == pytest.approx(85_750 / 56_950)
    # the bank has no gross profit: no gross margin, but a net margin
    bank = Ledger()
    select.statement_facts(json.loads((FIXTURES / "facts_bank.json").read_text()), [], bank, cik="9999003")
    ratios.compute(bank)
    assert bank.get("gross_margin", "FY2024") is None
    assert bank.get("net_margin", "FY2024").value == pytest.approx(5_060 / 18_400)
    assert bank.get("free_cash_flow", "FY2024") is None              # no capex reported


# ---- gross profit from revenue and cost of revenue ------------------------------------------------
def _no_gp(**extra):
    values = _with(gross_profit__FY2024=None, **extra)
    values[("cost_of_revenue", "FY2024")] = 580.0
    return values


def test_gross_profit_is_derived_from_revenue_and_cost_of_revenue():
    ledger = _ledger(_no_gp())
    ratios.compute(ledger)
    gp = ledger.get("gross_profit", "FY2024")
    assert gp is not None and gp.is_computed
    assert gp.value == pytest.approx(1000 - 580)
    assert gp.formula == "revenue - cost_of_revenue"
    assert gp.inputs == (("revenue", "FY2024"), ("cost_of_revenue", "FY2024"))
    assert gp.unit == "USD"
    assert ledger.cite(gp)                                             # reaches the filing
    gm = ledger.get("gross_margin", "FY2024")                          # the margin follows
    assert gm.value == pytest.approx(420 / 1000)
    assert ledger.get("gross_profit", "FY2023") is None                # no cost of revenue that year


def test_gross_profit_is_not_derived_when_switched_off_or_in_different_units():
    ledger = _ledger(_no_gp())
    ratios.compute(ledger, derive_gross_profit=False)                   # a bank or an insurer
    assert ledger.get("gross_profit", "FY2024") is None
    assert ledger.get("gross_margin", "FY2024") is None
    ledger = _ledger(_no_gp(), units={"cost_of_revenue": "EUR"})
    ratios.compute(ledger)
    assert ledger.get("gross_profit", "FY2024") is None


def test_a_reported_gross_profit_is_never_replaced():
    values = dict(BASE)
    values[("cost_of_revenue", "FY2024")] = 600.0                      # 1000 - 600 != 420
    ledger = _ledger(values)
    ratios.compute(ledger)
    gp = ledger.get("gross_profit", "FY2024")
    assert not gp.is_computed and gp.value == 420.0


def test_no_gross_profit_is_derived_when_the_company_defines_it_otherwise():
    # a year where all three are reported and gross profit is NOT revenue - cost of revenue shows
    # the cost line is not the whole cost of sales: no year is derived for this company
    values = _no_gp()
    values.update({("gross_profit", "FY2023"): 300.0, ("cost_of_revenue", "FY2023"): 450.0})   # 800-450=350
    ledger = _ledger(values)
    ratios.compute(ledger)
    assert ledger.get("gross_profit", "FY2024") is None
    values[("gross_profit", "FY2023")] = 350.0                         # consistent: derive
    ledger = _ledger(values)
    ratios.compute(ledger)
    assert ledger.get("gross_profit", "FY2024").value == pytest.approx(420.0)


def test_compute_twice_with_a_derived_gross_profit_gives_the_same_ledger():
    ledger = _ledger(_no_gp())
    ratios.compute(ledger)
    first = ledger.to_json()
    ratios.compute(ledger)
    assert ledger.to_json() == first
