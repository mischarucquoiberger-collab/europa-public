"""Scenario arithmetic: a small discounted-cash-flow grid. All arithmetic here, in Python.

Ported from the original product's valuation module (the original product's 
valuation.py, written for Japanese equities). What is carried over, with its line range:
- revenue CAGR between two fiscal years, elapsed time from the period-end dates / 365.25 with a
  positional fallback, refused for a non-positive revenue or misordered dates:
  `_cagr_between_rows` 335-392;
- the growth blend 0.6 x 2-year CAGR + 0.4 x 4-year CAGR, else the one that exists, else the mean
  of the year-on-year rates (at most four): `_historical_revenue_growth` 395-475;
- the projection: stage 1 for min(years, 5) years at g, stage 2 at (g + g_T) / 2, a Gordon terminal
  value times 0.95: `_project_dcf_value` 484-541 and `_TERMINAL_HAIRCUT` 481; as `_method_dcf`
  3413-3474 calls it: 7 years, g clipped to -10%..+25% (3455-3457), nothing when WACC <= g_T;
- net debt = interest-bearing debt - cash, never total liabilities, may be negative:
  `_net_debt` 591-607;
- CAPM: beta clipped to 0.3-2.5, cost of equity = rf + beta x ERP, the credible floor
  max(4%, rf + 0.5 x ERP): `_compute_capm` 869-1012, `_credible_coe_floor` 822-824 and the
  constants at 804 and 814;
- the bear / bull growth and margin rules: `_dcf_scenario` 3613-3655, here in enterprise value
  (the original subtracts net debt and divides by shares; neither is done here).

Left out on purpose: the model "advisor" (which supplies the original's discount rate) and the
blending of methods; every per-share value. New here, because the original has no cost-of-debt
input (`_wacc_coe_contradiction` 835-856): the WACC is built from the filings.

What this module never produces: a value per share, a comparison with the share price, or any
word of opinion. The output is enterprise value under stated assumptions, labelled as such.
"""
from __future__ import annotations

import html
import math
from datetime import date
from typing import Any, Iterable

from backend import format as fmt
from backend.facts.select import fiscal_years, year_end_instant
from backend.ledger import Fact, Ledger

RATIO = "ratio"

# Plain assumptions (not sourced figures): the defaults of `compute`.
RISK_FREE_RATE = 0.043          # a US 10-year Treasury yield level
EQUITY_RISK_PREMIUM = 0.05
TERMINAL_GROWTH = 0.02

# The original's method constants.
TERMINAL_HAIRCUT = 0.95         # valuation.py 481
STAGE1_YEARS = 5                # valuation.py 504
PROJECTION_YEARS = 7            # `_method_dcf` default, valuation.py 3413
GROWTH_BOUNDS = (-0.10, 0.25)   # valuation.py 3456
NO_HISTORY_GROWTH = 0.03        # valuation.py 409 and 455, labelled an assumption
BETA_BOUNDS = (0.3, 2.5)        # valuation.py 949
MIN_DISCOUNT_RATE = 0.04        # valuation.py 804
COE_MIN_ERP_SHARE = 0.5         # valuation.py 814
MIN_SPREAD = 0.015              # discount rate - terminal growth, the original's 1.5-point rule (2951)

MIN_BETA_DAYS = 60              # aligned daily returns needed for a regression beta
STATUTORY_TAX_RATE = 0.21       # US federal rate, used (labelled) when no effective rate is filed
MAX_COST_OF_DEBT = 0.15         # above this, interest expense is not the cost of the long-term debt
DISCOUNT_STEP = 0.01
TERMINAL_STEP = 0.005

# Reported inputs of the cost of debt and the tax rate (metrics in facts/metrics.py). When a
# filing has none of their tags the discount rate is the cost of equity alone and the result says so.
INTEREST_EXPENSE = "interest_expense"
INCOME_TAX = "income_tax_expense"
PRETAX_INCOME = "pretax_income"

TITLE = "Scenario arithmetic"
CLOSING = "Arithmetic under stated assumptions, not an opinion of value."


# ---- small helpers ---------------------------------------------------------------------------
def _value(ledger: Ledger, ref: tuple[str, str] | None) -> Fact | None:
    if ref is None or ref[1] is None:
        return None
    fact = ledger.get(*ref)
    return fact if fact is not None and fact.value is not None else None


def _put(ledger: Ledger, fact: Fact) -> Fact:
    """Add, or replace a fact computed earlier (so `compute` can run twice)."""
    if ledger.get(fact.key, fact.period) is None:
        return ledger.add_fact(fact)
    return ledger.replace_fact(fact)


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _finite(*values: Any) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in values)


def _pct(value: float) -> str:
    """A rate as text, through format (the one place a number becomes text)."""
    return fmt.fact(Fact(key="rate", period="-", value=value, unit=RATIO))


def _money(value: float, unit: str) -> str:
    return fmt.fact(Fact(key="amount", period="-", value=value, unit=unit))


def _e(text: str) -> str:
    return html.escape(text)


