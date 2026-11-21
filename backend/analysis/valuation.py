"""The valuation panel: six methods, each an implied value per share with a low-high range, blended
by relevance weights into one "Model value". All arithmetic here, in Python; the model (the
advisor, backend/analysis/advisor.py) only proposes relevance weights.

Ported from the original product's the original product's valuation.py:
- methods: P/E peer `_method_pe_peer` 3964-4054, P/B peer `_method_pb_peer` 4057-4108, EV/Sales
  peer `_method_ev_sales` 4111-4170, EV/EBITDA peer `_method_ev_ebitda` 3897-3961 (here EV/EBIT:
  the SEC data has operating income, not a reported EBITDA), Graham `_method_graham` 4604-4634
  (range x 0.85 / x 1.15), DCF from the scenario arithmetic (backend/analysis/scenarios.py, the
  bear / bull rules of `_dcf_scenario` 3613-3655) bridged to equity through net debt (3477-3487);
  peer median and linear P25 / P75 (`_median`, `_percentile` 226-243), peer bounds
  `_PEER_METHOD_BOUNDS` 3073-3076;
- default relevance weights: `_default_advisor_result` 2987-3041 (x 100);
- floor weights for the cross-check methods, an explicit advisor zero respected: 7692-7710;
- cohort comparability (a peer median more than 2x / 3x the company's own multiple):
  `_flag_incomparable_cohorts` 5051-5157, `_cap_marginal_cohort_shares` 5160-5173;
- data-quality factor on the relevance weight: `_data_quality_factor` 5176-5206, applied 6364-6375;
- outlier cap (value below 40% or above 250% of the price -> relevance at most 5): 6377-6402
  (the original applies it to its dividend models only; here, as the brief asks, to every method);
- blend, the +/-10% minimum range and the default band: `_blend_methods_v2` 5489-5543;
- whole-percent blend shares by largest remainder: `_largest_remainder_percents` 5371-5386;
- quality score: `_quality_score_v2` 5568-5653.

Public functions never raise: `compute` gives None on anything unexpected, `blend` gives the
valuation with empty blend values.
"""
from __future__ import annotations

import copy
import html
import logging
import math
from datetime import date

from backend import format as fmt
from backend.draft.writer import annual_fact
from backend.facts.select import fiscal_years, year_end_instant
from backend.ledger import Fact, Ledger

log = logging.getLogger(__name__)

KEYS = ("dcf", "pe_peer", "ev_ebit_peer", "ev_sales_peer", "pb_peer", "graham")
LABELS = {"dcf": "DCF (two-stage)", "pe_peer": "P/E peer relative",
          "ev_ebit_peer": "EV/EBIT peer relative", "ev_sales_peer": "EV/Sales peer relative",
          "pb_peer": "P/B peer relative", "graham": "Graham number"}
MODEL_VALUE = "Model value"
PRICE_UNIT = "USD/share"
MONEY_UNIT = "USD"

# peer multiples: the key in peer_table rows, its name, its accepted bounds
PEER_MULTIPLE = {"pe_peer": "pe", "ev_ebit_peer": "ev_ebit", "ev_sales_peer": "ev_sales", "pb_peer": "pb"}
PEER_NAME = {"pe": "P/E", "ev_ebit": "EV/EBIT", "ev_sales": "EV/Sales", "pb": "P/B"}
PEER_BOUNDS = {"pe": (2.0, 100.0), "pb": (0.05, 20.0), "ev_sales": (0.1, 20.0),
               "ev_ebit": (2.0, 100.0)}   # 3073-3076; EV/EBIT is new, given the P/E bounds
MIN_PEERS = 3              # fewer: not priced
ROBUST_PEERS = 5           # 3 or 4: a thin sample

# data-quality factors (5176-5206)
DQ_REPORTED = 1.0
DQ_THIN = 0.6
DQ_ASSUMPTION = 0.5
DQ_HEURISTIC = 0.3         # the original's ROE-adjusted book heuristic; no method here uses it

FLOOR_WEIGHTS = {"pe_peer": 20, "pb_peer": 20, "ev_ebit_peer": 20, "ev_sales_peer": 15, "graham": 15}
OUTLIER_LOW, OUTLIER_HIGH, OUTLIER_CAP = 0.40, 2.50, 5.0
MIN_HALF_WIDTH = 0.10      # a range narrower than +/-10% of its value is widened to +/-10%
DEFAULT_LOW, DEFAULT_HIGH = 0.85, 1.15
GRAHAM_BAND = 0.15
GRAHAM_CONSTANT = 22.5
SHARES_MAX_AGE_DAYS = 400
COHORT_COMPARABLE, COHORT_GAP, COHORT_UNCORROBORATED_GAP = 2.0, 3.0, 2.5

NOT_PRICED_SHARES = "no share count is available for the price date"


# ---- small helpers -------------------------------------------------------------------------------
def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _pos(value) -> float | None:
    value = _num(value)
    return value if value is not None and value > 0 else None


