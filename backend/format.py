"""The ONE place a fact becomes text. Nothing else in the backend may turn a number into words:
the report and the chat call `fact()` for plain text and `cited()` for the linked HTML form, so
every figure a user sees went through the same units, rounding and "not available" rule.
"""
from __future__ import annotations

import html
import math
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from backend.ledger import Fact, Ledger, LedgerError

NOT_MEANINGFUL = "n/m"            # shown for a ratio of 1,000% or more in size
NOT_MEANINGFUL_RATIO = 10.0
NOT_AVAILABLE = "Not available in the sources"

_SCALES = ((1e12, "trillion"), (1e9, "billion"), (1e6, "million"))
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PER_SHARE_RE = re.compile(r"^([A-Z]{3})/share$")
_FY_RE = re.compile(r"^FY(\d{4})$")
_Q_RE = re.compile(r"^Q([1-4])-(\d{4})$")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _half_up(x: float, places: int) -> Decimal:
    """Round the way a reader expects (31.25 -> 31.3), not Python's half-to-even (31.2)."""
    return Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _scaled(magnitude: float) -> str:
    """A non-negative amount in words: "391.0 billion", "4.2 million", "950", "12,345".
    The largest scale the value reaches is used (950,000 stays "950,000", never "1.0 million");
    if rounding then reads 1000.0, the next scale up is used (999.96 billion -> "1.0 trillion")."""
    for i, (size, word) in enumerate(_SCALES):
        if magnitude >= size:
            shown = _half_up(magnitude / size, 1)
            if shown >= 1000 and i > 0:
                size, word = _SCALES[i - 1]
                shown = _half_up(magnitude / size, 1)
            return f"{shown:.1f} {word}"
    return f"{_half_up(magnitude, 0):,.0f}"


def _money(value: float, currency: str) -> str:
    body = _scaled(abs(value))
    sign = "-" if value < 0 and body != "0" else ""
    return f"{sign}${body}" if currency == "USD" else f"{sign}{currency} {body}"


def _per_share(value: float, currency: str) -> str:
    body = f"{_half_up(abs(value), 2):,.2f}"
    sign = "-" if value < 0 and body != "0.00" else ""
    return f"{sign}${body}" if currency == "USD" else f"{sign}{currency} {body}"


def _percent(value: float, signed: bool) -> str:
    shown = f"{_half_up(abs(value) * 100, 1):.1f}"
    if shown == "0.0":
        return "0.0%"
    if value < 0:
        return f"-{shown}%"
    return f"+{shown}%" if signed else f"{shown}%"


def fact(f: Fact) -> str:
    """A fact's value as plain text, by unit: USD `$391.0 billion` / `-$1.2 billion` / `$950`;
    another currency `EUR 12.3 billion`; USD/share `$6.11`; shares `15.1 billion shares`; ratio
    `25.3%`, with a sign for keys ending in `_growth` (`+2.0%`); x (a multiple) `24.3x`; years
    `2.0 years`. No value: the not-available line."""
    value = f.value
    if value is None or isinstance(value, bool) or not math.isfinite(float(value)):
        return NOT_AVAILABLE
    value = float(value)
    unit = f.unit
    if unit == "ratio":
        if abs(value) >= NOT_MEANINGFUL_RATIO:
            return NOT_MEANINGFUL          # e.g. a margin on almost no revenue: -8,029%
        return _percent(value, signed=f.key.endswith("_growth"))
    if unit == "x":
        body = f"{_half_up(abs(value), 1):,.1f}"
        sign = "-" if value < 0 and body != "0.0" else ""
        return f"{sign}{body}x"
    if unit == "years":
        body = f"{_half_up(abs(value), 1):,.1f}"
        sign = "-" if value < 0 and body != "0.0" else ""
        return f"{sign}{body} years"
    if _CURRENCY_RE.match(unit):
        return _money(value, unit)
    m = _PER_SHARE_RE.match(unit)
    if m:
        return _per_share(value, m.group(1))
    if unit == "shares":
        sign = "-" if value < 0 else ""
        return f"{sign}{_scaled(abs(value))} shares"
    return f"{_half_up(value, 2):,.2f} {unit}"


def period_label(period: str) -> str:
    """`FY2024` -> `fiscal 2024`, `Q3-2024` -> `Q3 2024`, `2024-09-28` -> `as of 28 Sep 2024`;
    anything else unchanged."""
    m = _FY_RE.match(period or "")
    if m:
        return f"fiscal {m.group(1)}"
    m = _Q_RE.match(period or "")
    if m:
        return f"Q{m.group(1)} {m.group(2)}"
    try:
        d = date.fromisoformat(period)
    except (TypeError, ValueError):
        return period
    return f"as of {d.day} {_MONTHS[d.month - 1]} {d.year}"


def cited(f: Fact, ledger: Ledger) -> str:
    """The value as HTML: a reported fact links to its (first) source, a computed fact to its
    Calculations entry, and no value gives the plain not-available text. The fact must be the
    one the ledger holds (same value, same sources), so a number that is not in the ledger can
    never be dressed up with a real link. All text and attributes are HTML-escaped."""
    if f.value is None:
        return html.escape(NOT_AVAILABLE)
    held = ledger.get(f.key, f.period)
    if held is None or held != f:
        raise LedgerError(f"{f.key} {f.period} is not the fact the ledger holds")
    text = html.escape(fact(f))
    if f.is_computed:
        calc = html.escape(ledger.calc_id(f), quote=True)
        return f'<a class="calc" href="#{calc}" data-calc="{calc}">{text}</a>'
    sources = ledger.cite(f)
    if not sources:
        raise LedgerError(f"{f.key} {f.period} has no source")
    first = sources[0]
    return (f'<a class="src" href="{html.escape(first.url, quote=True)}" '
            f'data-source="{html.escape(first.id, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer">{text}</a>')