def _iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# ---- revenue growth (valuation.py 335-475) ----------------------------------------------------
def _elapsed_years(ledger: Ledger, newer_year: int, older_year: int) -> float | None:
    """Years between two fiscal year ends: the period-end dates / 365.25 when both are recorded
    (None when they are misordered), otherwise the difference of the fiscal year numbers (the
    original's positional fallback, 382-391)."""
    newer = _iso(ledger.period_end(f"FY{newer_year}"))
    older = _iso(ledger.period_end(f"FY{older_year}"))
    if newer is not None and older is not None:
        if newer <= older:
            return None
        return (newer - older).days / 365.25
    years = float(newer_year - older_year)
    return years if years > 0 else None


def _cagr(ledger: Ledger, year: int, span: int) -> tuple[float, float, tuple, tuple] | None:
    """(rate, elapsed years, newer ref, older ref) for revenue FY{year} against FY{year - span},
    or None when either is missing, the units differ, either revenue is zero or negative, or the
    dates are misordered (all refused by the original, 347-373)."""
    new_ref, old_ref = ("revenue", f"FY{year}"), ("revenue", f"FY{year - span}")
    new, old = _value(ledger, new_ref), _value(ledger, old_ref)
    if new is None or old is None or new.unit != old.unit:
        return None
    if new.value <= 0 or old.value <= 0:
        return None
    years = _elapsed_years(ledger, year, year - span)
    if years is None:
        return None
    return (new.value / old.value) ** (1.0 / years) - 1.0, years, new_ref, old_ref


def _cagr_fact(ledger: Ledger, year: int, span: int, key: str) -> Fact | None:
    found = _cagr(ledger, year, span)
    if found is None:
        return None
    rate, years, new_ref, old_ref = found
    elapsed = fmt.fact(Fact(key="elapsed", period="-", value=years, unit="years"))
    return Fact(key=key, period=f"FY{year}", value=rate, unit=RATIO, inputs=(new_ref, old_ref),
                formula=f"(revenue / revenue {span} fiscal years earlier) ^ (1 / years elapsed) - 1",
                note=f"Years elapsed between the fiscal year ends: {elapsed} "
                     "(period-end dates / 365.25, or the fiscal year numbers when a date is missing).")


def _latest_revenue_year(ledger: Ledger) -> int | None:
    for year in fiscal_years(ledger):
        if _value(ledger, ("revenue", f"FY{year}")) is not None:
            return year
    return None


def _growth_plan(ledger: Ledger, fiscal_year: int | None = None) -> dict:
    """The growth estimate and the computed facts behind it, in the order they must be added.
    Nothing is added to the ledger here."""
    year = fiscal_year if fiscal_year is not None else _latest_revenue_year(ledger)
    plan: dict = {"year": year, "estimate": None, "facts": [], "basis": None}
    if year is None:
        return plan
    fy = f"FY{year}"
    short = _cagr_fact(ledger, year, 2, "revenue_cagr_2y")
    long = _cagr_fact(ledger, year, 4, "revenue_cagr_4y")
    facts = [f for f in (short, long) if f is not None]
    if short is not None and long is not None:
        estimate = Fact(key="revenue_growth_estimate", period=fy,
                        value=0.6 * short.value + 0.4 * long.value, unit=RATIO,
                        inputs=(("revenue_cagr_2y", fy), ("revenue_cagr_4y", fy)),
                        formula="0.6 x revenue_cagr_2y + 0.4 x revenue_cagr_4y")
        basis = "blend"
    elif short is not None or long is not None:
        one = short or long
        other = "4-year" if one is short else "2-year"
        estimate = Fact(key="revenue_growth_estimate", period=fy, value=one.value, unit=RATIO,
                        inputs=((one.key, fy),), formula=one.key,
                        note=f"The {other} rate is not available, so the 0.6 / 0.4 blend uses the one rate there is.")
        basis = one.key
    else:
        # the original's fallback (433-453): the mean of up to four year-on-year rates
        rates, refs = [], []
        for idx in range(4):
            found = _cagr(ledger, year - idx, 1)
            if found is None:
                continue
            rates.append(found[0])
            for ref in found[2:]:
                if ref not in refs:
                    refs.append(ref)
        if not rates:
            return plan
        estimate = Fact(key="revenue_growth_estimate", period=fy, value=sum(rates) / len(rates),
                        unit=RATIO, inputs=tuple(refs),
                        formula="mean of the year-on-year revenue CAGRs "
                                "((revenue / prior-year revenue) ^ (1 / years elapsed) - 1)",
                        note="No 2-year or 4-year rate is available, so the year-on-year rates are averaged.")
        basis = "year_on_year_mean"
    plan.update(estimate=estimate.value, facts=facts + [estimate], basis=basis)
    return plan


def revenue_growth_estimate(ledger: Ledger, *, fiscal_year: int | None = None) -> float | None:
    """Historical revenue growth as the original blends it (valuation.py 395-475):

        g = 0.6 x CAGR(2 years) + 0.4 x CAGR(4 years)
        CAGR(n) = (revenue FY_t / revenue FY_t-n) ^ (1 / years elapsed) - 1

    where years elapsed = days between the two fiscal year ends / 365.25 (the fiscal year numbers'
    difference when a period end is not recorded). If only one of the two rates exists it is used
    alone; if neither does, the mean of up to four year-on-year rates. A rate is refused when
    either revenue is missing, zero or negative, the units differ, or the dates are misordered.
    No usable history gives None (the original then assumes 3%: `compute` does that, labelled).
    `fiscal_year` defaults to the newest fiscal year with revenue. Adds nothing to the ledger."""
    return _growth_plan(ledger, fiscal_year)["estimate"]


