"""Ratios as computed facts: all arithmetic here, in Python, never in the model.

Each result is a Fact with a readable `formula` and its `inputs` as (key, period) pairs, so the
report can show the calculation and link every input to its filing. The rules:
- a missing input (absent, or itself without a value) means the ratio is not added;
- a zero or negative denominator adds the ratio with `value=None` and a `note` saying why;
- inputs in different units (two currencies) add `value=None` with a note, never a mixed figure.
Ratios are computed per fiscal year (`FY2024`). Balances (equity, assets, debt) are taken on the
fiscal year's last day (`select.year_end_instant`), so FY2024 ROE uses equity on 2024-09-28 for a
September year end, not some other date.

Gross profit: a company that does not tag it (Meta, Eli Lilly) still reports revenue and cost of
revenue, and their difference is exact. `compute` adds it as a computed fact ("revenue -
cost_of_revenue") for a fiscal year that has both and no gross profit, before the margins, so the
gross margin follows. Never when the units differ, never over a reported gross profit, and not for
a company whose own reported gross profit differs from revenue less cost of revenue in some year
(its cost line is then not the whole cost of sales). `derive_gross_profit=False` switches it off:
the pipeline does so for banks and insurers, whose cost line is only part of their costs.
"""
from __future__ import annotations

from backend.facts.select import fiscal_years, year_end_instant
from backend.ledger import Fact, Ledger

RATIO = "ratio"


def _value(ledger: Ledger, ref: tuple[str, str] | None) -> Fact | None:
    if ref is None:
        return None
    fact = ledger.get(*ref)
    return fact if fact is not None and fact.value is not None else None


def _put(ledger: Ledger, fact: Fact) -> Fact:
    """Add, or replace a ratio computed earlier (so `compute` can run twice)."""
    if ledger.get(fact.key, fact.period) is None:
        return ledger.add_fact(fact)
    return ledger.replace_fact(fact)


def _division(ledger: Ledger, key: str, period: str, formula: str,
              num_ref: tuple[str, str] | None, den_ref: tuple[str, str] | None,
              den_note: str, *, minus_one: bool = False) -> Fact | None:
    """num / den (or num / den - 1 for growth) as a computed ratio, or None if an input is
    missing. `den_note` explains a zero or negative denominator."""
    num, den = _value(ledger, num_ref), _value(ledger, den_ref)
    if num is None or den is None:
        return None
    value, note = None, None
    if num.unit != den.unit:
        note = f"the inputs are reported in different units ({num.unit}, {den.unit})"
    elif den.value <= 0:
        note = den_note
    else:
        value = num.value / den.value - (1.0 if minus_one else 0.0)
    return _put(ledger, Fact(key=key, period=period, value=value, unit=RATIO,
                             inputs=(num_ref, den_ref), formula=formula, note=note))


def _free_cash_flow(ledger: Ledger, period: str) -> Fact | None:
    ocf_ref, capex_ref = ("operating_cash_flow", period), ("capex", period)
    ocf, capex = _value(ledger, ocf_ref), _value(ledger, capex_ref)
    if ocf is None or capex is None:
        return None
    value, note = None, None
    if ocf.unit != capex.unit:
        note = f"the inputs are reported in different units ({ocf.unit}, {capex.unit})"
    else:
        value = ocf.value - capex.value
    return _put(ledger, Fact(key="free_cash_flow", period=period, value=value, unit=ocf.unit,
                             inputs=(ocf_ref, capex_ref), formula="operating_cash_flow - capex",
                             note=note))


# a reported gross profit within this share of revenue - cost of revenue is the same definition
GROSS_PROFIT_TOLERANCE = 0.005


def _gross_profit_is_revenue_less_cost(ledger: Ledger, years: list[int]) -> bool:
    """False when some year REPORTS all three and gross profit is not revenue - cost of revenue."""
    for year in years:
        fy = f"FY{year}"
        gp, rev, cost = (ledger.get(k, fy) for k in ("gross_profit", "revenue", "cost_of_revenue"))
        if any(f is None or f.value is None or f.is_computed for f in (gp, rev, cost)):
            continue
        if len({gp.unit, rev.unit, cost.unit}) != 1:
            continue
        expected = rev.value - cost.value
        if abs(gp.value - expected) > GROSS_PROFIT_TOLERANCE * max(abs(gp.value), abs(expected), 1.0):
            return False
    return True


