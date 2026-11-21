"""Peer benchmarking: one row per comparable company, each built from that company's OWN SEC data.

    row = profile("MSFT")                     # one peer, never raises
    table = benchmark(["MSFT", "GOOGL", ...]) # every peer at the same time, order kept, never raises

Each peer is loaded exactly as the report's own company is (backend.pipeline): its CIK, its
filings index and XBRL company facts, `select.statement_facts` into a fresh Ledger of its own, then
`ratios.compute`. A row shows the peer's newest fiscal year. Every cell is a link to the SEC filing
its figure comes from: a reported figure through `format.cited`, a computed ratio through an anchor
of the same shape pointing at its first input's filing, with the calculation written out in its
title. A figure the peer's data does not hold is `n/a`, never a guess. Medians are computed here,
in Python, and only from three values or more.

Each row also carries the peer's own valuation multiples (P/E, EV/EBIT, EV/sales, P/B) from its
previous close (backend.sources.massive, fetched while the SEC data loads) and its newest fiscal
year: every input must be there, in US dollars, with a positive denominator, or the multiple is
None. `multiples_basis` states each multiple's arithmetic in words, numbers worded by `format.fact`.
"""
from __future__ import annotations

import re
import html
import logging
import math
import statistics
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date

from backend import format as fmt
from backend.facts import metrics
from backend.ledger import Fact, Ledger
from backend.sources import massive, sec

try:
    from backend.naming import display_name
except Exception:                  # names are a nicety: shown as the SEC writes them
    def display_name(raw) -> str:
        return str(raw or "").strip()

log = logging.getLogger(__name__)

_SOURCE_ID = re.compile(r'\sdata-source="[^"]*"')

COLUMNS = (("revenue", "Revenue"), ("revenue_growth", "Rev. growth"), ("operating_margin", "Op. margin"),
           ("net_margin", "Net margin"), ("return_on_equity", "ROE"), ("debt_to_equity", "LT debt / equity"))
# the unit a column's median is taken in: a revenue in another currency is left out of the median
COLUMN_UNITS = {"revenue": "USD"}
DEFAULT_UNIT = "ratio"
MEDIAN_MIN = 3

NOT_AVAILABLE = "Not available in the SEC data"
TOO_LONG = "Took too long"
NA = "n/a"
NOTE = ("Each company's figures are its own latest fiscal year as filed with the SEC; "
        "fiscal years end on different dates.")

_KEYS = tuple(key for key, _label in COLUMNS)

MULTIPLES = ("pe", "ev_ebit", "ev_sales", "pb")
MARKET_KEYS = ("shares", "shares_as_of", "market_cap", "net_debt", "enterprise_value")
SHARES_MAX_AGE_DAYS = 400     # a share count older than this (before the price date) is not used
PRICE_WAIT = 20.0             # seconds to wait for the price once the SEC data is in
SHORT_TERM_INVESTMENTS = "short_term_investments"   # netted against debt when the ledger holds it
MARGIN_KEYS = ("operating_margin", "net_margin")    # n/a for a peer without positive revenue
POSITIVE_ONLY = frozenset({"revenue"})              # a zero or negative revenue is not in its median


# ---- one peer -----------------------------------------------------------------------------
def _symbol(ticker) -> str:
    """The backend's one spelling of a symbol (`brk-b` -> `BRK.B`); a string that is not a symbol
    is kept as written (upper case) so its row can say it is not available."""
    from backend.sources import tickers
    text = str(ticker or "").strip()
    try:
        return tickers.normalise(text)
    except Exception:
        return text.upper()


def _filing_dict(f) -> dict:
    """The filing as `select.statement_facts` reads it (the same shape backend.pipeline passes)."""
    if isinstance(f, dict):
        d = dict(f)
    else:
        d = {k: getattr(f, k, None) for k in ("accession", "form", "filed", "period", "primary_doc", "cik")}
        d["url"] = getattr(f, "url", None)
        d["viewer_url"] = getattr(f, "viewer_url", None)
    return d