# ---- beta and the cost of equity (valuation.py 822-1012) ---------------------------------------
def _closes(bars: Iterable) -> dict[str, float]:
    """date -> close for every bar with an ISO date and a positive close (Massive `Bar` objects
    or dicts with `date` and `close`)."""
    out: dict[str, float] = {}
    for bar in bars or ():
        if isinstance(bar, dict):
            day, close = bar.get("date"), bar.get("close")
        else:
            day, close = getattr(bar, "date", None), getattr(bar, "close", None)
        if not day or not _finite(close) or close <= 0:
            continue
        out[str(day)[:10]] = float(close)
    return out


def beta_from_bars(stock_bars: Iterable, market_bars: Iterable) -> float | None:
    """The ordinary least squares slope of the stock's daily returns on the market's,
    cov(r_stock, r_market) / var(r_market), clipped to 0.3-2.5 (valuation.py 933-949).

    Both series are first aligned on the trading dates they share; a return is close / previous
    shared close - 1, so both returns always span the same days. Simple returns are used for both
    (the original took the stock's log return). Fewer than 60 aligned returns, or a market that
    does not move, gives None; the original's volatility proxy (941-946) is not carried over."""
    stock, market = _closes(stock_bars), _closes(market_bars)
    common = sorted(set(stock) & set(market))
    rs = [stock[b] / stock[a] - 1.0 for a, b in zip(common, common[1:])]
    rm = [market[b] / market[a] - 1.0 for a, b in zip(common, common[1:])]
    if len(rs) < MIN_BETA_DAYS:
        return None
    ms, mm = sum(rs) / len(rs), sum(rm) / len(rm)
    cov = sum((x - ms) * (y - mm) for x, y in zip(rs, rm))
    var = sum((y - mm) ** 2 for y in rm)
    if var <= 0:
        return None
    return _clip(cov / var, *BETA_BOUNDS)


def _capm(risk_free: float, beta: float | None, equity_risk_premium: float) -> tuple[float, float, float]:
    """(cost of equity, CAPM figure before the floor, the floor)."""
    b = 1.0 if beta is None else float(beta)
    raw = float(risk_free) + b * float(equity_risk_premium)
    floor = max(MIN_DISCOUNT_RATE, float(risk_free) + COE_MIN_ERP_SHARE * float(equity_risk_premium))
    return max(raw, floor), raw, floor


def cost_of_equity(risk_free: float, beta: float | None,
                   equity_risk_premium: float = EQUITY_RISK_PREMIUM) -> float:
    """CAPM, rf + beta x ERP (beta None counts as 1.0), never below the original's credible floor
    max(4%, rf + 0.5 x ERP) (valuation.py 822-824). The original withholds a figure under the
    floor; a scenario grid needs a rate, so here the floor is used and `compute` says so."""
    return _capm(risk_free, beta, equity_risk_premium)[0]


# ---- the discount rate (new: the original has no cost-of-debt input) ---------------------------
def _cost_of_debt_fact(ledger: Ledger, year: int, debt_ref: tuple[str, str], debt: Fact) -> Fact | None:
    """interest_expense / long-term debt (the average of this and the prior fiscal year end when
    both are held), or None when no interest expense is in the ledger."""
    fy = f"FY{year}"
    int_ref = (INTEREST_EXPENSE, fy)
    interest = _value(ledger, int_ref)
    if interest is None:
        return None
    prior_end = year_end_instant(ledger, year - 1)
    prior_ref = ("long_term_debt", prior_end) if prior_end and prior_end != debt_ref[1] else None
    prior = _value(ledger, prior_ref)
    if prior is not None and prior.unit == debt.unit:
        inputs = (int_ref, debt_ref, prior_ref)
        denominator = (debt.value + prior.value) / 2.0
        formula = "interest_expense / average of long_term_debt at this and the prior fiscal year end"
    else:
        inputs = (int_ref, debt_ref)
        denominator = debt.value
        formula = "interest_expense / long_term_debt at year end"
    value, note = None, None
    if interest.unit != debt.unit:
        note = f"the inputs are reported in different units ({interest.unit}, {debt.unit})"
    elif denominator <= 0:
        note = "long-term debt is zero or negative"
    elif interest.value < 0:
        note = "interest expense is reported as a negative amount"
    else:
        value = interest.value / denominator
    return Fact(key="pre_tax_cost_of_debt", period=fy, value=value, unit=RATIO, inputs=inputs,
                formula=formula, note=note)


def _tax_rate_fact(ledger: Ledger, year: int) -> Fact | None:
    """income_tax_expense / pretax_income, or None when either is not in the ledger."""
    fy = f"FY{year}"
    tax_ref, pre_ref = (INCOME_TAX, fy), (PRETAX_INCOME, fy)
    tax, pre = _value(ledger, tax_ref), _value(ledger, pre_ref)
    if tax is None or pre is None:
        return None
    value, note = None, None
    if tax.unit != pre.unit:
        note = f"the inputs are reported in different units ({tax.unit}, {pre.unit})"
    elif pre.value <= 0:
        note = "pre-tax income is zero or negative, so an effective tax rate is not meaningful"
    else:
        value = tax.value / pre.value
    return Fact(key="effective_tax_rate", period=fy, value=value, unit=RATIO,
                inputs=(tax_ref, pre_ref), formula="income_tax_expense / pretax_income", note=note)


