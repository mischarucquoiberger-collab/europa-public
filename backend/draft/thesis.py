"""The investment thesis and the bull / bear points of the report.

Code decides, the model only words:
- `signals(ledger)` applies fixed rules (the RULES table below) to the ledger's annual facts and
  returns the favourable (bull) and unfavourable (bear) findings, each with the facts it cites and
  a sentence built in code from `[[F:key|period]]` placeholders (no typed digit, no advice, no
  forecast, no cause). It may add one computed fact, `cash_conversion`.
- `build(...)` makes ONE model call that words the chosen points with the same tokens, and runs
  every sentence through `backend.verify.audit.apply`. A model sentence that is missing, breaks a
  rule of this module (other tokens, a contrary direction word, a forecast or a cause) or is
  removed by the audit is replaced by the code sentence; every removed sentence is listed.

"latest" is the report's fiscal year (`_current_year`), "prior" the fiscal year before it. A rule
fires only when every fact it needs is held with a value. Thresholds: a growth rate under
RATIO_STEP (0.1 percentage point) is ignored; a margin, a return or long-term debt to equity must
move by at least MARGIN_STEP (0.5 percentage point); a change in an amount that does not show once
the two values are formatted is ignored. A growth rate is never cited when either year's base is
zero or negative (growth from a negative base is not meaningful).

Banks, insurers and other financial companies (`financial=True`, SIC 6000 to 6799): operating cash
flow is trading and lending flows and debt is funding, so the cash rules, the debt rules and the
gross-margin rules do not fire, and the thesis has no cash line and describes the balance sheet by
total assets and shareholders' equity.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend import format as fmt
from backend.facts import metrics
from backend.ledger import Fact, LedgerError
from backend.verify import audit

# id: (side, dimension, weight, rule in plain words, no digits). Larger weight first; ties by id.
# one reply carries up to twelve sentences and each figure is a long placeholder
MAX_TOKENS = 1600

RULES: dict[str, tuple[str, str, float, str]] = {
    "net_loss":                ("bear", "profitability", 0.95, "The company reported a net loss"),
    "revenue_growth_up":       ("bull", "growth", 0.90, "Revenue rose from the year before"),
    "revenue_growth_down":     ("bear", "growth", 0.90, "Revenue fell from the year before"),
    "operating_margin_up":     ("bull", "profitability", 0.85, "The operating margin widened from the year before"),
    "operating_margin_down":   ("bear", "profitability", 0.85, "The operating margin narrowed from the year before"),
    "free_cash_flow_negative": ("bear", "cash", 0.82, "Free cash flow was negative"),
    "free_cash_flow_up":       ("bull", "cash", 0.80, "Free cash flow was positive and higher than the year before"),
    "free_cash_flow_down":     ("bear", "cash", 0.80, "Free cash flow fell from the year before"),
    "negative_equity":         ("bear", "balance_sheet", 0.80, "Shareholders' equity was negative"),
    "net_income_growth_up":    ("bull", "growth", 0.75, "Net income rose from the year before"),
    "net_income_growth_down":  ("bear", "growth", 0.75, "Net income fell from the year before"),
    "revenue_trend_up":        ("bull", "growth", 0.70, "Revenue rose in each of the last three years"),
    "revenue_trend_down":      ("bear", "growth", 0.70, "Revenue fell in at least two of the last three years"),
    "cash_conversion_high":    ("bull", "cash", 0.65, "Operating cash flow was between one and two times net income"),
    "cash_conversion_low":     ("bear", "cash", 0.65, "Operating cash flow was well below net income"),
    "debt_to_equity_down":     ("bull", "balance_sheet", 0.60, "Long-term debt to equity fell from the year before"),
    "debt_to_equity_up":       ("bear", "balance_sheet", 0.60, "Long-term debt to equity rose from the year before"),
    "cash_covers_debt":        ("bull", "balance_sheet", 0.55, "Cash at the year end covered long-term debt"),
    "eps_diluted_up":          ("bull", "per_share", 0.55, "Diluted earnings per share rose from the year before"),
    "eps_diluted_down":        ("bear", "per_share", 0.55, "Diluted earnings per share fell from the year before"),
    "gross_margin_up":         ("bull", "profitability", 0.50, "The gross margin widened from the year before"),
    "gross_margin_down":       ("bear", "profitability", 0.50, "The gross margin narrowed from the year before"),
    "return_on_equity_up":     ("bull", "profitability", 0.45, "Return on equity rose from the year before"),
    "return_on_equity_down":   ("bear", "profitability", 0.45, "Return on equity fell from the year before"),
    "share_count_down":        ("bull", "per_share", 0.40, "The share count fell"),
    "share_count_up":          ("bear", "per_share", 0.40, "The share count rose by more than a small margin"),
    "dividends_per_share_up":  ("bull", "per_share", 0.35, "Dividends per share rose from the year before"),
    "dividends_per_share_down": ("bear", "per_share", 0.35, "Dividends per share fell from the year before"),
}

DIMENSIONS = ("growth", "profitability", "cash", "balance_sheet", "per_share")
THESIS_TITLES = {"growth": "Growth", "profitability": "Profitability", "cash": "Cash flow",
                 "balance_sheet": "Balance sheet"}
MAX_PER_SIDE = 4
MAX_PER_DIMENSION = 2          # first pass of the pick; the rest only fills free places
RATIO_STEP = 0.001             # 0.1 percentage point: growth rates
MARGIN_STEP = 0.005            # 0.5 percentage point: margins, returns, long-term debt to equity
SHARE_RISE = 0.01              # the share count must rise by more than this share to count
CONVERSION_HIGH = 1.0          # bull only from 1.0 ...
CONVERSION_CAP = 2.0           # ... to 2.0: above it net income is too low for the ratio to mean strength
CONVERSION_LOW = 0.8
MAX_SENTENCE_CHARS = 400
# Rules that do not describe a bank or an insurer (see the module docstring).
NOT_FOR_FINANCIALS = frozenset({
    "free_cash_flow_negative", "free_cash_flow_up", "free_cash_flow_down",
    "cash_conversion_high", "cash_conversion_low", "debt_to_equity_up", "debt_to_equity_down",
    "cash_covers_debt", "gross_margin_up", "gross_margin_down"})
_STEP = {"operating_margin": MARGIN_STEP, "gross_margin": MARGIN_STEP,
         "return_on_equity": MARGIN_STEP, "debt_to_equity": MARGIN_STEP}

# Labels for the prompt where backend.facts.metrics has none.
_LABELS = {"cash_conversion": "Cash conversion (operating cash flow / net income)"}

_FY_RE = re.compile(r"^FY(\d{4})$")
_UP_WORDS = re.compile(r"\b(?:rose|rise|rising|risen|increas\w*|grew|grow\w*|higher|widen\w*|"
                       r"improv\w*|expand\w*|gain\w*|climb\w*|up)\b", re.IGNORECASE)
_DOWN_WORDS = re.compile(r"\b(?:fell|fall\w*|declin\w*|decreas\w*|drop\w*|lower|narrow\w*|"
                         r"shr[aiu]nk\w*|contract\w*|reduc\w*|down)\b", re.IGNORECASE)
_FORECAST_OR_CAUSE = re.compile(
    r"\b(?:will|would|expect\w*|likely|forecast\w*|outlook|guidance|going\s+forward|next\s+year|"
    r"future|anticipat\w*|predict\w*|because|due\s+to|driven\s+by|thanks\s+to|owing\s+to|"
    r"as\s+a\s+result|result\w*\s+from|on\s+the\s+back\s+of|led\s+by|reflect\w*)\b",
    re.IGNORECASE)
_JUDGEMENT = re.compile(r"\b(?:strong\w*|weak\w*|solid|robust|healthy|impressive|concerning|"
                        r"worrying|disappointing|excellent|poor\w*|stellar|favou?rabl\w*|"
                        r"unfavou?rabl\w*)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Signal:
    id: str            # e.g. "revenue_growth_up"
    side: str          # "bull" | "bear"
    dimension: str     # "growth" | "profitability" | "cash" | "balance_sheet" | "per_share"
    rule: str          # the rule in plain words, no digits
    tokens: tuple[tuple[str, str], ...]   # (key, period) of the facts cited, most important first
    template: str      # the code-built sentence, [[F:key|period]] placeholders, no typed digits
    weight: float      # ordering; larger first; ties broken by id


# ---- ledger helpers ----------------------------------------------------------------------------
def _years(ledger) -> list[int]:
    """Fiscal years with at least one FY fact or a recorded year end, newest first."""
    years = set()
    for key in ledger.keys():
        for p in ledger.periods(key):
            m = _FY_RE.match(p)
            if m:
                years.add(int(m.group(1)))
    try:
        ends = ledger.to_json().get("period_ends") or {}
    except Exception:
        ends = {}
    for period in ends:
        m = _FY_RE.match(str(period))
        if m:
            years.add(int(m.group(1)))
    return sorted(years, reverse=True)


def _period(ledger, key: str, year: int) -> str | None:
    """`FY2024` for a flow or a ratio; the fiscal year-end date for a balance (instant metric)."""
    m = metrics.METRICS.get(key)
    if m is not None and m.kind == "instant":
        return ledger.period_end(f"FY{year}")
    return f"FY{year}"


def _held(ledger, key: str, year: int) -> Fact | None:
    period = _period(ledger, key, year)
    return ledger.get(key, period) if period else None


def _fact(ledger, key: str, year: int) -> Fact | None:
    """The fact for fiscal `year`, only when it has a value."""
    f = _held(ledger, key, year)
    return f if f is not None and f.value is not None else None


def _current_year(ledger, years: list[int]) -> int | None:
    """The report's fiscal year: the newest one with reported revenue or net income."""
    for year in years:
        if _held(ledger, "revenue", year) is not None or _held(ledger, "net_income", year) is not None:
            return year
    return years[0] if years else None