def _derived_gross_profit(ledger: Ledger, period: str) -> Fact | None:
    held = ledger.get("gross_profit", period)
    if held is not None and not held.is_computed:
        return None                                   # a reported gross profit is never replaced
    rev_ref, cost_ref = ("revenue", period), ("cost_of_revenue", period)
    rev, cost = _value(ledger, rev_ref), _value(ledger, cost_ref)
    if rev is None or cost is None or rev.unit != cost.unit:
        return None
    return _put(ledger, Fact(key="gross_profit", period=period, value=rev.value - cost.value,
                             unit=rev.unit, inputs=(rev_ref, cost_ref),
                             formula="revenue - cost_of_revenue",
                             note="The company does not report gross profit: this is revenue "
                                  "less cost of revenue."))


def compute(ledger: Ledger, *, derive_gross_profit: bool = True) -> list[Fact]:
    """Add every ratio the ledger has the inputs for, for every fiscal year; return them. With
    `derive_gross_profit` (the default), a year with revenue and cost of revenue but no gross
    profit first gets gross profit as a computed fact (see the module note)."""
    out: list[Fact] = []
    years = fiscal_years(ledger)
    if derive_gross_profit and _gross_profit_is_revenue_less_cost(ledger, years):
        for year in years:
            fact = _derived_gross_profit(ledger, f"FY{year}")
            if fact is not None:
                out.append(fact)
    for year in years:
        fy, prior = f"FY{year}", f"FY{year - 1}"
        ye = year_end_instant(ledger, year)
        equity = ("shareholders_equity", ye) if ye else None
        assets = ("total_assets", ye) if ye else None
        debt = ("long_term_debt", ye) if ye else None
        revenue, net_income = ("revenue", fy), ("net_income", fy)
        no_revenue = "revenue is zero or negative"
        # evaluated in order: fcf_margin reads the free_cash_flow added just before it
        results = [
            _division(ledger, "gross_margin", fy, "gross_profit / revenue",
                      ("gross_profit", fy), revenue, no_revenue),
            _division(ledger, "operating_margin", fy, "operating_income / revenue",
                      ("operating_income", fy), revenue, no_revenue),
            _division(ledger, "net_margin", fy, "net_income / revenue",
                      net_income, revenue, no_revenue),
            _division(ledger, "revenue_growth", fy, "revenue / prior-year revenue - 1",
                      revenue, ("revenue", prior),
                      "prior-year revenue is zero or negative, so growth is not meaningful",
                      minus_one=True),
            _division(ledger, "net_income_growth", fy, "net_income / prior-year net_income - 1",
                      net_income, ("net_income", prior),
                      "prior-year net income is zero or negative, so growth is not meaningful",
                      minus_one=True),
            _division(ledger, "return_on_equity", fy, "net_income / shareholders_equity at year end",
                      net_income, equity, _equity_note(ledger, equity)),
            _division(ledger, "return_on_assets", fy, "net_income / total_assets at year end",
                      net_income, assets, "total assets are zero or negative"),
            _division(ledger, "debt_to_equity", fy, "long_term_debt / shareholders_equity at year end",
                      debt, equity, _equity_note(ledger, equity)),
            _free_cash_flow(ledger, fy),
            # a ratio of a computed value: cite() follows both levels down to the filings
            _division(ledger, "fcf_margin", fy, "free_cash_flow / revenue",
                      ("free_cash_flow", fy), revenue, no_revenue),
        ]
        out.extend(f for f in results if f is not None)
    return out


def _equity_note(ledger: Ledger, ref: tuple[str, str] | None) -> str:
    fact = _value(ledger, ref)
    if fact is not None and fact.value == 0:
        return "shareholders' equity is zero"
    return "shareholders' equity is negative"