def _row(ticker: str, name: str = "", error: str | None = None) -> dict:
    return {"ticker": ticker, "name": name or "", "period_label": "", "period_end": "",
            "cells": {key: "" for key in _KEYS}, "values": {key: None for key in _KEYS},
            "units": {key: None for key in _KEYS}, "error": error,
            "price": None, "market": {key: None for key in MARKET_KEYS},
            "multiples": {key: None for key in MULTIPLES}, "multiples_basis": {}}


def _date_words(iso: str | None) -> str:
    """`2026-06-30` -> `30 Jun 2026` (the report's own date wording); "" when it is not a date."""
    if not iso:
        return ""
    text = fmt.period_label(str(iso))
    return text.removeprefix("as of ") if text.startswith("as of ") else ""


def _annual(ledger: Ledger, key: str, year: int) -> Fact | None:
    """A key's fact for fiscal `year`: `FY2024` for a flow or a ratio, the year-end date for a balance."""
    m = metrics.METRICS.get(key)
    period = ledger.period_end(f"FY{year}") if m is not None and m.kind == "instant" else f"FY{year}"
    return ledger.get(key, period) if period else None


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _calculation(fact: Fact, ledger: Ledger) -> str:
    """The calculation in words with its inputs, e.g. `Operating income $123.2 billion ÷ revenue
    $391.0 billion, fiscal 2024 (computed)`. Every number comes from `format.fact`."""
    formula = fact.formula or ""
    inputs = []
    for i, (key, period) in enumerate(fact.inputs):
        held = ledger.get(key, period)
        label = metrics.label(key)
        inputs.append((label if i == 0 else _lower_first(label),
                       fmt.fact(held) if held is not None else fmt.NOT_AVAILABLE,
                       fmt.period_label(period)))
    op = " ÷ " if "/" in formula else (" − " if " - " in formula else " and ")
    minus_one = " − 1" if formula.replace(" ", "").endswith("-1") and "/" in formula else ""
    periods = {p for _l, _v, p in inputs}
    if len(periods) == 1:
        body = op.join(f"{label} {value}" for label, value, _p in inputs)
        return f"{body}{minus_one}, {inputs[0][2]} (computed)"
    body = op.join(f"{label} {value} ({period})" for label, value, period in inputs)
    return f"{body}{minus_one} (computed)"


def _computed_cell(fact: Fact, ledger: Ledger) -> str | None:
    """A computed figure linked to the filing of its first input (the in-page `#calc-` link of
    `format.cited` exists only for the report's own company), with the calculation as its title.
    None when the fact has no source to link to."""
    sources = [s for s in ledger.cite(fact) if str(s.url).startswith(("https://", "http://"))]
    if not sources:
        return None
    first = sources[0]
    title = _calculation(fact, ledger)
    return (f'<a class="src" href="{html.escape(first.url, quote=True)}" '
            f'data-source="{html.escape(first.id, quote=True)}" '
            f'title="{html.escape(title, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer">{html.escape(fmt.fact(fact))}</a>')


def _not_meaningful(fact: Fact) -> str:
    """A computed ratio the ledger holds without a value (e.g. negative equity): n/a, with why."""
    return _na("Not meaningful: " + fact.note) if fact.note else NA


# ---- valuation multiples ------------------------------------------------------------------------
def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except (TypeError, ValueError):
        return None


def _price(raw) -> dict | None:
    """`massive.previous_close`'s bar as {"close", "date"}; None unless both are usable."""
    if not isinstance(raw, dict):
        return None
    close, day = _finite(raw.get("close")), _iso(raw.get("date"))
    if close is None or close <= 0 or day is None:
        return None
    return {"close": close, "date": day.isoformat()}


def _in(fact: Fact | None, unit: str) -> Fact | None:
    """The fact when it has a finite value in `unit`; otherwise None."""
    if fact is None or fact.unit != unit or _finite(fact.value) is None:
        return None
    return fact


def _divide(num: float | None, den: float | None) -> float | None:
    """num / den when both are positive and the result is finite."""
    if num is None or den is None or num <= 0 or den <= 0:
        return None
    return _finite(num / den)


def _words(key: str, value: float, unit: str) -> str:
    # a throwaway Fact so the number is worded by `format.fact`; never added to a ledger
    return fmt.fact(Fact(key=key, period="peer", value=value, unit=unit))