def _latest(ledger, key: str, years: list[int]) -> int | None:
    """The report's fiscal year, when the metric is held for it (with or without a value). A
    metric whose newest figure is older than that (the company stopped tagging it) gives None:
    a figure from years ago never makes a point about the company today."""
    current = _current_year(ledger, years)
    if current is None or _held(ledger, key, current) is None:
        return None
    return current


def _ratio_sign(value: float, step: float = RATIO_STEP) -> int:
    if round(abs(value), 9) < step:
        return 0
    return 1 if value > 0 else -1


def _compare(cur: Fact | None, prior: Fact | None) -> int | None:
    """1 up, -1 down, 0 no change worth naming, None when it cannot be compared. A ratio moves by
    its key's step (MARGIN_STEP for margins, returns and debt to equity, else RATIO_STEP)."""
    if cur is None or prior is None or cur.value is None or prior.value is None:
        return None
    if cur.unit != prior.unit:
        return None
    diff = cur.value - prior.value
    if cur.unit == "ratio":
        return _ratio_sign(diff, _STEP.get(cur.key, RATIO_STEP))
    if diff == 0 or fmt.fact(cur) == fmt.fact(prior):
        return 0
    return 1 if diff > 0 else -1


def _t(f: Fact) -> str:
    return f"[[F:{f.key}|{f.period}]]"