def wacc(ledger: Ledger, fiscal_year: int, *, cost_of_equity: float,
         market_cap: float | None) -> tuple[float, dict]:
    """The discount rate: E/(D+E) x cost of equity + D/(D+E) x Kd x (1 - t).

    E is the market capitalisation when given (market data), otherwise book equity at the fiscal
    year end; D is long-term debt at the fiscal year end. Kd = interest expense / long-term debt
    (the average of the opening and closing balance when both are held); t = income tax / pre-tax
    income, or the 21% statutory rate (labelled an assumption) when no usable effective rate is
    filed. When D, Kd or a positive E is missing, the rate is the cost of equity alone and
    `detail["reason"]` says why. Adds nothing to the ledger: `detail["facts"]` holds the computed
    facts (cost of debt, tax rate) for `compute` to add."""
    coe = float(cost_of_equity)
    year = int(fiscal_year)
    ye = year_end_instant(ledger, year)
    detail: dict = {"method": "weighted", "reason": None, "cost_of_equity": coe,
                    "equity_basis": None, "equity_value": None, "equity_ref": None,
                    "debt": None, "debt_ref": None, "equity_weight": None, "debt_weight": None,
                    "pre_tax_cost_of_debt": None, "tax_rate": None, "tax_basis": None,
                    "tax_reason": None, "after_tax_cost_of_debt": None, "facts": []}

    def alone(reason: str) -> tuple[float, dict]:
        detail.update(method="cost_of_equity_only", reason=reason, equity_weight=1.0, debt_weight=0.0)
        return coe, detail

    debt_ref = ("long_term_debt", ye) if ye else None
    debt = _value(ledger, debt_ref)
    if debt is None:
        return alone("long-term debt at the fiscal year end is not in the sources")
    detail.update(debt=debt.value, debt_ref=debt_ref)
    if market_cap is not None and _finite(market_cap) and market_cap > 0:
        if debt.unit != "USD":
            return alone(f"the market capitalisation is in USD and debt is reported in {debt.unit}")
        equity_value = float(market_cap)
        detail.update(equity_basis="market capitalisation (market data)")
    else:
        eq_ref = ("shareholders_equity", ye)
        equity = _value(ledger, eq_ref)
        if equity is None:
            return alone("no market capitalisation was given and book equity at the fiscal year "
                         "end is not in the sources, so the capital weights cannot be computed")
        if equity.unit != debt.unit:
            return alone(f"book equity and debt are reported in different units ({equity.unit}, {debt.unit})")
        if equity.value <= 0:
            return alone("book equity is zero or negative, so book-value weights are not meaningful")
        equity_value = equity.value
        detail.update(equity_basis="book equity at the fiscal year end", equity_ref=eq_ref)
    detail["equity_value"] = equity_value
    if debt.value <= 0:
        return alone("long-term debt at the fiscal year end is zero")
    kd = _cost_of_debt_fact(ledger, year, debt_ref, debt)
    if kd is None:
        return alone("interest expense is not reported as its own figure, so no cost of debt can be computed")
    detail["facts"].append(kd)
    if kd.value is None:
        return alone(f"no cost of debt: {kd.note}")
    if kd.value > MAX_COST_OF_DEBT:
        return alone(f"interest expense is more than {_pct(MAX_COST_OF_DEBT)} of long-term debt, so it "
                     "likely covers more than this debt (a bank's interest on deposits, for example)")
    tax = _tax_rate_fact(ledger, year)
    if tax is not None:
        detail["facts"].append(tax)
    if tax is not None and tax.value is not None and 0.0 <= tax.value < 1.0:
        t, basis, why = tax.value, "effective", None
    else:
        t, basis = STATUTORY_TAX_RATE, "statutory"
        if tax is None:
            why = "income tax or pre-tax income is not in the sources"
        elif tax.value is None:
            why = tax.note
        else:
            why = "the effective rate is outside 0 to 100%"
    after = kd.value * (1.0 - t)
    total = equity_value + debt.value
    w_e, w_d = equity_value / total, debt.value / total
    detail.update(pre_tax_cost_of_debt=kd.value, tax_rate=t, tax_basis=basis, tax_reason=why,
                  after_tax_cost_of_debt=after, equity_weight=w_e, debt_weight=w_d)
    return w_e * coe + w_d * after, detail


