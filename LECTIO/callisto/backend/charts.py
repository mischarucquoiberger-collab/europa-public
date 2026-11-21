"""Charts for /api/ask. Chart data comes straight from the source (Massive daily closes, Apple's SEC facts),
never from a model, so nothing here passes through the writer or needs the number gate. Ported from the local
chat (Jayden, 2026-11-21). A chart is only built when the question asks for one."""
from __future__ import annotations

import re

from backend import facts, massive

_CHART_RX = re.compile(r"\b(chart|charts|graph|graphs|plot|visuali[sz]e|visual|diagram|trend ?line)\b", re.I)
_METRICS = [  # (words in the question, fact key stem, title)
    (r"gross margin %|gross margin percent|margin percent|gross margin", "gross_margin_pct", "Gross margin (% of sales)"),
    (r"gross profit", "gross_margin", "Gross profit"),
    (r"revenue|sales", "revenue", "Net sales (revenue)"),
    (r"net income|profit|earnings(?! per)", "net_income", "Net income"),
    (r"operating income", "operating_income", "Operating income"),
    (r"\beps\b|earnings per share|per share", "eps_diluted", "Diluted EPS"),
    (r"r&d|research", "rnd", "Research and development"),
    (r"cash", "cash", "Cash and cash equivalents"),
    (r"buyback|repurchase", "buybacks", "Share repurchases"),
]


def _period(q: str):
    """Window rule = the backend's return rule (backend/specialists.py), so the chart's % matches the answer's %:
    week/month/3 months = 5/21/63 trading days back; year = close nearest one year back; YTD = last close of prior year."""
    q = q.lower()
    m = re.search(r"(\d+)\s*(day|week|month|year)s?", q)
    if m:
        n, u = int(m.group(1)), m.group(2)
        label = f"{n} {u}{'s' if n > 1 else ''}"
        if u == "week":
            return ("bars", 5 * n), label
        if u == "month" and n <= 12:
            return ("bars", 21 * n), label
        return ("cal", n * {"day": 1, "month": 30, "year": 365}[u]), label
    for words, rule, label in [(("ytd", "year to date", "this year"), ("ytd", 0), "year to date"),
                               (("week",), ("bars", 5), "1 week"), (("quarter",), ("bars", 63), "3 months"),
                               (("month",), ("bars", 21), "1 month"),
                               (("all time", "max", "five year"), ("cal", 365 * 5), "5 years")]:
        if any(w in q for w in words):
            return rule, label
    return ("cal", 365), "1 year"


def make_charts(ticker: str, q: str, price_only: bool = False) -> list:
    if not price_only and not _CHART_RX.search(q):
        return []
    charts = []
    if ticker in facts.FACTS and not price_only:
        F = facts.FACTS[ticker]
        for rx, stem, title in _METRICS:
            if re.search(rx, q, re.I) and f"{stem}_fy2025" in F and f"{stem}_fy2026" in F:
                a, b = F[f"{stem}_fy2025"], F[f"{stem}_fy2026"]
                charts.append({"type": "bar", "title": f"{facts.COMPANY.get(ticker, ticker)} {title}",
                               "unit": a["kind"], "points": [{"x": "Fiscal 2025", "y": a["value"]},
                                                             {"x": "Fiscal 2026", "y": b["value"]}],
                               "source": a["source"].replace("FY2025", "FY2025 and FY2026") + ", checked facts"})
        if charts:
            return charts
    if not massive.available():
        return [{"type": "none", "title": "Price chart", "note": "Market data is not connected."}]
    from datetime import date, timedelta
    end = massive.today_et()
    (kind, n), label = _period(q)
    if kind == "ytd":
        start = date(end.year - 1, 12, 15)
    elif kind == "bars":
        start = end - timedelta(days=int(n * 1.6) + 20)
    else:
        start = end - timedelta(days=n + 20)
    try:
        bars = massive.daily_bars(ticker, start, end)
    except Exception:
        return [{"type": "none", "title": f"{ticker} share price", "note": "Massive did not return price history just now."}]
    if not bars:
        return [{"type": "none", "title": f"{ticker} share price", "note": "Massive has no price history for this ticker."}]
    last_d = date.fromisoformat(bars[-1]["date"])
    if kind == "ytd":
        prev = [i for i, b in enumerate(bars) if date.fromisoformat(b["date"]).year < last_d.year]
        i0 = prev[-1] if prev else 0
    elif kind == "bars":
        i0 = max(0, len(bars) - 1 - n)
    else:
        cut = (last_d - timedelta(days=n)).isoformat()
        older = [i for i, b in enumerate(bars) if b["date"] <= cut]
        i0 = older[-1] if older else 0
    bars = bars[i0:]
    return [{"type": "line", "title": f"{ticker} closing price, {label}", "unit": "usd_price",
             "points": [{"x": b["date"], "y": b["c"]} for b in bars],
             "source": f"Massive end-of-day closes, {bars[0]['date']} to {bars[-1]['date']}"}]