def _ref(f: Fact) -> tuple[str, str]:
    return (f.key, f.period)


def _signal(sid: str, facts: tuple[Fact, ...], template: str) -> Signal:
    side, dimension, weight, rule = RULES[sid]
    return Signal(id=sid, side=side, dimension=dimension, rule=rule,
                  tokens=tuple(_ref(f) for f in facts), template=template, weight=weight)


# ---- the rules ---------------------------------------------------------------------------------
def _growth_rule(base: str, growth: str, name: str):
    def rule(ledger, years):
        year = _latest(ledger, base, years)      # the newest year of the base, never a stale one
        if year is None:
            return []
        g = _fact(ledger, growth, year)        # None when the ratios module marked it not meaningful
        cur, prior = _fact(ledger, base, year), _fact(ledger, base, year - 1)
        if g is None or cur is None or prior is None:
            return []
        if cur.value <= 0 or prior.value <= 0:   # from or to a loss: a percentage means nothing
            return []
        sign = _ratio_sign(g.value)
        if not sign:
            return []
        word = "rose" if sign > 0 else "fell"
        sid = f"{growth}_up" if sign > 0 else f"{growth}_down"
        return [_signal(sid, (cur, g, prior),
                        f"{name} {word} to {_t(cur)} in fiscal {year} from {_t(prior)} a year "
                        f"earlier, a change of {_t(g)}.")]
    return rule


def _revenue_trend(ledger, years):
    year = _latest(ledger, "revenue", years)
    if year is None:
        return []
    facts = [_fact(ledger, "revenue", year - i) for i in range(4)]       # newest first
    if any(f is None for f in facts) or len({f.unit for f in facts}) != 1:
        return []
    steps = []
    for newer, older in zip(facts, facts[1:]):
        if older.value <= 0:
            return []
        steps.append(_ratio_sign(newer.value / older.value - 1.0))
    last, first = facts[0], facts[3]
    ups, downs = steps.count(1), steps.count(-1)
    if ups == 3:
        return [_signal("revenue_trend_up", (last, first),
                        f"Revenue rose in each of the last three fiscal years, from {_t(first)} in "
                        f"fiscal {year - 3} to {_t(last)} in fiscal {year}.")]
    if downs == 3:
        return [_signal("revenue_trend_down", (last, first),
                        f"Revenue fell in each of the last three fiscal years, from {_t(first)} in "
                        f"fiscal {year - 3} to {_t(last)} in fiscal {year}.")]
    if downs == 2:
        return [_signal("revenue_trend_down", (last, first),
                        f"Revenue fell in two of the last three fiscal years and was {_t(last)} in "
                        f"fiscal {year}, against {_t(first)} in fiscal {year - 3}.")]
    return []


def _pair_rule(key: str, up_id: str, down_id: str, up_text: str, down_text: str,
               signed_text: str | None = None):
    """latest above prior -> up_id, below -> down_id. Texts use {cur}, {prior}, {year}.
    `signed_text` (no direction word) is used when either value is negative: "fell to -$1.50" or
    "narrowed to -2.0%" does not read; "was -2.0%, against 3.1% a year earlier" does."""
    def rule(ledger, years):
        year = _latest(ledger, key, years)
        if year is None:
            return []
        cur, prior = _fact(ledger, key, year), _fact(ledger, key, year - 1)
        c = _compare(cur, prior)
        if not c:
            return []
        text = up_text if c > 0 else down_text
        if signed_text and (cur.value < 0 or prior.value < 0):
            text = signed_text
        text = text.format(cur=_t(cur), prior=_t(prior), year=year)
        return [_signal(up_id if c > 0 else down_id, (cur, prior), text)]
    return rule


def _net_loss(ledger, years):
    year = _latest(ledger, "net_income", years)
    ni = _fact(ledger, "net_income", year) if year is not None else None
    if ni is None or ni.value >= 0:
        return []
    prior = _fact(ledger, "net_income", year - 1)
    if prior is not None and prior.unit == ni.unit:
        return [_signal("net_loss", (ni, prior),
                        f"The company reported a net loss in fiscal {year}, with net income of "
                        f"{_t(ni)} against {_t(prior)} a year earlier.")]
    return [_signal("net_loss", (ni,),
                    f"The company reported a net loss in fiscal {year}, with net income of {_t(ni)}.")]


