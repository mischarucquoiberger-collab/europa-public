"""The company's own valuation multiples for its latest fiscal year, computed in Python.

The descriptive half of the original's peer multiples (the original product's 
valuation.py: P/S at 4557-4597, EV multiples at 3897-4172, which subtract net debt; net debt at
591-607): the company's own multiple only. Left out: the implied price (peer median x own metric /
shares), which is a fair value, and any comparison or judgement.

The multiples are NOT added to the ledger: the price is market data, not a filing figure. Each
ledger input is shown as its linked value (`fmt.cited`), the price with its date. A missing input
or a zero or negative denominator gives value None and the reason in "text".
"""
from __future__ import annotations

import math

from backend import format as fmt
from backend.draft.writer import annual_fact
from backend.facts import metrics
from backend.facts.select import fiscal_years, year_end_instant
from backend.ledger import Fact, Ledger

PRICE_CURRENCY = "USD"      # a US listing's price


def _finite_positive(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _usable(f: Fact | None) -> Fact | None:
    return f if f is not None and f.value is not None else None


def _latest_shares(ledger: Ledger) -> Fact | None:
    """The newest reported share count (the cover-page count is usually the latest date)."""
    for period in ledger.periods("shares_outstanding"):
        f = _usable(ledger.get("shares_outstanding", period))
        if f is not None:
            return f
    return None


def _text(value: float | None, reason: str | None) -> str:
    if value is not None:
        return fmt.fact(Fact(key="multiple", period="-", value=value, unit="x"))
    return f"{fmt.NOT_AVAILABLE}: {reason}" if reason else fmt.NOT_AVAILABLE


FINANCIAL_REASON = ("not used for a bank or insurer: enterprise value and free cash flow do not "
                    "describe a company whose debt and cash are its business")


def _row(ledger: Ledger, key: str, label: str, formula: str, inputs: list[Fact],
         value: float | None, reason: str | None, price_note: str, *, not_used: bool = False) -> dict:
    if value is not None and not math.isfinite(value):
        value, reason = None, "the arithmetic does not give a finite number"
    text = (reason[:1].upper() + reason[1:]) if not_used else _text(value, reason)
    return {
        "key": key,
        "label": label,
        "value": value,
        "text": text,
        "reason": None if value is not None else (reason or fmt.NOT_AVAILABLE),
        "formula": formula,
        "inputs_html": [fmt.cited(f, ledger) for f in inputs],
        "inputs": [{"label": metrics.label(f.key), "period": fmt.period_label(f.period),
                    "value_html": fmt.cited(f, ledger)} for f in inputs],
        "price_note": price_note,
    }


def _price_note(price, price_date: str | None, shares_note: str | None) -> str:
    if not _finite_positive(price):
        note = "No share price was available (market data)"
    else:
        shown = fmt.fact(Fact(key="price", period="-", value=float(price), unit=f"{PRICE_CURRENCY}/share"))
        when = f", end of day {price_date}" if price_date else ", date not given"
        note = f"Price: {shown}{when} (market data)"
    return note + (f"; {shares_note}" if shares_note else "")


def _money_reason(f: Fact | None, what: str, period: str) -> str | None:
    """Why a money input cannot be used, or None when it can."""
    if f is None:
        return f"{what} for {fmt.period_label(period)} is not in the sources"
    if f.unit != PRICE_CURRENCY:
        return f"{what} is reported in {f.unit} and the price is in {PRICE_CURRENCY}"
    return None


STALE_SHARE_DAYS = 400      # a share count older than this is not multiplied by today's price


def _share_age_days(period: str, price_date: str | None) -> int | None:
    from datetime import date
    try:
        counted = date.fromisoformat(str(period)[:10])
        priced = date.fromisoformat(str(price_date)[:10]) if price_date else date.today()
    except ValueError:
        return None
    return (priced - counted).days


def compute(ledger: Ledger, *, price: float | None, price_date: str | None,
            shares: float | None = None, fallback_shares: float | None = None,
            financial: bool = False) -> list[dict]:
    """For the latest fiscal year: price / diluted EPS, market cap / revenue, market cap / free
    cash flow, EV / operating income and price / book value, where market cap = price x shares
    (the newest reported share count unless `shares` is given) and EV = market cap + net debt
    (net debt = long-term debt - cash - short-term investments at the fiscal year end, the
    investments only when the filings data has them). Each row: key, label, value (float or
    None), text ("24.3x" or the not-available line with the reason), reason (None with a value),
    formula, inputs_html (fmt.cited of each ledger input), inputs (the same with labels) and
    price_note. `financial` (a bank or insurer): the free-cash-flow and enterprise-value rows are
    not computed and say why. Nothing is added to the ledger. An empty list when the ledger has
    no fiscal year."""
    years = fiscal_years(ledger)
    if not years:
        return []
    year = years[0]
    fy = f"FY{year}"
    ye = year_end_instant(ledger, year)
    has_price = _finite_positive(price)
    price_value = float(price) if has_price else None

    stale = None
    if shares is not None and _finite_positive(shares):
        share_count, share_inputs = float(shares), []
        shown = fmt.fact(Fact(key="shares", period="-", value=share_count, unit="shares"))
        shares_note = f"shares: {shown} (supplied with the price)"
    else:
        held = _latest_shares(ledger)
        if held is not None:
            age = _share_age_days(held.period, price_date)
            if age is not None and age > STALE_SHARE_DAYS:
                # a company with several share classes may stop tagging one total: a count from
                # years ago times today's price would be a wrong market capitalisation
                stale = f"the newest share count in the filings is {fmt.period_label(held.period)}"
                held = None
        if held is None and fallback_shares is not None and _finite_positive(fallback_shares):
            share_count, share_inputs = float(fallback_shares), []
            shown = fmt.fact(Fact(key="shares", period="-", value=share_count, unit="shares"))
            shares_note = f"shares: {shown} (market data" + (f"; {stale}" if stale else "") + ")"
        else:
            share_count = held.value if held is not None and held.value > 0 else None
            share_inputs = [held] if held is not None else []
            shares_note = None
    note = _price_note(price, price_date, shares_note)

    market_cap, cap_reason = None, None
    if not has_price:
        cap_reason = "no share price"
    elif share_count is None:
        cap_reason = (f"{stale}, too old to use with the price" if (shares is None and stale)
                      else "no positive share count is in the sources")
    else:
        market_cap = price_value * share_count

    rows = []

    # price / diluted EPS
    eps = _usable(annual_fact(ledger, "eps_diluted", year))
    value, reason = None, None
    if not has_price:
        reason = "no share price"
    elif eps is None:
        reason = f"diluted EPS for {fmt.period_label(fy)} is not in the sources"
    elif eps.unit != f"{PRICE_CURRENCY}/share":
        reason = f"diluted EPS is reported in {eps.unit} and the price is in {PRICE_CURRENCY}"
    elif eps.value <= 0:
        reason = "diluted EPS is zero or negative, so the multiple is not meaningful"
    else:
        value = price_value / eps.value
    # P/E uses no share count: its note carries the price only
    rows.append(_row(ledger, "price_to_earnings", "Price / diluted EPS", "price / eps_diluted",
                     [eps] if eps is not None else [], value, reason, _price_note(price, price_date, None)))

    # market cap / revenue and market cap / free cash flow
    for key, label, metric, what in (
            ("market_cap_to_revenue", "Market capitalisation / revenue", "revenue", "revenue"),
            ("market_cap_to_fcf", "Market capitalisation / free cash flow", "free_cash_flow",
             "free cash flow")):
        formula = f"price x shares_outstanding / {metric}"
        if financial and metric == "free_cash_flow":
            rows.append(_row(ledger, key, label, formula, [], None, FINANCIAL_REASON, note, not_used=True))
            continue
        f = _usable(annual_fact(ledger, metric, year))
        value, reason = None, cap_reason or _money_reason(f, what, fy)
        if reason is None:
            if f.value <= 0:
                reason = f"{what} is zero or negative, so the multiple is not meaningful"
            else:
                value = market_cap / f.value
        rows.append(_row(ledger, key, label, formula,
                         share_inputs + ([f] if f is not None else []), value, reason, note))

    # EV / operating income, EV = market cap + net debt
    nd_inputs, net_debt, nd_reason, nd_formula = _net_debt(ledger, year, ye)
    formula = f"(price x shares_outstanding + net_debt) / operating_income, net_debt = {nd_formula}"
    if financial:
        rows.append(_row(ledger, "ev_to_operating_income", "Enterprise value / operating income",
                         formula, [], None, FINANCIAL_REASON, note, not_used=True))
    else:
        op = _usable(annual_fact(ledger, "operating_income", year))
        value, reason = None, cap_reason or nd_reason or _money_reason(op, "operating income", fy)
        if reason is None:
            ev = market_cap + net_debt
            if op.value <= 0:
                reason = "operating income is zero or negative, so the multiple is not meaningful"
            elif ev <= 0:
                reason = "enterprise value (market capitalisation + net debt) is zero or negative"
            else:
                value = ev / op.value
        rows.append(_row(ledger, "ev_to_operating_income", "Enterprise value / operating income", formula,
                         share_inputs + nd_inputs + ([op] if op is not None else []), value, reason, note))

    # price / book value = market cap / shareholders' equity at the fiscal year end
    equity = _usable(ledger.get("shareholders_equity", ye)) if ye else None
    value, reason = None, cap_reason
    if reason is None and equity is None:
        reason = "book equity at the fiscal year end is not in the sources"
    elif reason is None and equity.unit != PRICE_CURRENCY:
        reason = f"book equity is reported in {equity.unit} and the price is in {PRICE_CURRENCY}"
    if reason is None:
        if equity.value <= 0:
            reason = "book equity is zero or negative, so the multiple is not meaningful"
        else:
            value = market_cap / equity.value
    rows.append(_row(ledger, "price_to_book", "Price / book value",
                     "price x shares_outstanding / shareholders_equity at year end",
                     share_inputs + ([equity] if equity is not None else []), value, reason, note))
    return rows


def _net_debt(ledger: Ledger, year: int, ye: str | None) -> tuple[list[Fact], float | None, str | None, str]:
    """(inputs to cite, net debt, reason it is unavailable, its formula). The ledger's computed
    net_debt (scenarios.compute) when held, otherwise long_term_debt - cash - short-term
    investments at the fiscal year end (the investments only when the ledger holds them)."""
    held = _usable(ledger.get("net_debt", f"FY{year}"))
    if held is not None:
        formula = held.formula or "long_term_debt - cash at year end"
        if held.unit != PRICE_CURRENCY:
            return [held], None, f"net debt is reported in {held.unit} and the price is in {PRICE_CURRENCY}", formula
        return [held], held.value, None, formula
    from backend.analysis.scenarios import short_term_investments
    debt = _usable(ledger.get("long_term_debt", ye)) if ye else None
    cash = _usable(ledger.get("cash", ye)) if ye else None
    sti = short_term_investments(ledger, year)
    formula = ("long_term_debt - cash - short_term_investments at year end" if sti is not None
               else "long_term_debt - cash at year end")
    inputs = [f for f in (debt, cash, sti) if f is not None]
    if debt is None or cash is None:
        return (inputs, None, "net debt is not available: long-term debt or cash at the fiscal year end is missing",
                formula)
    for f, what in ((debt, "long-term debt"), (cash, "cash"), (sti, "short-term investments")):
        if f is not None and f.unit != PRICE_CURRENCY:
            return inputs, None, f"{what} is reported in {f.unit} and the price is in {PRICE_CURRENCY}", formula
    return inputs, debt.value - cash.value - (sti.value if sti is not None else 0.0), None, formula

