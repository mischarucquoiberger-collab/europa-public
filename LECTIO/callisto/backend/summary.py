"""Code-built parts of the short advice answer: stat bullets and a news-mood block.

Bullets are source facts printed by code (SEC facts for Apple, the Massive market pack for any ticker); no model
writes or rounds them. The news block shows publisher headlines word for word with the feed's own sentiment tag;
it is labelled as not checked. Every function returns [] instead of raising."""
from __future__ import annotations

import re
from datetime import date

from backend import facts, massive, specialists as sp

NEWS_HEAD = "In the news (headlines from Massive, not checked by Callisto):"
# Stock-pitch titles are not news about the company: dropped from the block.
_PITCH_RX = re.compile(r"\b(?:stocks? to buy|should you buy|better buy|millionaire|top \d+|\d+ (?:stocks|reasons)|"
                       r"predictions?|could soar|buy now|vs\.?)(?!\w)", re.I)
_MAX_WORDS = 16
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _chg(pct) -> str:
    return f"{'up' if pct >= 0 else 'down'} {sp._q(abs(pct), '0.1')}%"


def _day(iso) -> str:
    """'2026-11-20' -> 'Fri, Nov 20'. Falls back to the text given."""
    try:
        d = date.fromisoformat(str(iso))
        return f"{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday()]}, {_MON[d.month - 1]} {d.day}"
    except ValueError:
        return str(iso)


def _moved(display: str) -> str:
    """'+28.7%' -> 'up 28.7%', '-14.0%' -> 'down 14.0%'."""
    d = str(display).strip()
    return ("down " + d[1:]) if d.startswith("-") else ("up " + d.lstrip("+"))


def market_bullets(ticker: str, full: bool = True) -> list[str]:
    try:
        pack = sp.market({"ticker": ticker})
        if not isinstance(pack, dict) or pack.get("status") != "ok":
            return []
        f, out = pack.get("facts") or {}, []
        d = lambda k: (f.get(k) or {}).get("display")
        if d("px_close_last"):
            line = f"Stock: {d('px_close_last')} at the last close ({_day(pack.get('as_of'))})"
            if not full and d("ret_1y_pct"):
                line += f", {_moved(d('ret_1y_pct'))} over the past year"
            out.append(line)
        if not full:
            return out
        moves = [f"{_moved(d(k))} {w}" for k, w in [("ret_1d_pct", "on the day"), ("ret_1m_pct", "over one month"),
                                                    ("ret_1y_pct", "over the past year")] if d(k)]
        if moves:
            out.append("Moves: " + ", ".join(moves))
        if d("px_52w_low") and d("px_52w_high"):
            line = f"52-week range: {d('px_52w_low')} to {d('px_52w_high')}"
            if d("gap_52w_high_pct"):
                line += f" (now {d('gap_52w_high_pct')} below the high)"
            out.append(line)
        if d("market_cap"):
            out.append(f"Market value: {d('market_cap')}")
        if d("div_yield_pct"):
            out.append(f"Dividend yield: {d('div_yield_pct')}")
        return out[:5]
    except Exception:
        return []


def apple_bullets() -> list[str]:
    try:
        F = facts.FACTS["AAPL"]
        v = lambda k: F[k]["value"]
        out = [f"Sales: {sp.fmt_usd_big(v('revenue_fy2026'))}, {_chg(v('revenue_change_pct'))} from fiscal 2025",
               f"Profit: {sp.fmt_usd_big(v('net_income_fy2026'))}, {_chg(v('net_income_change_pct'))}",
               f"Profit per share (EPS): {sp.fmt_price(v('eps_diluted_fy2026'))}, {_chg(v('eps_diluted_change_pct'))}",
               f"Gross margin: {sp._q(v('gross_margin_pct_fy2026'), '0.1')}%, "
               f"{'up' if v('gross_margin_pct_change_pts') >= 0 else 'down'} from {sp._q(v('gross_margin_pct_fy2025'), '0.1')}%",
               f"Buybacks: {sp.fmt_usd_big(v('buybacks_fy2026'))}, {_chg(v('buybacks_change_pct'))}"]
        return (out + market_bullets("AAPL", full=False))[:6]
    except Exception:
        return []


def news_lines(ticker: str, name: str | None = None, limit: int = 2) -> list[str]:
    """Up to `limit` headlines the feed tags positive or negative for this ticker. A title is kept only when it names
    the company (first word of the name, at least 3 letters) or the ticker as a whole word; stock-pitch titles are
    dropped. Short titles (at most 16 words) are shown word for word and preferred; a longer one is cut at 16 words
    and ends with an ellipsis only when no short one exists."""
    try:
        first = (name or "").split(" ")[0].strip(",.'") if name else ""
        alts = [re.escape(ticker)] + ([re.escape(first)] if len(first) >= 3 else [])
        rx = re.compile(r"(?<!\w)(" + "|".join(alts) + r")(?!\w)", re.I)
        short, long_, seen = [], [], set()
        for r in massive.news(ticker, 50):
            if not isinstance(r, dict):
                continue
            title = " ".join(str(r.get("title") or "").split())
            if (not title or title.lower() in seen or sp.ADVICE_HEADLINE.search(title) or _PITCH_RX.search(title)
                    or not rx.search(title)):
                continue
            mood = next((str(i.get("sentiment") or "").lower() for i in (r.get("insights") or [])
                         if isinstance(i, dict) and str(i.get("ticker") or "").upper() == ticker), "")
            if mood not in ("positive", "negative"):
                continue
            seen.add(title.lower())
            words = title.split()
            is_short = len(words) <= _MAX_WORDS
            if not is_short:
                title = " ".join(words[:_MAX_WORDS]).rstrip(",;:-") + "\u2026"
            pub = (r.get("publisher") or {}).get("name") if isinstance(r.get("publisher"), dict) else ""
            day = str(r.get("published_utc") or "")[:10]
            try:
                dd = date.fromisoformat(day); when = f"{_MON[dd.month - 1]} {dd.day}"
            except ValueError:
                when = ""
            src = ", ".join(x for x in (pub, when) if x)
            line = f"{title}{' (' + src + ')' if src else ''}: tagged {mood} by the feed"
            (short if is_short else long_).append(line)
        return (short or long_)[:limit]
    except Exception:
        return []