def _free_cash_flow(ledger, years):
    year = _latest(ledger, "free_cash_flow", years)
    if year is None:
        return []
    cur, prior = _fact(ledger, "free_cash_flow", year), _fact(ledger, "free_cash_flow", year - 1)
    if cur is None:
        return []
    c = _compare(cur, prior)
    if cur.value < 0:
        if c is not None and c < 0:
            return [_signal("free_cash_flow_negative", (cur, prior),
                            f"Free cash flow was negative at {_t(cur)} in fiscal {year}, down from "
                            f"{_t(prior)} a year earlier.")]
        if c is not None:
            return [_signal("free_cash_flow_negative", (cur, prior),
                            f"Free cash flow was negative at {_t(cur)} in fiscal {year}, against "
                            f"{_t(prior)} a year earlier.")]
        return [_signal("free_cash_flow_negative", (cur,),
                        f"Free cash flow was negative at {_t(cur)} in fiscal {year}.")]
    if c is None or c == 0:
        return []
    if c > 0 and cur.value > 0:
        return [_signal("free_cash_flow_up", (cur, prior),
                        f"Free cash flow rose to {_t(cur)} in fiscal {year} from {_t(prior)} a "
                        f"year earlier.")]
    if c < 0:
        return [_signal("free_cash_flow_down", (cur, prior),
                        f"Free cash flow fell to {_t(cur)} in fiscal {year} from {_t(prior)} a "
                        f"year earlier.")]
    return []


def _conversion_side(value: float) -> str | None:
    """"cash_conversion_high" from CONVERSION_HIGH to CONVERSION_CAP (above the cap net income is
    too low for the ratio to mean strength), "cash_conversion_low" below CONVERSION_LOW."""
    if CONVERSION_HIGH <= value <= CONVERSION_CAP:
        return "cash_conversion_high"
    if value < CONVERSION_LOW:
        return "cash_conversion_low"
    return None


def _cash_conversion(ledger, years):
    """operating_cash_flow / net_income for the latest year (only when net income is positive).
    The computed fact `cash_conversion` is added only when a point cites it."""
    year = _latest(ledger, "operating_cash_flow", years)
    if year is None:
        return []
    ocf, ni = _fact(ledger, "operating_cash_flow", year), _fact(ledger, "net_income", year)
    if ocf is None or ni is None or ni.value <= 0 or ocf.unit != ni.unit:
        return []
    period = f"FY{year}"
    cc = ledger.get("cash_conversion", period)
    if cc is None:
        if _conversion_side(ocf.value / ni.value) is None:
            return []
        try:
            cc = ledger.add_fact(Fact(key="cash_conversion", period=period,
                                      value=ocf.value / ni.value, unit="ratio",
                                      inputs=(_ref(ocf), _ref(ni)),
                                      formula="operating_cash_flow / net_income"))
        except LedgerError:          # added by someone else in the meantime: use theirs
            cc = ledger.get("cash_conversion", period)
    if cc is None or cc.value is None:
        return []
    sid = _conversion_side(cc.value)
    if sid is None:
        return []
    return [_signal(sid, (cc, ocf, ni),
                    f"Operating cash flow was {_t(cc)} of net income in fiscal {year}, at {_t(ocf)} "
                    f"against {_t(ni)}.")]


def _cash_covers_debt(ledger, years):
    year = _latest(ledger, "cash", years)
    if year is None:
        return []
    cash, debt = _fact(ledger, "cash", year), _fact(ledger, "long_term_debt", year)
    if cash is None or debt is None or cash.unit != debt.unit or cash.value < debt.value:
        return []
    verb = "exceeded" if cash.value > debt.value else "matched"
    return [_signal("cash_covers_debt", (cash, debt),
                    f"Cash and cash equivalents of {_t(cash)} at the end of fiscal {year} {verb} "
                    f"long-term debt of {_t(debt)}.")]


def _negative_equity(ledger, years):
    year = _latest(ledger, "shareholders_equity", years)
    eq = _fact(ledger, "shareholders_equity", year) if year is not None else None
    if eq is None or eq.value >= 0:
        return []
    return [_signal("negative_equity", (eq,),
                    f"Shareholders' equity was negative at the end of fiscal {year}, at {_t(eq)}.")]


def _share_count(ledger, years):
    year = _latest(ledger, "shares_outstanding", years)
    if year is None:
        return []
    cur, prior = _fact(ledger, "shares_outstanding", year), _fact(ledger, "shares_outstanding", year - 1)
    c = _compare(cur, prior)
    if c is not None and c < 0:
        return [_signal("share_count_down", (cur, prior),
                        f"The share count fell to {_t(cur)} at the end of fiscal {year} from "
                        f"{_t(prior)} a year earlier.")]
    if c is not None and c > 0 and prior.value > 0 and cur.value > prior.value * (1.0 + SHARE_RISE):
        return [_signal("share_count_up", (cur, prior),
                        f"The share count rose to {_t(cur)} at the end of fiscal {year} from "
                        f"{_t(prior)} a year earlier.")]
    return []


_SIGNED = "{label} {verb} {{cur}} in fiscal {{year}}, against {{prior}} a year earlier."