def _shares(ledger: Ledger, price_day: date) -> Fact | None:
    """The newest share count with a value, if it is dated no more than SHARES_MAX_AGE_DAYS
    before the price date."""
    for period in ledger.periods("shares_outstanding"):
        fact = ledger.get("shares_outstanding", period)
        if fact is None or fact.value is None:
            continue
        day = _iso(period)
        if _in(fact, "shares") is None or fact.value <= 0 or day is None:
            return None
        return fact if (price_day - day).days <= SHARES_MAX_AGE_DAYS else None
    return None


def _valuation(ledger: Ledger, year: int, price: dict | None) -> tuple[dict, dict, dict]:
    """(market, multiples, multiples_basis) for fiscal `year` at `price`."""
    market = {key: None for key in MARKET_KEYS}
    multiples = {key: None for key in MULTIPLES}
    basis: dict[str, str] = {}
    fy = f"FY{year}"
    fy_text = fmt.period_label(fy)
    ye = ledger.period_end(fy)
    ye_text = _date_words(ye)

    nd_text = None
    debt = _in(ledger.get("long_term_debt", ye), "USD") if ye else None
    cash = _in(ledger.get("cash", ye), "USD") if ye else None
    # short-term investments count against debt when the peer's data holds them; one held in
    # another unit cannot be netted, so then there is no net debt at all (never a mixed figure)
    investments_held = ledger.get(SHORT_TERM_INVESTMENTS, ye) if ye else None
    investments = _in(investments_held, "USD")
    usable = investments_held is None or investments_held.value is None or investments is not None
    if debt is not None and cash is not None and usable:
        less = debt.value - cash.value - (investments.value if investments is not None else 0.0)
        market["net_debt"] = _finite(less)
        if market["net_debt"] is not None:
            less_investments = (f" less short-term investments {fmt.fact(investments)}"
                                if investments is not None else "")
            nd_text = (f"net debt {_words('net_debt', market['net_debt'], 'USD')} (long-term debt "
                       f"{fmt.fact(debt)} less cash {fmt.fact(cash)}{less_investments} at {ye_text})")
    if price is None:
        return market, multiples, basis

    close, price_day = price["close"], _iso(price["date"])
    close_text = f"price {_words('price', close, 'USD/share')} on {_date_words(price['date'])}"

    eps = _in(ledger.get("eps_diluted", fy), "USD/share")
    if eps is not None:
        multiples["pe"] = _divide(close, eps.value)
        if multiples["pe"] is not None:
            basis["pe"] = f"{close_text} ÷ diluted EPS {fmt.fact(eps)}, {fy_text}"

    shares = _shares(ledger, price_day)
    if shares is None:
        return market, multiples, basis
    market["shares"] = float(shares.value)
    market["shares_as_of"] = shares.period
    market["market_cap"] = _finite(close * shares.value)
    if market["market_cap"] is None:
        return market, multiples, basis
    cap_words = _words("market_cap", market["market_cap"], "USD")
    cap_text = (f"market cap {cap_words} ({close_text} × {fmt.fact(shares)} as of "
                f"{_date_words(shares.period)})")

    equity = _in(ledger.get("shareholders_equity", ye), "USD") if ye else None
    if equity is not None:
        multiples["pb"] = _divide(market["market_cap"], equity.value)
        if multiples["pb"] is not None:
            basis["pb"] = f"{cap_text} ÷ shareholders' equity {fmt.fact(equity)} at {ye_text}"

    if market["net_debt"] is None:
        return market, multiples, basis
    market["enterprise_value"] = _finite(market["market_cap"] + market["net_debt"])
    ev = market["enterprise_value"]
    if ev is None:
        return market, multiples, basis
    ev_text = f"enterprise value {_words('enterprise_value', ev, 'USD')}"
    ev_parts = f"; enterprise value = {cap_text} + {nd_text}"
    for key, metric, label in (("ev_ebit", "operating_income", "operating income"),
                               ("ev_sales", "revenue", "revenue")):
        denominator = _in(ledger.get(metric, fy), "USD")
        if denominator is None:
            continue
        multiples[key] = _divide(ev, denominator.value)
        if multiples[key] is not None:
            basis[key] = f"{ev_text} ÷ {label} {fmt.fact(denominator)}, {fy_text}{ev_parts}"
    return market, multiples, basis