# ---- the projection (valuation.py 484-541) -----------------------------------------------------
def two_stage_dcf(base_fcf: float, growth: float, discount: float, terminal_growth: float,
                  years: int = 5, terminal_haircut: float = TERMINAL_HAIRCUT) -> float | None:
    """Enterprise value from a free-cash-flow projection (the original's `_project_dcf_value`,
    with revenue x margin replaced by the free cash flow itself, i.e. a constant margin):

        stage 1, t = 1 .. min(years, 5):  FCF_t = FCF_(t-1) x (1 + growth)
        stage 2, t = 6 .. years:          FCF_t = FCF_(t-1) x (1 + (growth + terminal_growth) / 2)
        EV = sum FCF_t / (1 + discount)^t
             + FCF_years x (1 + terminal_growth) / (discount - terminal_growth) x terminal_haircut
               / (1 + discount)^years

    None when discount <= terminal_growth (the perpetuity diverges), base_fcf <= 0, years < 1,
    or an input is not a finite number."""
    if not _finite(base_fcf, growth, discount, terminal_growth, terminal_haircut):
        return None
    if isinstance(years, bool) or not isinstance(years, int) or years < 1:
        return None
    if base_fcf <= 0 or discount <= terminal_growth or discount <= -1:
        return None
    stage1 = min(years, STAGE1_YEARS)
    growth2 = (growth + terminal_growth) / 2.0
    fcf, pv = float(base_fcf), 0.0
    for t in range(1, years + 1):
        fcf *= 1.0 + (growth if t <= stage1 else growth2)
        pv += fcf / (1.0 + discount) ** t
    terminal = fcf * (1.0 + terminal_growth) / (discount - terminal_growth) * terminal_haircut
    return pv + terminal / (1.0 + discount) ** years


# ---- the entry point ---------------------------------------------------------------------------
SHORT_TERM_INVESTMENTS = "short_term_investments"


def short_term_investments(ledger: Ledger, year: int) -> Fact | None:
    """Short-term investments at the fiscal year end, when the ledger holds them (through
    `annual_fact` once the metric is an instant in METRICS, else at the year-end date directly)."""
    from backend.draft.writer import annual_fact
    f = annual_fact(ledger, SHORT_TERM_INVESTMENTS, year)
    if f is None or f.value is None:
        ye = year_end_instant(ledger, year)
        f = ledger.get(SHORT_TERM_INVESTMENTS, ye) if ye else None
    return f if f is not None and f.value is not None else None


def net_debt_words(fact: Fact) -> str:
    """What a net_debt fact subtracts, from its own inputs."""
    if any(key == SHORT_TERM_INVESTMENTS for key, _p in fact.inputs):
        return "long-term debt less cash and short-term investments"
    return "long-term debt less cash"


def _net_debt_fact(ledger: Ledger, year: int) -> Fact | None:
    """long_term_debt - cash - short_term_investments at the fiscal year end (valuation.py
    591-607, with near-cash investments subtracted too); without short-term investments in the
    ledger, long_term_debt - cash. None when debt or cash is missing (absence is unknown, never
    zero). May be negative (net cash)."""
    ye = year_end_instant(ledger, year)
    if not ye:
        return None
    debt_ref, cash_ref = ("long_term_debt", ye), ("cash", ye)
    debt, cash = _value(ledger, debt_ref), _value(ledger, cash_ref)
    if debt is None or cash is None:
        return None
    sti = short_term_investments(ledger, year)
    parts = [debt, cash] + ([sti] if sti is not None else [])
    inputs = (debt_ref, cash_ref) + (((sti.key, sti.period),) if sti is not None else ())
    formula = ("long_term_debt - cash - short_term_investments at year end" if sti is not None
               else "long_term_debt - cash at year end")
    value, note = None, None
    if len({f.unit for f in parts}) != 1:
        note = "the inputs are reported in different units (" + ", ".join(f.unit for f in parts) + ")"
    else:
        value = debt.value - cash.value - (sti.value if sti is not None else 0.0)
    held = ("Short-term investments are subtracted with cash. " if sti is not None
            else "No short-term investments are in the filings data, so only cash is subtracted. ")
    return Fact(key="net_debt", period=f"FY{year}", value=value, unit=debt.unit, inputs=inputs,
                formula=formula,
                note=note or held + "Interest-bearing debt is the long-term debt line as filed; "
                                    "short-term borrowings tagged separately are not in it. Never total liabilities.")