# (rule, applies to a financial company)
_RULE_FUNCS = (
    (_growth_rule("revenue", "revenue_growth", "Revenue"), True),
    (_revenue_trend, True),
    (_growth_rule("net_income", "net_income_growth", "Net income"), True),
    (_pair_rule("operating_margin", "operating_margin_up", "operating_margin_down",
                "The operating margin widened to {cur} in fiscal {year} from {prior} a year earlier.",
                "The operating margin narrowed to {cur} in fiscal {year} from {prior} a year earlier.",
                _SIGNED.format(label="The operating margin", verb="was")), True),
    (_pair_rule("gross_margin", "gross_margin_up", "gross_margin_down",
                "The gross margin widened to {cur} in fiscal {year} from {prior} a year earlier.",
                "The gross margin narrowed to {cur} in fiscal {year} from {prior} a year earlier.",
                _SIGNED.format(label="The gross margin", verb="was")), False),
    (_pair_rule("return_on_equity", "return_on_equity_up", "return_on_equity_down",
                "Return on equity rose to {cur} in fiscal {year} from {prior} a year earlier.",
                "Return on equity fell to {cur} in fiscal {year} from {prior} a year earlier.",
                _SIGNED.format(label="Return on equity", verb="was")), True),
    (_net_loss, True),
    (_free_cash_flow, False),
    (_cash_conversion, False),
    (_pair_rule("debt_to_equity", "debt_to_equity_up", "debt_to_equity_down",
                "Long-term debt to equity rose to {cur} at the end of fiscal {year} from {prior} a "
                "year earlier.",
                "Long-term debt to equity fell to {cur} at the end of fiscal {year} from {prior} a "
                "year earlier."), False),
    (_cash_covers_debt, False),
    (_negative_equity, True),
    (_pair_rule("eps_diluted", "eps_diluted_up", "eps_diluted_down",
                "Diluted earnings per share rose to {cur} in fiscal {year} from {prior} a year earlier.",
                "Diluted earnings per share fell to {cur} in fiscal {year} from {prior} a year earlier.",
                _SIGNED.format(label="Diluted earnings per share", verb="were")), True),
    (_share_count, True),
    (_pair_rule("dividends_per_share", "dividends_per_share_up", "dividends_per_share_down",
                "Dividends per share rose to {cur} in fiscal {year} from {prior} a year earlier.",
                "Dividends per share fell to {cur} in fiscal {year} from {prior} a year earlier."), True),
)


def _ordered(found) -> list[Signal]:
    return sorted(found, key=lambda s: (-s.weight, s.id))


def signals(ledger, *, financial: bool = False) -> list[Signal]:
    """Every rule that fires on the ledger, largest weight first (ties by id). May add the computed
    fact `cash_conversion` for the latest year (never one already held). `financial=True` (a bank,
    an insurer: SIC 6000 to 6799) skips the rules in NOT_FOR_FINANCIALS. Never raises."""
    found: dict[str, Signal] = {}
    try:
        years = _years(ledger)
    except Exception:
        return []
    for rule, for_financial in _RULE_FUNCS:
        if financial and not for_financial:
            continue
        try:
            for s in rule(ledger, years):
                if financial and s.id in NOT_FOR_FINANCIALS:
                    continue
                found.setdefault(s.id, s)
        except Exception:
            continue
    return _ordered(found.values())


# ---- thesis lines (neutral, built in code) -----------------------------------------------------
def thesis_lines(ledger, *, financial: bool = False) -> list[tuple[str, tuple[tuple[str, str], ...], str]]:
    """(dimension, tokens, code sentence) for each thesis dimension whose facts are held. They
    describe; they do not take a side. The growth line takes the longer view (revenue against
    three fiscal years earlier) so it does not repeat the first bull or bear point. For a
    financial company there is no cash line and the balance sheet is total assets and
    shareholders' equity. Read-only."""
    years = _years(ledger)
    out = []

    year = _latest(ledger, "revenue", years)
    rev = _fact(ledger, "revenue", year) if year is not None else None
    if rev is not None:
        g = _fact(ledger, "revenue_growth", year)
        earlier = _fact(ledger, "revenue", year - 3)
        if earlier is not None and earlier.unit == rev.unit:
            out.append(("growth", (_ref(rev), _ref(earlier)),
                        f"Revenue was {_t(rev)} in fiscal {year}, against {_t(earlier)} in fiscal "
                        f"{year - 3}."))
        elif g is not None:
            out.append(("growth", (_ref(rev), _ref(g)),
                        f"Revenue was {_t(rev)} in fiscal {year}, a change of {_t(g)} from the year "
                        f"before."))
        else:
            out.append(("growth", (_ref(rev),), f"Revenue was {_t(rev)} in fiscal {year}."))

    # the year's two margins side by side, not the change from the year before (that is a point)
    year = _current_year(ledger, years)
    om = _fact(ledger, "operating_margin", year) if year is not None else None
    nm = _fact(ledger, "net_margin", year) if year is not None else None
    if om is not None and nm is not None:
        out.append(("profitability", (_ref(om), _ref(nm)),
                    f"The operating margin was {_t(om)} in fiscal {year} and the net margin "
                    f"{_t(nm)}."))
    elif om is not None:
        out.append(("profitability", (_ref(om),),
                    f"The operating margin was {_t(om)} in fiscal {year}."))
    elif nm is not None:
        out.append(("profitability", (_ref(nm),),
                    f"The net margin was {_t(nm)} in fiscal {year}."))

    if financial:
        year = _current_year(ledger, years)
        assets = _fact(ledger, "total_assets", year) if year is not None else None
        equity = _fact(ledger, "shareholders_equity", year) if year is not None else None
        if assets is not None and equity is not None:
            out.append(("balance_sheet", (_ref(assets), _ref(equity)),
                        f"At the end of fiscal {year} total assets were {_t(assets)} and "
                        f"shareholders' equity was {_t(equity)}."))
        elif assets is not None:
            out.append(("balance_sheet", (_ref(assets),),
                        f"At the end of fiscal {year} total assets were {_t(assets)}."))
        elif equity is not None:
            out.append(("balance_sheet", (_ref(equity),),
                        f"At the end of fiscal {year} shareholders' equity was {_t(equity)}."))
        return out

    year = _latest(ledger, "operating_cash_flow", years)
    ocf = _fact(ledger, "operating_cash_flow", year) if year is not None else None
    if ocf is not None:
        fcf = _fact(ledger, "free_cash_flow", year)
        if fcf is not None:
            out.append(("cash", (_ref(fcf), _ref(ocf)),
                        f"Operating cash flow was {_t(ocf)} in fiscal {year}, and free cash flow "
                        f"after capital expenditure was {_t(fcf)}."))
        else:
            out.append(("cash", (_ref(ocf),),
                        f"Operating cash flow was {_t(ocf)} in fiscal {year}."))

    year = _latest(ledger, "cash", years)
    cash = _fact(ledger, "cash", year) if year is not None else None
    if cash is not None:
        debt = _fact(ledger, "long_term_debt", year)
        de = _fact(ledger, "debt_to_equity", year)
        head = f"At the end of fiscal {year} the company held cash and cash equivalents of {_t(cash)}"
        if debt is not None and de is not None:
            out.append(("balance_sheet", (_ref(cash), _ref(debt), _ref(de)),
                        f"{head} against long-term debt of {_t(debt)}, a long-term debt to equity "
                        f"ratio of {_t(de)}."))
        elif debt is not None:
            out.append(("balance_sheet", (_ref(cash), _ref(debt)),
                        f"{head} against long-term debt of {_t(debt)}."))
        else:
            out.append(("balance_sheet", (_ref(cash),), f"{head}."))
    return out