_STRIP_RX = re.compile(r"\b(can you |please )?(show|make|draw|give|plot|create|display)?( me)?\s*(a |an |the )?"
                       r"(chart|charts|graph|graphs|plot|visuali[sz]e|visual|diagram|trend ?line)( of| for| showing)?\b",
                       re.I)


def wanted(q: str) -> bool:
    return bool(_CHART_RX.search(q or ""))


def strip_chart_words(q: str) -> str:
    """The question the desk sees: the same question without "chart of" (the chart is drawn by code)."""
    if not wanted(q):
        return q
    dq = re.sub(r"\s+", " ", _STRIP_RX.sub(" ", q)).strip(" ?.,") or q
    return dq[0].upper() + dq[1:] + ("?" if q.rstrip().endswith("?") else "")


def charts_for(ticker: str, q: str) -> list:
    """Never raises: a chart failure must not break the answer."""
    try:
        return make_charts(ticker, q)
    except Exception:
        return [{"type": "none", "title": "Chart", "note": "The chart could not be drawn."}]


# Questions about how the share price moved get a price chart even when nobody typed "chart".
_AUTO_RX = re.compile(r"\bhow (?:has|have|is|are|did)\b[^?]*\b(?:stock|shares?|price|done|doing|perform\w*)\b|"
                      r"\bwhat(?:'s| is| has)? (?:happen\w*|going on)\b|\bperformance\b|\b(?:bear|bull)(?:ish)? case\b|"
                      r"\bwhy\b[^?]*\b(?:down|up|drop\w*|fall\w*|fell|ris\w+|rose|jump\w*|crash\w*|tank\w*|mov\w+)\b|"
                      r"\bhow\b[^?]*\b(?:perform\w*|done|doing|moved?|trad\w+)\b|\b(?:this|last|past) (?:week|month|year|quarter)\b|"
                      r"\b52[- ]week\b|\bover(?:valued|priced)\b|\bstock price\b|\bshare price\b", re.I)
_SHORT_RX = re.compile(r"\b(?:yesterday|today|this week|friday|monday|tuesday|wednesday|thursday)\b", re.I)


def auto_wanted(q: str) -> bool:
    return bool(_AUTO_RX.search(q or "")) and not wanted(q)


def auto_charts(ticker: str, q: str) -> list:
    """A price line for a price-move question. One-day questions get a one-month window for context. Returns []
    rather than a "none" note when there is no data: nobody asked for this chart."""
    try:
        qq = q if re.search(r"\d+\s*(?:day|week|month|year)|ytd|year to date|this year|quarter|month", q, re.I) else (
            q + " 1 month" if _SHORT_RX.search(q) else q)
        out = make_charts(ticker, qq, price_only=True)
        return [c for c in out if c.get("type") == "line" and len(c.get("points") or []) >= 2]
    except Exception:
        return []