def compute(ledger: Ledger, *, risk_free: float = RISK_FREE_RATE,
            equity_risk_premium: float = EQUITY_RISK_PREMIUM, beta: float | None = None,
            market_cap: float | None = None, terminal_growth: float = TERMINAL_GROWTH,
            years: int = PROJECTION_YEARS) -> dict | None:
    """The scenario grid for the latest fiscal year, ready to render; None (and nothing added)
    when that year's free cash flow (a computed fact from ratios.compute) is missing or not
    positive.

    Adds computed facts for what is derived from ledger figures: revenue_cagr_2y,
    revenue_cagr_4y, revenue_growth_estimate, net_debt, and (when the inputs exist)
    pre_tax_cost_of_debt and effective_tax_rate. The risk-free rate, equity risk premium and
    terminal growth are plain assumptions (the defaults above); beta is market data when given,
    otherwise 1.0; market_cap (market data) sets the equity weight. The cells are enterprise
    values for the discount rate (base, -1 point, +1 point) x terminal growth (-0.5, base, +0.5
    points); a cell whose discount rate is less than 1.5 points above terminal growth is n/a.
    No per-share value is computed and nothing is compared with a share price.

    "cases": bear, base and bull rows (`case_inputs`, the original's `_dcf_scenario`), each with
    the enterprise value at the discount rate +1 point / base / -1 point at the base terminal
    growth. "market": market_cap + net debt as a reference value (None values without a market
    cap or net debt); no difference or percentage against it is computed anywhere.

    HTML vs text: assumptions' value_html is HTML (escaped text and fmt.cited links); the cells,
    labels, columns, note, cases and market are plain text with nothing that needs escaping."""
    all_years = fiscal_years(ledger)
    if not all_years:
        return None
    year = all_years[0]
    fy = f"FY{year}"
    fcf = _value(ledger, ("free_cash_flow", fy))
    if fcf is None or fcf.value <= 0:
        return None

    # growth: the filings' history, or the original's 3% assumption, clipped for the projection
    plan = _growth_plan(ledger, year)
    for f in plan["facts"]:
        _put(ledger, f)
    growth_fact = ledger.get("revenue_growth_estimate", fy) if plan["estimate"] is not None else None
    raw_growth = plan["estimate"] if plan["estimate"] is not None else NO_HISTORY_GROWTH
    growth = _clip(raw_growth, *GROWTH_BOUNDS)

    net_debt = _net_debt_fact(ledger, year)
    if net_debt is not None:
        net_debt = _put(ledger, net_debt)

    # cost of equity and the discount rate
    if beta is not None and not _finite(beta):
        beta = None
    beta_used = 1.0 if beta is None else _clip(float(beta), *BETA_BOUNDS)
    coe, coe_raw, coe_floor = _capm(risk_free, beta_used, equity_risk_premium)
    discount, detail = wacc(ledger, year, cost_of_equity=coe, market_cap=market_cap)
    held = {f.key: _put(ledger, f) for f in detail["facts"]}

    # the grid
    rates = [discount - DISCOUNT_STEP, discount, discount + DISCOUNT_STEP]
    terminals = [terminal_growth - TERMINAL_STEP, terminal_growth, terminal_growth + TERMINAL_STEP]
    columns = [f"terminal growth {_pct(terminals[0])}"] + [_pct(t) for t in terminals[1:]]
    rows = []
    for r in rates:
        cells = []
        for tg in terminals:
            ev = two_stage_dcf(fcf.value, growth, r, tg, years=years) if r - tg >= MIN_SPREAD - 1e-12 else None
            cells.append(_money(ev, fcf.unit) if ev is not None
                         else "n/a: discount rate less than 1.5 points above terminal growth")
        rows.append({"label": f"discount rate {_pct(r)}", "cells": cells})

    assumptions = [
        {"label": "Base free cash flow",
         "value_html": fmt.cited(fcf, ledger) + _e(f" ({fmt.period_label(fy)}, operating cash flow "
                                                   "less capital expenditure, from the filings)")},
        {"label": "Revenue growth", "value_html": _growth_html(ledger, plan, growth_fact, raw_growth, growth)},
        {"label": "Projection",
         "value_html": _e(_capital(_years_text(min(years, STAGE1_YEARS))) + " at the revenue growth rate"
                          + (f", then {_years_text(years - STAGE1_YEARS)} at the midpoint of that rate "
                             "and terminal growth" if years > STAGE1_YEARS else "")
                          + "; the terminal value (a growing perpetuity) is multiplied by 0.95, "
                            "a 5% haircut for caution")},
        {"label": "Risk-free rate", "value_html": _e(f"{_pct(risk_free)} (assumption, not a sourced figure)")},
        {"label": "Equity risk premium",
         "value_html": _e(f"{_pct(equity_risk_premium)} (assumption, not a sourced figure)")},
        {"label": "Beta", "value_html": _beta_html(beta, beta_used)},
        {"label": "Cost of equity", "value_html": _coe_html(coe, coe_raw, coe_floor)},
        {"label": "Discount rate", "value_html": _discount_html(ledger, discount, detail, held, fcf.unit, coe)},
        {"label": "Terminal growth", "value_html": _e(f"{_pct(terminal_growth)} (assumption, not a sourced figure)")},
    ]

    # net debt: linked in the assumptions; the note is plain text (no link, nothing to escape)
    if net_debt is not None and net_debt.value is not None:
        when = fmt.period_label(year_end_instant(ledger, year))
        words = net_debt_words(net_debt)
        assumptions.append({"label": "Net debt", "value_html": fmt.cited(net_debt, ledger) + _e(
            f" {when} ({words}, from the filings; not subtracted in the grid)")})
        net_debt_text = (f"{fmt.fact(net_debt)} {when} ({words}, linked with the assumptions); "
                         "the cells are before net debt")
    else:
        net_debt_text = f"{fmt.NOT_AVAILABLE} (long-term debt or cash at the fiscal year end is missing)"
    floor_text = ""
    if rates[0] < coe_floor - 1e-12:
        if detail["method"] == "weighted" and discount < coe - 1e-12:
            floor_text = (f" The weighted discount rate is below the cost of equity because debt is "
                          f"cheaper than equity, so rows can sit under the {_pct(coe_floor)} "
                          "cost-of-equity floor.")
        else:
            floor_text = (f" The row at {_pct(rates[0])} is under the {_pct(coe_floor)} cost-of-equity "
                          "floor and is shown as a sensitivity only.")
    note = ("Enterprise value implied by the latest free cash flow under each pair of assumptions. "
            f"Net debt: {net_debt_text}.{floor_text} The risk-free rate, equity risk premium and "
            f"terminal growth are assumptions, not sourced figures. {CLOSING}")
    revenue = _value(ledger, ("revenue", fy))
    cases = _cases(fcf, revenue, growth, discount, terminal_growth, years,
                   from_history=growth_fact is not None, bounded=abs(growth - raw_growth) > 1e-12)
    return {"title": TITLE, "period": fmt.period_label(fy), "assumptions": assumptions,
            "columns": columns, "rows": rows, "note": note, "cases": cases,
            "market": _market(market_cap, net_debt)}