# ---- the model's wording -----------------------------------------------------------------------
def _direction(ledger, key: str, period: str, years: list[int]) -> str:
    """up / down / flat / none versus the year before, for the prompt (never a value)."""
    if key.endswith("_growth") or key == "cash_conversion":
        return "none"           # a growth rate is itself the change from the year before
    cur = ledger.get(key, period)
    m = _FY_RE.match(period)
    year = int(m.group(1)) if m else None
    if year is None:
        for y in years:
            if ledger.period_end(f"FY{y}") == period:
                year = y
                break
    if cur is None or year is None:
        return "none"
    c = _compare(cur, _fact(ledger, key, year - 1))
    return {1: "up", -1: "down", 0: "flat"}.get(c, "none")


def _token_lines(ledger, tokens, years: list[int], *, directions: bool = True) -> list[str]:
    lines = []
    for key, period in tokens:
        label = _LABELS.get(key) or metrics.label(key)
        direction = _direction(ledger, key, period, years) if directions else "none"
        lines.append(f"  [[F:{key}|{period}]] | {label} | {fmt.period_label(period)} | {direction}")
    return lines


def line_direction(ledger, tokens) -> str | None:
    """The direction a thesis line may state: its first token against its second when both are the
    same metric ("up", "down" or "flat"), else None (no direction word at all)."""
    if len(tokens) < 2 or tokens[0][0] != tokens[1][0]:
        return None
    c = _compare(ledger.get(*tokens[0]), ledger.get(*tokens[1]))
    return {1: "up", -1: "down", 0: "flat"}.get(c)


_LINE_COMPARISON = {"up": "the first token is higher than the second",
                    "down": "the first token is lower than the second",
                    "flat": "the first token is about the same as the second",
                    None: "no comparison: use no direction word"}


def _system_prompt() -> str:
    return (
        "You word the investment thesis and the bull and bear points of a company report built "
        "from SEC filings. Code has already chosen every point and its side; you only write the "
        "sentence. Rules:\n"
        "- One sentence per item, in plain analyst English. No heading, no bullet mark.\n"
        "- Every figure must be one of that item's tokens, copied exactly, for example "
        "[[F:revenue|FY2024]]. Use only the tokens listed under the item, and always use its "
        "first token.\n"
        "- Never type a digit yourself: no amounts, no percentages, no counts in figures. You may "
        "name a fiscal year as its period label does (fiscal 2024).\n"
        "- Describe direction only as the item's rule and the token directions state. A growth "
        "token is itself the change from the year before.\n"
        "- No advice, no rating, no view on the share price or on valuation, no forecast, and no "
        "cause or reason that the figures themselves do not show.\n"
        "- Thesis lines describe the figures and do not take a side. Use a direction word in a "
        "thesis line only as its comparison states, and none when it says no comparison.\n"
        'Answer with strict JSON only: {"thesis": {"<dimension>": "one sentence"}, '
        '"bullets": {"<signal id>": "one sentence"}}. Leave out an item you cannot write.'
    )