def _start_loads(symbol: str, cik: str):
    """The filings index, the company facts and the previous close, all started at once (a large
    company-facts document no longer waits behind the filings index). Returns three futures; the
    pool is not waited for, so a load the row stops waiting for never holds it."""
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="peer-load")
    try:
        filings = pool.submit(sec.filings, cik)
        facts = pool.submit(sec.company_facts, cik)
        try:
            price = pool.submit(massive.previous_close, symbol)
        except Exception:
            price = None
        return filings, facts, price
    finally:
        pool.shutdown(wait=False)


def _na(title: str) -> str:
    return f'<span class="na" title="{html.escape(title, quote=True)}">{NA}</span>'


def _revenue_problem(ledger: Ledger, year: int) -> str | None:
    """Why the margins cannot be shown for `year` (no revenue, or revenue of zero or below), or None."""
    revenue = _annual(ledger, "revenue", year)
    if revenue is None or revenue.value is None:
        return "Not available: revenue is not in the SEC data for this year"
    if revenue.value == 0:
        return "Not meaningful: revenue is zero"
    if revenue.value < 0:
        return "Not meaningful: revenue is negative"
    return None


def _collect_price(future) -> dict | None:
    try:
        return _price(future.result(timeout=PRICE_WAIT)) if future is not None else None
    except Exception as exc:       # no price: the multiples are None, the row stands
        log.info("peer price not available: %s", exc)
        return None


def profile(ticker: str) -> dict:
    """One peer's row: its newest fiscal year's figures for every column, each linked to its
    filing, and its valuation multiples at its previous close. Never raises: a failure gives the
    row with `error` set, empty cells and None values."""
    symbol = _symbol(ticker)
    name = ""
    try:
        from backend.analysis import ratios
        from backend.facts import select

        cik = sec.cik_for(symbol)
        if not cik:
            return _row(symbol, error=NOT_AVAILABLE)
        filings_future, facts_future, price_future = _start_loads(symbol, cik)
        try:
            name = display_name(sec.company_name(symbol))   # "MICROSOFT CORP" -> "Microsoft Corp."
        except Exception:      # the name is a nicety; the ticker stands on its own
            name = ""
        filings = list(filings_future.result() or [])
        company_facts = facts_future.result()
        ledger = Ledger()
        summary = select.statement_facts(company_facts, [_filing_dict(f) for f in filings], ledger, cik=cik)
        if not (summary or {}).get("facts"):
            return _row(symbol, name, NOT_AVAILABLE)
        ratios.compute(ledger)
        years = select.fiscal_years(ledger)
        if not years:
            return _row(symbol, name, NOT_AVAILABLE)
        year = years[0]
        row = _row(symbol, name)
        row["period_label"] = fmt.period_label(f"FY{year}")
        row["period_end"] = _date_words(ledger.period_end(f"FY{year}"))
        revenue_problem = _revenue_problem(ledger, year)
        for key in _KEYS:
            if key in MARGIN_KEYS and revenue_problem:
                row["cells"][key] = _na(revenue_problem)
                continue
            fact = _annual(ledger, key, year)
            cell = None
            if fact is not None and fact.value is not None:
                cell = _computed_cell(fact, ledger) if fact.is_computed else fmt.cited(fact, ledger)
                # the source number belongs to the peer's own ledger: on another company's page it
                # would point at a different filing in that page's source list
                cell = _SOURCE_ID.sub("", cell)
            if cell is None:
                row["cells"][key] = _not_meaningful(fact) if fact is not None else NA
                continue
            row["cells"][key] = cell
            row["values"][key] = float(fact.value)
            row["units"][key] = fact.unit
        price = _collect_price(price_future)
        try:
            market, multiples, basis = _valuation(ledger, year, price)
            row.update(price=price, market=market, multiples=multiples, multiples_basis=basis)
        except Exception as exc:   # the figures stand; the multiples stay None
            log.info("peer %s multiples not available: %s", symbol, exc)
        return row
    except Exception as exc:
        log.info("peer %s not available: %s", symbol, exc)
        return _row(symbol, name, NOT_AVAILABLE)