def _iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _e(text: str) -> str:
    return html.escape(text)


def _usable(f: Fact | None) -> Fact | None:
    return f if f is not None and f.value is not None else None


def _per_share(value: float | None) -> str | None:
    return None if value is None else fmt.fact(Fact(key="per_share", period="-", value=value, unit=PRICE_UNIT))


def _range(low: float | None, high: float | None) -> str | None:
    if low is None or high is None:
        return None
    return f"{_per_share(low)} – {_per_share(high)}"


def _multiple(value: float) -> str:
    return fmt.fact(Fact(key="multiple", period="-", value=value, unit="x"))


def _pct(value: float, signed: bool = False) -> str:
    return fmt.fact(Fact(key="change_growth" if signed else "rate", period="-", value=value, unit="ratio"))


def _date_words(d: date | None) -> str | None:
    if d is None:
        return None
    label = fmt.period_label(d.isoformat())
    return label[len("as of "):] if label.startswith("as of ") else label


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (numpy's default, as the original's `_percentile`)."""
    data = sorted(values)
    if not data:
        return None
    pos = (len(data) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def peer_values(peer_table: dict | None, multiple: str) -> list[float]:
    """The peers' values of one multiple: positive, finite and inside the original's bounds."""
    lo, hi = PEER_BOUNDS[multiple]
    out = []
    rows = peer_table.get("rows") if isinstance(peer_table, dict) else None
    for row in rows if isinstance(rows, list) else ():
        multiples = row.get("multiples") if isinstance(row, dict) else None
        value = _num(multiples.get(multiple)) if isinstance(multiples, dict) else None
        if value is not None and lo <= value <= hi:
            out.append(value)
    return out


# ---- the company's own inputs --------------------------------------------------------------------
def _shares(ledger: Ledger, price_day: date | None, supplied, supplied_note: str | None) -> dict:
    """The newest reported share count when it is at most 400 days older than the price date,
    else the supplied (market data) count, else nothing with the reason."""
    newest = None
    for period in ledger.periods("shares_outstanding"):
        f = _usable(ledger.get("shares_outstanding", period))
        if f is not None and f.value > 0 and f.unit == "shares":
            newest = f
            break
    if newest is not None:
        day = _iso(newest.period)
        if price_day is None or day is None or (price_day - day).days <= SHARES_MAX_AGE_DAYS:
            return {"value": newest.value, "fact": newest, "text": fmt.fact(newest),
                    "html": fmt.cited(newest, ledger),
                    "note": f"Shares outstanding as reported, {fmt.period_label(newest.period)} (from the filings)",
                    "reason": None}
    count = _pos(supplied)
    if count is not None:
        text = fmt.fact(Fact(key="shares", period="-", value=count, unit="shares"))
        note = supplied_note or "Share count from market data"
        return {"value": count, "fact": None, "text": text, "html": _e(f"{text} ({note})"),
                "note": note, "reason": None}
    reason = (f"the newest reported share count ({fmt.period_label(newest.period)}) is more than "
              f"{SHARES_MAX_AGE_DAYS} days older than the price date and no current count was given"
              if newest is not None else "no share count is in the sources")
    return {"value": None, "fact": None, "text": None, "html": None, "note": None, "reason": reason}


def _net_debt(ledger: Ledger, year: int, ye: str | None) -> dict:
    """The ledger's net_debt for the fiscal year, else long_term_debt - cash - short-term
    investments at the year end (the investments only when the ledger holds them)."""
    from backend.analysis.scenarios import short_term_investments
    held = _usable(ledger.get("net_debt", f"FY{year}"))
    if held is not None and held.unit == MONEY_UNIT:
        return {"value": held.value, "html": fmt.cited(held, ledger), "reason": None}
    debt = _usable(ledger.get("long_term_debt", ye)) if ye else None
    cash = _usable(ledger.get("cash", ye)) if ye else None
    if debt is None or cash is None:
        return {"value": None, "html": None,
                "reason": "net debt is not available (long-term debt or cash at the fiscal year end is missing)"}
    sti = short_term_investments(ledger, year)
    if any(f is not None and f.unit != MONEY_UNIT for f in (debt, cash, sti)):
        return {"value": None, "html": None, "reason": "debt or cash is not reported in US dollars"}
    html_text = fmt.cited(debt, ledger) + _e(" less cash ") + fmt.cited(cash, ledger)
    if sti is not None:
        html_text += _e(" less short-term investments ") + fmt.cited(sti, ledger)
    return {"value": debt.value - cash.value - (sti.value if sti is not None else 0.0),
            "html": html_text, "reason": None}


def _money(ledger: Ledger, key: str, period: str | None, unit: str = MONEY_UNIT) -> Fact | None:
    f = _usable(ledger.get(key, period)) if period else None
    return f if f is not None and f.unit == unit else None


def default_weights(ledger: Ledger, year: int, ye: str | None, financial: bool = False) -> dict[str, int]:
    """The original's deterministic fallback weights (2987-3009, x 100), without its sector table.
    A bank or insurer: book value and earnings methods only (P/B 60, P/E 50, Graham 20)."""
    if financial:
        return {"dcf": 0, "pe_peer": 50, "ev_ebit_peer": 0, "ev_sales_peer": 0, "pb_peer": 60, "graham": 20}
    fy = f"FY{year}"
    fcf = _usable(ledger.get("free_cash_flow", fy))
    # profit: net income, or diluted EPS when net income is not in the ledger
    ni = _usable(ledger.get("net_income", fy)) or _usable(ledger.get("eps_diluted", fy))
    rev = _usable(ledger.get("revenue", fy))
    eq = _usable(ledger.get("shareholders_equity", ye)) if ye else None
    positive = lambda f: f is not None and f.value > 0  # noqa: E731
    return {"dcf": 60 if positive(fcf) else 20,
            "pe_peer": 50 if positive(ni) else 10,
            "ev_ebit_peer": 40,
            "ev_sales_peer": 30 if positive(rev) else 0,
            "pb_peer": 30,
            "graham": 20 if positive(ni) and positive(eq) else 0}


# ---- one method row ------------------------------------------------------------------------------
def _row(key: str, defaults: dict, *, basis: str, inputs_html: str = "", value=None, low=None,
         high=None, reason: str | None = None, n_peers: int | None = None, data_quality: float = DQ_REPORTED,
         own_multiple: float | None = None, peer_median: float | None = None,
         uses_assumption: bool = False) -> dict:
    value = _num(value)
    if reason is None and (value is None or value <= 0):
        reason = "the arithmetic gives no positive value"
    if reason is not None:
        value = low = high = None
    else:
        low, high = _num(low), _num(high)
    return {"key": key, "label": LABELS[key], "basis": basis, "inputs_html": inputs_html,
            "value": value, "low": low, "high": high,
            "value_text": _per_share(value), "range_text": _range(low, high),
            "reason": reason, "n_peers": n_peers, "data_quality": data_quality,
            "floor": key in FLOOR_WEIGHTS, "default_weight": int(defaults.get(key, 0)),
            "own_multiple": own_multiple, "peer_median": peer_median,
            "uses_assumption": uses_assumption}


def _peer_stats(peer_table: dict | None, key: str) -> dict:
    multiple = PEER_MULTIPLE[key]
    values = peer_values(peer_table, multiple)
    n = len(values)
    out = {"multiple": multiple, "name": PEER_NAME[multiple], "n": n, "values": values,
           "median": None, "p25": None, "p75": None, "dq": DQ_REPORTED, "text": "", "reason": None}
    if n < MIN_PEERS:
        out["reason"] = (f"at least {MIN_PEERS} peers with a {PEER_NAME[multiple]} are needed "
                         f"({n} available); no sector multiple is substituted")
        return out
    out.update(median=percentile(values, 50), p25=percentile(values, 25), p75=percentile(values, 75))
    out["dq"] = DQ_REPORTED if n >= ROBUST_PEERS else DQ_THIN
    sample = "robust sample" if n >= ROBUST_PEERS else "thin sample"
    out["text"] = (f"peer {PEER_NAME[multiple]} median {_multiple(out['median'])} (n={n}, {sample}; "
                   f"P25 {_multiple(out['p25'])}, P75 {_multiple(out['p75'])})")
    return out


def _dcf(ctx: dict) -> dict:
    basis = ("Enterprise value from the scenario arithmetic (base case) less net debt, divided by the "
             "share count; range from the bear case at the higher discount rate to the bull case at "
             "the lower one.")
    sc = ctx["scenarios"]
    cases = {c.get("key"): c for c in (sc or {}).get("cases") or [] if isinstance(c, dict)}
    base = cases.get("base") or {}
    ev = _pos(base.get("base"))
    if sc is None:
        return _row("dcf", ctx["defaults"], basis=basis,
                    reason="no projection: free cash flow is missing or not positive")
    if ev is None:
        return _row("dcf", ctx["defaults"], basis=basis,
                    reason="the base discount rate gives no valid projection (too close to terminal growth)")
    nd, sh = ctx["net_debt"], ctx["shares"]
    if nd["value"] is None:
        return _row("dcf", ctx["defaults"], basis=basis, reason=nd["reason"] + ", so enterprise value cannot be bridged to equity")
    if sh["value"] is None:
        return _row("dcf", ctx["defaults"], basis=basis, reason=sh["reason"])
    per = lambda x: None if _num(x) is None else max((x - nd["value"]) / sh["value"], 0.0)  # noqa: E731
    value = (ev - nd["value"]) / sh["value"]
    if value <= 0:
        return _row("dcf", ctx["defaults"], basis=basis,
                    reason="the enterprise value does not cover net debt, so no equity value remains")
    inputs = (_e(f"enterprise value {base.get('base_text')} (scenario arithmetic, base case) less net debt ")
              + nd["html"] + _e(", divided by ") + sh["html"])
    assumed = ctx["growth_assumed"]
    return _row("dcf", ctx["defaults"], basis=basis, inputs_html=inputs, value=value,
                low=per((cases.get("bear") or {}).get("low")), high=per((cases.get("bull") or {}).get("high")),
                data_quality=DQ_ASSUMPTION if assumed else DQ_REPORTED, uses_assumption=assumed)


def _pe(ctx: dict) -> dict:
    basis = (f"Peer median P/E times the company's own diluted EPS for {ctx['period_label']}; range "
             "from the peer 25th to the 75th percentile.")
    eps = ctx["eps"]
    if eps is None:
        return _row("pe_peer", ctx["defaults"], basis=basis,
                    reason=f"diluted EPS in US dollars for {ctx['period_label']} is not in the sources")
    if eps.value <= 0:
        return _row("pe_peer", ctx["defaults"], basis=basis, reason="diluted EPS is zero or negative")
    st = _peer_stats(ctx["peer_table"], "pe_peer")
    if st["reason"]:
        return _row("pe_peer", ctx["defaults"], basis=basis, reason=st["reason"], n_peers=st["n"])
    own = ctx["price"] / eps.value if ctx["price"] else None
    return _row("pe_peer", ctx["defaults"], basis=basis,
                inputs_html=_e("diluted EPS ") + fmt.cited(eps, ctx["ledger"]) + _e(f" x {st['text']}"),
                value=st["median"] * eps.value, low=st["p25"] * eps.value, high=st["p75"] * eps.value,
                n_peers=st["n"], data_quality=st["dq"], own_multiple=own, peer_median=st["median"])


def _ev_peer(ctx: dict, key: str, metric: Fact | None, metric_words: str) -> dict:
    name = PEER_NAME[PEER_MULTIPLE[key]]
    basis = (f"Peer median {name} times the company's own {metric_words} for {ctx['period_label']} "
             "gives an enterprise value; less net debt, divided by the share count; range from the "
             "peer 25th to the 75th percentile.")
    if metric is None:
        return _row(key, ctx["defaults"], basis=basis,
                    reason=f"{metric_words} in US dollars for {ctx['period_label']} is not in the sources")
    if metric.value <= 0:
        return _row(key, ctx["defaults"], basis=basis, reason=f"{metric_words} is zero or negative")
    nd, sh = ctx["net_debt"], ctx["shares"]
    if nd["value"] is None:
        return _row(key, ctx["defaults"], basis=basis, reason=nd["reason"])
    if sh["value"] is None:
        return _row(key, ctx["defaults"], basis=basis, reason=sh["reason"])
    st = _peer_stats(ctx["peer_table"], key)
    if st["reason"]:
        return _row(key, ctx["defaults"], basis=basis, reason=st["reason"], n_peers=st["n"])
    per = lambda multiple: (multiple * metric.value - nd["value"]) / sh["value"]  # noqa: E731
    value = per(st["median"])
    if value <= 0:
        return _row(key, ctx["defaults"], basis=basis, n_peers=st["n"],
                    reason="the implied enterprise value does not cover net debt")
    own = ((ctx["price"] * sh["value"] + nd["value"]) / metric.value) if ctx["price"] else None
    inputs = (_e(f"{metric_words} ") + fmt.cited(metric, ctx["ledger"]) + _e(f" x {st['text']}, less net debt ")
              + nd["html"] + _e(", divided by ") + sh["html"])
    return _row(key, ctx["defaults"], basis=basis, inputs_html=inputs, value=value,
                low=max(per(st["p25"]), 0.0), high=max(per(st["p75"]), 0.0), n_peers=st["n"],
                data_quality=st["dq"], own_multiple=own if own and own > 0 else None,
                peer_median=st["median"])


def _book_per_share(ctx: dict) -> tuple[float | None, str | None, str | None]:
    """(book value per share, its inputs HTML, the reason it is missing)."""
    eq, sh = ctx["equity"], ctx["shares"]
    if eq is None:
        return None, None, "book equity in US dollars at the fiscal year end is not in the sources"
    if eq.value <= 0:
        return None, None, "book equity is zero or negative"
    if sh["value"] is None:
        return None, None, sh["reason"]
    bvps = eq.value / sh["value"]
    return bvps, (_e("book equity ") + fmt.cited(eq, ctx["ledger"]) + _e(" divided by ") + sh["html"]
                  + _e(f" = book value per share {_per_share(bvps)}")), None


def _pb(ctx: dict) -> dict:
    basis = ("Peer median P/B times the company's own book value per share (book equity at the "
             "fiscal year end divided by the share count); range from the peer 25th to the 75th percentile.")
    bvps, bvps_html, why = _book_per_share(ctx)
    if why:
        return _row("pb_peer", ctx["defaults"], basis=basis, reason=why)
    st = _peer_stats(ctx["peer_table"], "pb_peer")
    if st["reason"]:
        return _row("pb_peer", ctx["defaults"], basis=basis, reason=st["reason"], n_peers=st["n"])
    own = ctx["price"] / bvps if ctx["price"] else None
    return _row("pb_peer", ctx["defaults"], basis=basis, inputs_html=bvps_html + _e(f" x {st['text']}"),
                value=st["median"] * bvps, low=st["p25"] * bvps, high=st["p75"] * bvps, n_peers=st["n"],
                data_quality=st["dq"], own_multiple=own, peer_median=st["median"])


def _graham(ctx: dict) -> dict:
    basis = ("Square root of 22.5 x diluted EPS x book value per share (the Graham number); range "
             "plus or minus 15%, a fixed sensitivity band.")
    eps = ctx["eps"]
    if eps is None or eps.value <= 0:
        return _row("graham", ctx["defaults"], basis=basis,
                    reason="needs positive diluted EPS in US dollars")
    bvps, bvps_html, why = _book_per_share(ctx)
    if why:
        return _row("graham", ctx["defaults"], basis=basis, reason=why)
    value = math.sqrt(GRAHAM_CONSTANT * eps.value * bvps)
    return _row("graham", ctx["defaults"], basis=basis,
                inputs_html=_e("diluted EPS ") + fmt.cited(eps, ctx["ledger"]) + _e("; ") + bvps_html,
                value=value, low=value * (1 - GRAHAM_BAND), high=value * (1 + GRAHAM_BAND))


# ---- compute -------------------------------------------------------------------------------------
FINANCIAL_REASON = ("not used for a bank or insurer: enterprise value and free cash flow do not "
                    "describe a company whose debt and cash are its business")
FINANCIAL_KEYS = ("dcf", "ev_ebit_peer", "ev_sales_peer")


def compute(ledger: Ledger, *, price: float | None, price_date: str | None, shares: float | None = None,
            shares_note: str | None = None, scenarios: dict | None = None,
            peer_table: dict | None = None, financial: bool = False) -> dict | None:
    """Every method's implied value per share for the latest fiscal year (see the module text).
    `financial` (a bank or insurer): the DCF and the enterprise-value methods are not priced and
    say why; the default weights favour book value and earnings. None only when the ledger has
    no fiscal year (or on an unexpected error, logged)."""
    try:
        return _compute(ledger, price=price, price_date=price_date, shares=shares,
                        shares_note=shares_note, scenarios=scenarios, peer_table=peer_table,
                        financial=bool(financial))
    except Exception:
        log.exception("valuation.compute failed")
        return None


def _compute(ledger, *, price, price_date, shares, shares_note, scenarios, peer_table, financial) -> dict | None:
    years = fiscal_years(ledger)
    if not years:
        return None
    year = years[0]
    fy, ye = f"FY{year}", year_end_instant(ledger, year)
    price_value = _pos(price)
    price_day = _iso(price_date)
    defaults = default_weights(ledger, year, ye, financial)
    sh = _shares(ledger, price_day, shares, shares_note)
    nd = _net_debt(ledger, year, ye)
    eps = annual_fact(ledger, "eps_diluted", year)
    eps = eps if eps is not None and eps.value is not None and eps.unit == PRICE_UNIT else None
    ctx = {"ledger": ledger, "price": price_value, "defaults": defaults, "shares": sh, "net_debt": nd,
           "eps": eps, "equity": _money(ledger, "shareholders_equity", ye),
           "period_label": fmt.period_label(fy), "peer_table": peer_table,
           "scenarios": scenarios if isinstance(scenarios, dict) else None,
           "growth_assumed": ledger.get("revenue_growth_estimate", fy) is None}
    if financial:
        # the basis sentence stays: the reader sees what the method is and why it is not used
        not_used = {key: _row(key, defaults, basis=basis, reason=FINANCIAL_REASON)
                    for key, basis in (("dcf", "Enterprise value from the scenario arithmetic less net debt, "
                                               "divided by the share count."),
                                       ("ev_ebit_peer", "Peer median EV/EBIT times operating income, less "
                                                        "net debt, divided by the share count."),
                                       ("ev_sales_peer", "Peer median EV/Sales times revenue, less net "
                                                         "debt, divided by the share count."))}
    else:
        not_used = {}
    methods = [
        not_used.get("dcf") or _dcf(ctx),
        _pe(ctx),
        not_used.get("ev_ebit_peer") or _ev_peer(ctx, "ev_ebit_peer", _money(ledger, "operating_income", fy),
                                                 "operating income"),
        not_used.get("ev_sales_peer") or _ev_peer(ctx, "ev_sales_peer", _money(ledger, "revenue", fy), "revenue"),
        _pb(ctx),
        _graham(ctx),
    ]
    market_cap = price_value * sh["value"] if price_value and sh["value"] else None
    has = lambda key, period: _usable(ledger.get(key, period)) is not None  # noqa: E731
    beta_from_market = bool(ctx["scenarios"]) and any(
        a.get("label") == "Beta" and "(market data" in str(a.get("value_html"))
        for a in ctx["scenarios"].get("assumptions") or [] if isinstance(a, dict))
    completeness = {
        "beta": beta_from_market,
        "cost_of_equity": bool(ctx["scenarios"]),
        "earnings_yield": market_cap is not None and has("net_income", fy),
        "fcf_yield": market_cap is not None and has("free_cash_flow", fy),
        "ev_revenue": market_cap is not None and nd["value"] is not None and has("revenue", fy),
        "debt_equity": bool(ye) and has("long_term_debt", ye) and has("shareholders_equity", ye),
        "roic": nd["value"] is not None and has("operating_income", fy) and bool(ye) and has("shareholders_equity", ye),
    }
    return {
        "period_label": fmt.period_label(fy),
        "price": price_value,
        "price_text": _per_share(price_value),
        "price_date_text": _date_words(price_day),
        "shares_text": sh["text"],
        "shares_note": sh["note"],
        "methods": methods,
        "priced": sum(1 for m in methods if m["value"] is not None),
        "total": len(methods),
        "financial": financial,
        "context": {"period_end": ye, "price_date": price_day.isoformat() if price_day else None,
                    "years": len(years), "completeness": completeness,
                    "beta_assumed": bool(ctx["scenarios"]) and not beta_from_market},
    }


# ---- blend ---------------------------------------------------------------------------------------
def _cohort_factor(dev: float, corroborated: bool) -> float:
    """5085-5092: 1 within 2x, 0 at 3x (2.5x without a second comparable cohort), log taper between."""
    if dev <= COHORT_COMPARABLE:
        return 1.0
    gap = COHORT_GAP if corroborated else COHORT_UNCORROBORATED_GAP
    if dev >= gap:
        return 0.0
    return math.log(gap / dev) / math.log(gap / COHORT_COMPARABLE)


def largest_remainder_percents(shares: dict) -> dict:
    """Whole percents summing to exactly 100 (5371-5386)."""
    total = sum(s for s in shares.values() if s and s > 0)
    if total <= 0:
        return {key: 0 for key in shares}
    exact = {key: (s / total * 100 if s and s > 0 else 0.0) for key, s in shares.items()}
    floors = {key: int(math.floor(v)) for key, v in exact.items()}
    left = 100 - sum(floors.values())
    for key in sorted(exact, key=lambda k: exact[k] - floors[k], reverse=True)[:max(left, 0)]:
        floors[key] += 1
    return floors


def _empty_blend(basis: str) -> dict:
    return {"label": MODEL_VALUE, "value": None, "low": None, "high": None, "value_text": None,
            "range_text": None, "vs_price": None, "vs_price_text": None, "basis": basis}


def blend(valuation: dict, weights: dict | None = None, *, rationale_html: str | None = None,
          advisor_method: str = "default") -> dict:
    """A new dict: the valuation plus each method's weight, blend share and note, the blended Model
    value with its range, the quality score, the advisor and the methodology paragraph."""
    try:
        return _blend(valuation, weights, rationale_html, advisor_method)
    except Exception:
        log.exception("valuation.blend failed")
        out = copy.deepcopy(valuation) if isinstance(valuation, dict) else {}
        out.update(blend=_empty_blend("Not computed"), quality={"score": 0, "text": "0", "parts": []},
                   advisor={"method": advisor_method, "rationale_html": rationale_html}, methodology="")
        return out


def _blend(valuation: dict, weights: dict | None, rationale_html: str | None, advisor_method: str) -> dict:
    out = copy.deepcopy(valuation)
    methods = out.get("methods") or []
    price = _pos(out.get("price"))
    use_default = not weights
    rel: dict[str, float] = {}
    notes: dict[str, list[str]] = {m["key"]: [] for m in methods}
    share_caps: dict[str, float] = {}

    # 1. relevance weights, floors (7692-7710)
    for m in methods:
        key = m["key"]
        if use_default:
            given, present = float(m.get("default_weight") or 0), True
        else:
            raw = _num(weights.get(key)) if key in weights else None
            present = raw is not None
            given = max(0.0, min(100.0, raw)) if present else 0.0
        m["weight"] = int(round(given))
        explicit_zero = present and given == 0
        w = given
        if m.get("floor") and not explicit_zero and w < FLOOR_WEIGHTS.get(key, 0):
            w = float(FLOOR_WEIGHTS[key])
            if m["value"] is not None:
                notes[key].append(f"raised to the floor weight of {FLOOR_WEIGHTS[key]}")
        if explicit_zero and m["value"] is not None:
            notes[key].append("excluded by the advisor" if not use_default else "excluded: default weight 0")
        elif not present and not m.get("floor") and m["value"] is not None:
            notes[key].append("excluded: the advisor gave it no weight")
        rel[key] = w if m["value"] is not None else 0.0

    # 2. cohort comparability (5095-5157), only with a price
    if price:
        devs = {m["key"]: max(r, 1 / r) for m in methods
                if m["value"] is not None and _pos(m.get("own_multiple")) and _pos(m.get("peer_median"))
                for r in [m["peer_median"] / m["own_multiple"]]}
        comparable = {k for k, d in devs.items() if d <= COHORT_COMPARABLE}
        for key, dev in devs.items():
            if dev <= COHORT_COMPARABLE or rel[key] <= 0:
                continue
            factor = _cohort_factor(dev, any(k != key for k in comparable))
            ratio = _multiple(dev)
            if factor > 0:
                rel[key] *= factor
                share_caps[key] = factor
                notes[key].append(f"marginal cohort: the peer median is {ratio} away from the "
                                  "company's own multiple, weight tapered")
            else:
                rel[key] = 0.0
                notes[key].append(f"cohort not comparable: the peer median is {ratio} away from the "
                                  "company's own multiple; reference only")

    # 3. data-quality factor (5176-5206, 6364-6375)
    for m in methods:
        key = m["key"]
        if rel[key] > 0 and m.get("data_quality", 1.0) < 1.0:
            rel[key] *= m["data_quality"]
            if m["data_quality"] == DQ_THIN:
                notes[key].append(f"thin peer sample (n={m.get('n_peers')})")
            elif m["data_quality"] == DQ_ASSUMPTION:
                notes[key].append("assumed growth input")

    # 4. outlier cap (6377-6402), only with a price
    if price:
        for m in methods:
            key, v = m["key"], m["value"]
            if v is None or rel[key] <= 0:
                continue
            if v < price * OUTLIER_LOW or v > price * OUTLIER_HIGH:
                if rel[key] > OUTLIER_CAP:
                    notes[key].append("outlier: capped at 5%")
                rel[key] = min(rel[key], OUTLIER_CAP)

    # 5. a marginal cohort's blend share never exceeds its factor (5160-5173)
    for key, cap in share_caps.items():
        others = sum(w for k, w in rel.items() if k != key and w > 0)
        limit = others * cap / (1.0 - cap) if cap < 1.0 else rel[key]
        if rel[key] > limit + 1e-12:
            rel[key] = limit

    # 6. ranges: at least +/-10%, default band when a side is missing (5493-5520)
    for m in methods:
        v = m["value"]
        if v is None:
            continue
        lo, hi = m["low"], m["high"]
        if lo is not None and hi is not None and hi - lo < 2 * MIN_HALF_WIDTH * v:
            lo, hi = v * (1 - MIN_HALF_WIDTH), v * (1 + MIN_HALF_WIDTH)
            notes[m["key"]].append("range widened to plus or minus 10%")
        if lo is None:
            lo = v * DEFAULT_LOW
        if hi is None:
            hi = v * DEFAULT_HIGH
        m["low"], m["high"], m["range_text"] = lo, hi, _range(lo, hi)

    # 7. the blend (5522-5543)
    active = [m for m in methods if m["value"] is not None and rel[m["key"]] > 0]
    total = sum(rel[m["key"]] for m in active)
    if active and total > 0:
        value = sum(m["value"] * rel[m["key"]] for m in active) / total
        low = min(sum(m["low"] * rel[m["key"]] for m in active) / total, value)
        high = max(sum(m["high"] * rel[m["key"]] for m in active) / total, value)
        vs = value / price - 1 if price else None
        result = {"label": MODEL_VALUE, "value": value, "low": low, "high": high,
                  "value_text": _per_share(value), "range_text": _range(low, high),
                  "vs_price": vs, "vs_price_text": _pct(vs, signed=True) if vs is not None else None,
                  "basis": f"Weight-blended average of {len(active)} priced methods"}
    else:
        result = _empty_blend("No method priced" if not any(m["value"] is not None for m in methods)
                              else "No priced method carries weight")
    shares = {m["key"]: (rel[m["key"]] / total if total > 0 and m in active else 0.0) for m in methods}
    percents = largest_remainder_percents(shares)
    for m in methods:
        key = m["key"]
        m["share"] = shares[key]
        m["share_text"] = f"{percents[key]}%" if m["value"] is not None else None
        m["blend_weight"] = rel[key]
        m["note"] = "; ".join(notes[key]) or None

    # a score says how far the blended value can be relied on: with nothing priced there is none
    quality = _quality(out, active) if active else None
    out["blend"] = result
    out["quality"] = quality
    out["advisor"] = {"method": advisor_method if advisor_method in ("model", "default") else "default",
                      "rationale_html": rationale_html}
    out["methodology"] = _methodology(out, price is not None, quality["score"] if quality else None, use_default)
    return out


# ---- quality score (5568-5653) -------------------------------------------------------------------
def _quality(valuation: dict, active: list[dict]) -> dict:
    ctx = valuation.get("context") or {}
    parts = []
    n = len(active)
    base = min(60, 20 + 10 * n)
    parts.append({"label": "Priced methods in the blend", "text": f"{n}: +{base} (20 plus 10 each, at most 60)"})

    recency = 0
    end, as_of = _iso(ctx.get("period_end")), _iso(ctx.get("price_date")) or date.today()
    if end is not None:
        months = max(0.0, (as_of - end).days / 30.0)
        recency = 15 if months <= 6 else 10 if months <= 12 else 5 if months <= 18 else 0
        parts.append({"label": "Data recency",
                      "text": f"fiscal year ended {_date_words(end)}: +{recency}"})
    else:
        parts.append({"label": "Data recency", "text": "fiscal year end not recorded: +0"})

    agreement = 0
    values = [m["value"] for m in active]
    if len(values) >= 2:
        mean = sum(values) / len(values)
        cv = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / mean if mean > 0 else None
        if cv is not None:
            agreement = (15 if cv < 0.10 else 10 if cv < 0.20 else 5 if cv < 0.30
                         else -10 if cv > 0.50 else -5 if cv > 0.40 else 0)
            parts.append({"label": "Agreement between methods",
                          "text": f"spread (coefficient of variation) {_pct(cv)}: {agreement:+d}"})
    else:
        parts.append({"label": "Agreement between methods", "text": "fewer than two methods: +0"})

    years = int(ctx.get("years") or 0)
    depth = 10 if years >= 5 else 5 if years >= 3 else 0
    parts.append({"label": "History", "text": f"{years} fiscal years in the sources: +{depth}"})

    filled = sum(1 for v in (ctx.get("completeness") or {}).values() if v)
    fill = filled / 7
    complete = 5 if fill >= 0.80 else 3 if fill >= 0.50 else 0
    parts.append({"label": "Completeness", "text": f"{filled} of 7 supporting measures: +{complete}"})

    deductions = []
    if any(m.get("uses_assumption") for m in active):
        deductions.append(("assumed growth input", 5))
    if ctx.get("beta_assumed"):
        deductions.append(("beta assumed, not measured", 3))
    if any(m.get("data_quality") == DQ_THIN for m in active):
        deductions.append(("thin peer sample", 2))
    penalty = sum(p for _w, p in deductions)
    parts.append({"label": "Deductions",
                  "text": "; ".join(f"{w} -{p}" for w, p in deductions) if deductions else "none"})
    parts.append({"label": "Cross-sectional model", "text": "not part of this build: +0"})
    score = int(max(0, min(100, base + recency + agreement + depth + complete - penalty)))
    return {"score": score, "text": str(score), "parts": parts}


def _methodology(out: dict, has_price: bool, score: int | None, use_default: bool) -> str:
    priced, total = out.get("priced", 0), out.get("total", len(KEYS))
    who = ("The advisor model gives each method a relevance weight from 0 to 100"
           if not use_default else "Each method carries a default relevance weight from 0 to 100 (no advisor answer)")
    text = (
        f"Methodology: {who}; {priced} of {total} methods priced on these filings and each unpriced "
        "method shows its reason. "
        + ("For a bank or insurer the DCF and the enterprise-value multiples are not used, because "
           "enterprise value and free cash flow do not describe a company whose debt and cash are "
           "its business; book value and earnings methods carry the weight. "
           if out.get("financial") else "")
        + "Relevance is multiplied by a data-quality factor (1.0 for reported "
        "figures or five or more peers, 0.6 for a thin sample of three or four peers, 0.5 when the "
        "growth input is an assumption) before blending. A method with weight 0 is excluded. The "
        "cross-check methods (the four peer multiples and the Graham number) keep a minimum weight of "
        "15 to 20 unless the weight is exactly 0. ")
    if has_price:
        text += ("A peer multiple whose median is more than three times (or under a third of) the "
                 "company's own multiple is shown for reference only, and between two and three times "
                 "its weight tapers. A method whose value is below 40% or above 250% of the share price "
                 "is an outlier and its weight is capped at 5. ")
    else:
        text += "With no share price, the cohort and outlier rules are not applied. "
    text += (
        "Each value is computed on its own, then blended by weight; the blend shares sum to 100%. "
        "Ranges: bear case to bull case for the DCF, the peer 25th to 75th percentile for the "
        "multiples, plus or minus 15% for the Graham number; a range narrower than plus or minus 10% "
        "of its value is widened to 10%. The blended range is the weight-blended low and high. "
        + (f"Quality score ({score} of 100) counts the priced methods, their agreement, data recency, "
           "history and completeness, less deductions for assumed inputs and thin samples."
           if score is not None else "No quality score is given because no method could be priced."))
    return text