def prompt_for(ledger, company: dict, chosen: list[Signal], lines) -> list[dict]:
    """System + user messages: tokens, labels, periods and directions. NO values."""
    company = company or {}
    years = _years(ledger)
    parts = [f"Company: {company.get('name') or ''} ({company.get('ticker') or ''})", "",
             "Thesis lines (dimension | title | comparison | tokens):"]
    for dimension, tokens, _template in lines:
        comparison = _LINE_COMPARISON[line_direction(ledger, tokens)]
        parts.append(f"{dimension} | {THESIS_TITLES[dimension]} | {comparison} | tokens:")
        parts += _token_lines(ledger, tokens, years, directions=False)
    if not lines:
        parts.append("(none)")
    parts += ["", "Signals (id | side | rule | tokens):"]
    for s in chosen:
        parts.append(f"{s.id} | {s.side} | {s.rule} | tokens:")
        parts += _token_lines(ledger, s.tokens, years)
    if not chosen:
        parts.append("(none)")
    return [{"role": "system", "content": _system_prompt()},
            {"role": "user", "content": "\n".join(parts)}]


def _resolve_ask(ask):
    if ask is not None:
        return ask
    try:
        from backend import model as _model
        fn = getattr(_model, "ask", None)
        if callable(fn):
            return fn
    except Exception:
        pass
    import llm
    return llm.call_llm