# ---- bear / base / bull (valuation.py 3613-3655), in enterprise value -------------------------------
SCENARIO_GROWTH_BOUNDS = (-0.10, 0.30)   # valuation.py 3614
SCENARIO_GROWTH_STEP = 0.02              # valuation.py 3645 and 3651
BEAR_GROWTH_FLOOR = -0.05                # valuation.py 3651: the cut stops at -5%
SCENARIO_MARGIN_STEP = 0.01              # valuation.py 3645 and 3651
SCENARIO_MARGIN_BOUNDS = (0.01, 0.30)    # valuation.py 3615
MARKET_NOTE = "Market capitalisation (as given) plus net debt"
_CASE_LABELS = {"bear": "Bear case", "base": "Base case", "bull": "Bull case"}


def _ev_at(base_fcf: float, growth: float, discount: float, terminal_growth: float,
           years: int) -> float | None:
    """The grid's arithmetic for one cell: None under the 1.5-point spread rule."""
    if discount - terminal_growth < MIN_SPREAD - 1e-12:
        return None
    return two_stage_dcf(base_fcf, growth, discount, terminal_growth, years=years)


def case_inputs(growth: float, margin: float | None) -> dict:
    """The original's scenario operands (`_dcf_scenario`, valuation.py 3613-3655) for a base growth
    rate and free-cash-flow margin (None when revenue is not usable: the margin is then held):

        bull growth  = clip(g + 2 points, -10%, 30%)
        bear growth  = min(clip(g + min(0, max(-2 points, -5% - g)), -10%, 30%), g)
        bull margin  = m + min(1 point, 30% - m), never below m
        bear margin  = min(m, max(m - 1 point, 1%))

    The original caps its base margin at 25%, so its 30% ceiling never moves a case across the
    base; here the base margin is the filed one, so the ceiling is applied only as far as it
    keeps bear <= base <= bull."""
    bull_g = _clip(growth + SCENARIO_GROWTH_STEP, *SCENARIO_GROWTH_BOUNDS)
    bear_adj = min(0.0, max(-SCENARIO_GROWTH_STEP, BEAR_GROWTH_FLOOR - growth))
    bear_g = min(_clip(growth + bear_adj, *SCENARIO_GROWTH_BOUNDS), growth)
    out = {"bear": {"growth": bear_g, "margin": margin}, "base": {"growth": growth, "margin": margin},
           "bull": {"growth": bull_g, "margin": margin}}
    if margin is not None:
        out["bull"]["margin"] = margin + max(0.0, min(SCENARIO_MARGIN_STEP, SCENARIO_MARGIN_BOUNDS[1] - margin))
        out["bear"]["margin"] = min(margin, max(margin - SCENARIO_MARGIN_STEP, SCENARIO_MARGIN_BOUNDS[0]))
    return out


def _case_sentence(key: str, has_margin: bool, period: str, from_history: bool, bounded: bool,
                   growth: float) -> str:
    held = ("" if has_margin else
            f"; the free cash flow margin is held at the base because revenue for {period} is not usable")
    if key == "base":
        if not from_history:
            return (f"Growth is the {_pct(NO_HISTORY_GROWTH)} assumption used when the sources have no "
                    "comparable revenue history, applied to the latest filed free cash flow.")
        bound = f", bounded to {_pct(growth)}" if bounded else ""
        return (f"Growth is the blended historical revenue growth from the filings{bound}, applied to "
                "the latest filed free cash flow.")
    if key == "bull":
        margin = (f" and the free cash flow margin the base margin plus up to one point (to at most "
                  f"{_pct(SCENARIO_MARGIN_BOUNDS[1])})" if has_margin else "")
        return f"Growth is the base rate plus two points{margin}{held}."
    margin = (f" and the free cash flow margin the base margin less one point (floor "
              f"{_pct(SCENARIO_MARGIN_BOUNDS[0])})" if has_margin else "")
    return (f"Growth is the base rate less up to two points (the cut stops at {_pct(BEAR_GROWTH_FLOOR)} "
            f"and never raises a rate already below it){margin}{held}.")


def _cases(fcf: Fact, revenue: Fact | None, growth: float, discount: float, terminal_growth: float,
           years: int, *, from_history: bool, bounded: bool) -> list[dict]:
    """Bear, base and bull rows. low / base / high are the enterprise value at the discount rate
    plus one point / the base rate / less one point, at the base terminal growth. The base case
    is the grid's middle cell; a bull or bear case's free cash flow is revenue x its margin."""
    usable = revenue is not None and revenue.unit == fcf.unit and revenue.value > 0
    margin = fcf.value / revenue.value if usable else None
    period = fmt.period_label(fcf.period)
    out = []
    for key, operands in case_inputs(growth, margin).items():
        g, m = operands["growth"], operands["margin"]
        base_fcf = fcf.value if key == "base" or m is None else revenue.value * m
        row = {"key": key, "label": _CASE_LABELS[key], "growth": g, "growth_text": _pct(g),
               "fcf_margin": m, "fcf_margin_text": _pct(m) if m is not None else None,
               "assumption": _case_sentence(key, m is not None, period, from_history, bounded, g)}
        for name, rate in (("low", discount + DISCOUNT_STEP), ("base", discount),
                           ("high", discount - DISCOUNT_STEP)):
            ev = _ev_at(base_fcf, g, rate, terminal_growth, years)
            row[name] = ev
            row[f"{name}_text"] = _money(ev, fcf.unit) if ev is not None else None
        out.append(row)
    return out