# ---- every peer -----------------------------------------------------------------------------
def _unique(tickers) -> list[str]:
    seen: dict[str, None] = {}
    for t in list(tickers or []):
        symbol = _symbol(t)
        if symbol and symbol not in seen:
            seen[symbol] = None
    return list(seen)


def _median_text(key: str, unit: str, value: float) -> str:
    # a throwaway Fact only so the median is worded exactly as `format.fact` words this kind of
    # value; it is never added to a ledger
    return fmt.fact(Fact(key=key, period="median", value=value, unit=unit))


def medians(rows: list[dict]) -> dict:
    """Per column: the median of the rows that have the value (in the column's unit), given only
    when at least three do: {"value": float | None, "text": str | None, "n": int}."""
    out = {}
    for key in _KEYS:
        unit = COLUMN_UNITS.get(key, DEFAULT_UNIT)
        values = []
        for row in rows:
            if not isinstance(row, dict) or row.get("error"):
                continue
            value = (row.get("values") or {}).get(key)
            row_unit = (row.get("units") or {}).get(key)
            if value is None or (row_unit is not None and row_unit != unit):
                continue
            if key in POSITIVE_ONLY and value <= 0:     # a peer without revenue is no benchmark for it
                continue
            values.append(float(value))
        if len(values) >= MEDIAN_MIN:
            m = float(statistics.median(values))
            out[key] = {"value": m, "text": _median_text(key, unit, m), "n": len(values)}
        else:
            out[key] = {"value": None, "text": None, "n": len(values)}
    return out


def multiple_medians(rows: list[dict]) -> dict:
    """Per multiple: the median of the rows that have it, given only when at least three do:
    {"value": float | None, "n": int}."""
    out = {}
    for key in MULTIPLES:
        values = []
        for row in rows:
            if not isinstance(row, dict) or row.get("error"):
                continue
            value = _finite((row.get("multiples") or {}).get(key))
            if value is not None:
                values.append(value)
        value = float(statistics.median(values)) if len(values) >= MEDIAN_MIN else None
        out[key] = {"value": value, "n": len(values)}
    return out


def _table(rows: list[dict], asked: int) -> dict:
    return {"columns": [[key, label] for key, label in COLUMNS], "rows": rows, "medians": medians(rows),
            "multiple_medians": multiple_medians(rows),
            "note": NOTE, "asked": asked, "answered": sum(1 for r in rows if not r.get("error")),
            "slow": [r.get("ticker") for r in rows if r.get("error") == TOO_LONG]}


def benchmark(tickers: list[str], *, max_workers: int = 5, timeout: float = 45.0) -> dict:
    """Every peer's `profile` at the same time, rows in the order asked (duplicates dropped); a peer
    not finished within `timeout` seconds gets the error "Took too long" (it is not waited for) and
    its ticker is listed in `slow`. Never raises."""
    try:
        ordered = _unique(tickers)
    except Exception:
        ordered = []
    rows: list[dict] = []
    try:
        if ordered:
            pool = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), len(ordered))),
                                      thread_name_prefix="peer")
            try:
                futures = [pool.submit(profile, t) for t in ordered]
                done, _late = wait(futures, timeout=max(0.0, float(timeout)))
                for symbol, future in zip(ordered, futures):
                    if future in done:
                        try:
                            row = future.result()
                        except Exception:
                            row = _row(symbol, error=NOT_AVAILABLE)
                        rows.append(row if isinstance(row, dict) else _row(symbol, error=NOT_AVAILABLE))
                    else:
                        future.cancel()
                        rows.append(_row(symbol, error=TOO_LONG))
            finally:
                # never wait here for a slow peer; drop the ones that have not started
                pool.shutdown(wait=False, cancel_futures=True)
        return _table(rows, len(ordered))
    except Exception as exc:
        log.warning("peer benchmark failed: %s", exc)
        try:
            return _table([], len(ordered))
        except Exception:
            return {"columns": [[k, label] for k, label in COLUMNS], "rows": [],
                    "medians": {k: {"value": None, "text": None, "n": 0} for k in _KEYS},
                    "multiple_medians": {k: {"value": None, "n": 0} for k in MULTIPLES},
                    "note": NOTE, "asked": len(ordered), "answered": 0, "slow": []}