_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)```", re.DOTALL)


def parse_reply(text) -> dict | None:
    """The JSON object in a model reply: the whole reply, a fenced block, or the first object that
    parses inside prose. None when there is none."""
    if not isinstance(text, str) or not text.strip():
        return None
    candidates = [text] + [m.group(1) for m in _FENCE.finditer(text)]
    for candidate in candidates:
        try:
            value = json.loads(candidate.strip())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for i, ch in enumerate(candidate):
            if ch != "{":
                continue
            try:
                value, _end = decoder.raw_decode(candidate, i)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return None


_PAIR = re.compile(r'"([A-Za-z0-9_]+)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def salvage(text, dims, ids) -> dict:
    """The sentences of a reply whose JSON does not parse as asked (cut off at the length limit,
    a missing closing brace): every complete `"key": "sentence"` pair whose key is one of the
    dimensions or signal ids asked for. A pair cut off mid-sentence has no closing quote and is
    not taken. Always returns {"thesis": {...}, "bullets": {...}}."""
    out = {"thesis": {}, "bullets": {}}
    if not isinstance(text, str):
        return out
    for key, value in _PAIR.findall(text):
        try:
            sentence = json.loads(f'"{value}"')
        except ValueError:
            continue
        if key in ids and key not in out["bullets"]:
            out["bullets"][key] = sentence
        elif key in dims and key not in out["thesis"]:
            out["thesis"][key] = sentence
    return out


def _ask_model(ledger, company, chosen, lines, session_id, ask) -> dict:
    """{"thesis": {dimension: text}, "bullets": {id: text}}; empty parts on any failure."""
    wording = {"thesis": {}, "bullets": {}}
    try:
        fn = _resolve_ask(ask)
        # the default door traces this call under its own agent name (an injected `ask` is left alone)
        named = {"agent_id": "europa-bull-bear"} if ask is None else {}
        reply = fn(prompt_for(ledger, company, chosen, lines), session_id=session_id,
                   temperature=0.2, max_tokens=MAX_TOKENS, **named)
    except Exception:
        return wording
    dims = {d for d, _t, _x in lines}
    ids = {s.id for s in chosen}
    data = parse_reply(reply)
    if not isinstance(data, dict) or not ("thesis" in data or "bullets" in data):
        # the object was cut off before it closed (or only an inner part parsed): take every
        # complete "key": "sentence" pair that names one of the items asked for
        data = salvage(reply, dims, ids)
    thesis, bullets = data.get("thesis"), data.get("bullets")
    if isinstance(thesis, dict):
        wording["thesis"] = {k: v for k, v in thesis.items() if k in dims and isinstance(v, str)}
    if isinstance(bullets, dict):
        wording["bullets"] = {k: v for k, v in bullets.items() if k in ids and isinstance(v, str)}
    return wording


# ---- checking and choosing the sentence --------------------------------------------------------
def _plain(text: str) -> str:
    """A removed sentence as a reader may see it: no placeholder syntax, whole or cut off."""
    readable = getattr(audit, "readable", None)
    if readable is not None:
        return readable(text).strip()
    return audit.PLACEHOLDER.sub("[figure]", text).strip()


def _clean(text: str) -> str:
    text = " ".join(text.replace("**", "").split())
    text = re.sub(r"^(?:[-*•]\s+)", "", text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def _acceptable(text: str, tokens, signal_id: str | None, direction: str | None = None) -> bool:
    """This module's own checks on the model's sentence (the audit runs after them). A thesis line
    (`signal_id` None) may use a direction word only as `line_direction` allows."""
    if not text or len(text) > MAX_SENTENCE_CHARS or len(audit.sentences(text)) != 1:
        return False
    used = audit.find_placeholders(text)
    allowed = {tuple(t) for t in tokens}
    if tokens and tuple(tokens[0]) not in used:
        return False
    if any(u not in allowed for u in used):
        return False
    words = audit.PLACEHOLDER.sub(" ", text)
    if _FORECAST_OR_CAUSE.search(words):
        return False
    if signal_id is None:
        if _JUDGEMENT.search(words):
            return False
        if direction != "up" and _UP_WORDS.search(words):
            return False
        if direction != "down" and _DOWN_WORDS.search(words):
            return False
        return True
    if signal_id.endswith("_up") and _DOWN_WORDS.search(words):
        return False
    if signal_id.endswith("_down") and _UP_WORDS.search(words):
        return False
    return True


def _unwrap(html: str) -> str:
    html = (html or "").strip()
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        return html[3:-4].strip()
    return ""


_DIRECTION_WORDS = re.compile(r"\b(?:widen\w*|narrow\w*|rose|rise[sn]?|rising|fell|fall(?:s|en|ing)?|grew|grow\w*|"
                              r"increas\w*|decreas\w*|declin\w*|improv\w*|worsen\w*|expand\w*|shr[aiu]nk\w*|"
                              r"higher|lower|up|down|climb\w*|dropp?\w*)\b", re.I)


def _negative_with_direction(ledger, text: str, tokens) -> bool:
    """A direction word in a sentence that cites a negative figure."""
    if not _DIRECTION_WORDS.search(audit.PLACEHOLDER.sub(" ", text)):
        return False
    for key, period in tokens or ():
        fact = ledger.get(key, period)
        if fact is not None and fact.value is not None and fact.value < 0:
            return True
    return False


def _word(ledger, model_text, template: str, tokens, signal_id, withheld: list,
          direction: str | None = None) -> tuple[str, str] | None:
    """(inline html, "model" | "code"), or None when neither sentence survives the checks."""
    if isinstance(model_text, str) and model_text.strip():
        text = _clean(model_text)
        if _negative_with_direction(ledger, text, tokens):
            # "the margin widened to -66.5% from -94.3%" reads as worse when the loss narrowed:
            # around a negative figure only the code sentence, which takes no direction, is used
            withheld.append(_plain(text))
        elif _acceptable(text, tokens, signal_id, direction):
            html, removed = audit.apply(text, ledger)
            withheld.extend(removed)
            inner = _unwrap(html)
            if inner and not removed:
                return inner, "model"
        elif text:
            withheld.append(_plain(text))
    html, removed = audit.apply(template, ledger)
    withheld.extend(removed)
    inner = _unwrap(html)
    if inner and not removed:
        return inner, "code"
    return None


def _pick(side: list[Signal]) -> list[Signal]:
    """The MAX_PER_SIDE strongest, at most MAX_PER_DIMENSION per dimension unless places are left."""
    picked, rest, per_dim = [], [], {}
    for s in side:
        if len(picked) >= MAX_PER_SIDE:
            break
        if per_dim.get(s.dimension, 0) >= MAX_PER_DIMENSION:
            rest.append(s)
            continue
        picked.append(s)
        per_dim[s.dimension] = per_dim.get(s.dimension, 0) + 1
    for s in rest:
        if len(picked) >= MAX_PER_SIDE:
            break
        picked.append(s)
    return _ordered(picked)


def _empty(n_signals: int = 0) -> dict:
    return {"thesis": [], "bull": [], "bear": [], "withheld": [], "method": "code",
            "counts": {"signals": n_signals, "bull": 0, "bear": 0}}


def _build(ledger, company, session_id, found, ask, use_model: bool, financial: bool = False) -> dict:
    unique: dict[str, Signal] = {}
    for s in found:
        if isinstance(s, Signal) and s.side in ("bull", "bear"):
            unique.setdefault(s.id, s)
    ordered = _ordered(unique.values())
    n_signals = len(ordered)          # anything in `found` that is not a Signal is ignored
    bull = _pick([s for s in ordered if s.side == "bull"])
    bear = _pick([s for s in ordered if s.side == "bear"])
    lines = thesis_lines(ledger, financial=financial)
    wording = {"thesis": {}, "bullets": {}}
    if use_model and (bull or bear or lines):
        wording = _ask_model(ledger, company, bull + bear, lines, session_id, ask)

    withheld: list[str] = []
    out = _empty(n_signals)
    for dimension, tokens, template in lines:
        done = _word(ledger, wording["thesis"].get(dimension), template, tokens, None, withheld,
                     line_direction(ledger, tokens))
        if done:
            out["thesis"].append({"title": THESIS_TITLES[dimension], "html": done[0],
                                  "method": done[1]})
    for side, chosen in (("bull", bull), ("bear", bear)):
        for s in chosen:
            done = _word(ledger, wording["bullets"].get(s.id), s.template, s.tokens, s.id, withheld)
            if done:
                out[side].append({"html": done[0], "method": done[1], "signal": s.id,
                                  "rule": s.rule})
    out["withheld"] = withheld
    items = out["thesis"] + out["bull"] + out["bear"]
    out["method"] = "model" if any(i["method"] == "model" for i in items) else "code"
    out["counts"] = {"signals": n_signals, "bull": len(out["bull"]), "bear": len(out["bear"])}
    return out


def build(ledger, company: dict, *, session_id: str, found: list[Signal] | None = None,
          ask=None, financial: bool = False) -> dict:
    """The thesis block and the bull / bear lists, checked, as inline HTML. ONE model call
    (temperature 0.2, max_tokens MAX_TOKENS) words them; anything the model did not write, or the
    checks removed, uses the code sentence. `found` is the output of `signals()` (taken on the main
    thread); None gives the empty result. `financial` must match the `signals()` call: it picks
    the thesis lines for a bank or an insurer. Never raises and never changes the ledger."""
    if found is None:
        return _empty()
    try:
        found = list(found)
    except Exception:
        return _empty()
    try:
        return _build(ledger, company or {}, session_id, found, ask, use_model=True,
                      financial=financial)
    except Exception:
        pass
    try:
        return _build(ledger, company or {}, session_id, found, ask, use_model=False,
                      financial=financial)
    except Exception:
        return _empty()