def _market(market_cap: float | None, net_debt: Fact | None) -> dict:
    """A reference line: market capitalisation (market data, USD) plus the ledger's net debt.
    None values unless both are known and in USD, and then "reason" says why no line is drawn.
    Nothing is compared with it here."""
    out = {"enterprise_value": None, "text": None, "note": MARKET_NOTE, "reason": None}
    if market_cap is None or not _finite(market_cap) or market_cap <= 0:
        out["reason"] = "No market enterprise value is drawn: no market capitalisation was available."
    elif net_debt is None or net_debt.value is None:
        out["reason"] = ("No market enterprise value is drawn: net debt is not available (long-term "
                         "debt or cash at the fiscal year end is not in the filings data).")
    elif net_debt.unit != "USD":
        out["reason"] = (f"No market enterprise value is drawn: net debt is reported in {net_debt.unit} "
                         "and the market capitalisation is in USD.")
    else:
        ev = float(market_cap) + net_debt.value
        out.update(enterprise_value=ev, text=_money(ev, "USD"))
    return out


# ---- assumption texts (HTML: escaped text and fmt.cited links only) ------------------------------
_NUMBER_WORDS = {1: "one year", 2: "two years", 3: "three years", 4: "four years", 5: "five years"}


def _years_text(n: int) -> str:
    return _NUMBER_WORDS.get(n) or fmt.fact(Fact(key="years", period="-", value=n, unit="years"))


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _growth_html(ledger: Ledger, plan: dict, growth_fact: Fact | None, raw: float, used: float) -> str:
    if growth_fact is None:
        text = _e(f"{_pct(raw)} (assumption: the sources have no comparable revenue history, so the "
                  "default rate is used)")
    else:
        how = {"blend": "0.6 x the 2-year CAGR + 0.4 x the 4-year CAGR",
               "revenue_cagr_2y": "the 2-year CAGR (no 4-year rate)",
               "revenue_cagr_4y": "the 4-year CAGR (no 2-year rate)",
               "year_on_year_mean": "the mean of the year-on-year rates"}[plan["basis"]]
        text = fmt.cited(growth_fact, ledger) + _e(f" ({how}, from the filings)")
    if abs(used - raw) > 1e-12:
        text += _e(f"; bounded to {_pct(used)} for the projection (growth is kept between "
                   f"{_pct(GROWTH_BOUNDS[0])} and {_pct(GROWTH_BOUNDS[1])})")
    return text


def _beta_html(supplied: float | None, used: float) -> str:
    shown = fmt.fact(Fact(key="beta", period="-", value=used, unit="against the market index"))
    if supplied is None:
        return _e(f"{shown} (assumption: no price history was used)")
    text = (f"{shown} (market data: least-squares slope of the stock's daily returns on the index, "
            "bounded to 0.30-2.50)")
    if abs(float(supplied) - used) > 1e-12:
        given = fmt.fact(Fact(key="beta", period="-", value=float(supplied), unit="as supplied"))
        text += f"; {given}, bounded"
    return _e(text)


def _coe_html(coe: float, raw: float, floor: float) -> str:
    if raw >= floor:
        return _e(f"{_pct(coe)} (risk-free rate + beta x equity risk premium)")
    return _e(f"{_pct(coe)} (the floor: the larger of {_pct(MIN_DISCOUNT_RATE)} and risk-free rate + "
              f"0.5 x equity risk premium; risk-free rate + beta x premium gives {_pct(raw)})")


def _discount_html(ledger: Ledger, rate: float, detail: dict, held: dict, unit: str,
                   coe: float | None = None) -> str:
    if detail["method"] != "weighted":
        return _e(f"{_pct(rate)} (the cost of equity alone: {detail['reason']})")
    below = (_e("; the weighted rate is below the cost of equity because debt is cheaper")
             if coe is not None and rate < coe - 1e-12 else "")
    debt = ledger.get(*detail["debt_ref"])
    if detail["equity_ref"] is not None:
        equity_html = _e("book equity ") + fmt.cited(ledger.get(*detail["equity_ref"]), ledger)
    else:
        equity_html = _e(f"market capitalisation {_money(detail['equity_value'], unit)} (market data)")
    if detail["tax_basis"] == "effective":
        tax_html = fmt.cited(held["effective_tax_rate"], ledger)
    else:
        tax_html = _e(f"{_pct(STATUTORY_TAX_RATE)}, the statutory rate (assumption: {detail['tax_reason']})")
    return (_e(f"{_pct(rate)} (weighted: equity {_pct(detail['equity_weight'])} at the cost of equity, "
               f"from ") + equity_html
            + _e(f"; debt {_pct(detail['debt_weight'])} at the after-tax cost of debt "
                 f"{_pct(detail['after_tax_cost_of_debt'])} = ")
            + fmt.cited(held["pre_tax_cost_of_debt"], ledger) + _e(" x (1 - ") + tax_html
            + _e("), from long-term debt ") + fmt.cited(debt, ledger) + below + _e(")"))
