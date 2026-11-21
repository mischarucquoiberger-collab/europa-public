"""Massive: an optional source for prices, company details, related companies, news and
dividends. Nothing here is required for a report; a caller treats SourceUnavailable as a gap.

The owner's plan (confirmed against the live API): five years of daily history, no fundamentals,
no live quote. The key travels only in the `Authorization: Bearer` header, never in a URL, so it
cannot reach a cache file name, a recording, a log line or an error message. Massive responses are
never written to the committed replay folder (see http.CACHE_ONLY_HOSTS).
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass

from backend import settings
from backend.sources import tickers
from backend.sources.http import Client, SourceUnavailable, default_client

BASE = "https://api.massive.com"
MAX_DAYS = 1825            # five years: the plan's history limit

HOUR = 3600
DAY = 24 * HOUR


@dataclass(frozen=True)
class Bar:
    """One daily bar, split- and dividend-adjusted."""
    date: str               # ISO trading date
    open: float
    high: float
    low: float
    close: float
    volume: float


def _headers(url: str) -> dict[str, str]:
    key = settings.secret("MASSIVE_API_KEY")
    if not key:
        raise SourceUnavailable(url, "MASSIVE_API_KEY is not set")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate"}


def _symbol(symbol: str) -> str:
    return urllib.parse.quote(tickers.for_massive(symbol), safe=".")


def _get(path: str, client: Client | None, *, params: dict | None = None, ttl: float = HOUR):
    url = BASE + path
    headers = _headers(url)
    data = (client or default_client()).get_json(url, params=params, headers=headers, ttl=ttl)
    return data if isinstance(data, dict) else {}


def _iso_date(ms_epoch) -> str | None:
    """A bar's `t` (milliseconds since 1970, the start of the trading day in New York, which
    is the same calendar day in UTC) as an ISO date."""
    try:
        return dt.datetime.fromtimestamp(float(ms_epoch) / 1000.0, tz=dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def details(symbol: str, client: Client | None = None) -> dict:
    """Reference data for the symbol (`/v3/reference/tickers/{T}` -> `results`); {} when absent."""
    data = _get(f"/v3/reference/tickers/{_symbol(symbol)}", client, ttl=DAY)
    results = data.get("results")
    return results if isinstance(results, dict) else {}


def daily_bars(symbol: str, days: int, client: Client | None = None, *,
               today: dt.date | None = None) -> list[Bar]:
    """Adjusted daily bars for the last `days` calendar days (capped at 1825, the plan's five
    years), oldest first. `today` is the end date (default: today), set by tests."""
    span = max(1, min(int(days), MAX_DAYS))
    end = today or dt.date.today()
    start = end - dt.timedelta(days=span)
    data = _get(f"/v2/aggs/ticker/{_symbol(symbol)}/range/1/day/{start.isoformat()}/{end.isoformat()}",
                client, params={"adjusted": "true", "sort": "asc", "limit": 50000})
    bars = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        date = _iso_date(item.get("t"))
        values = [_number(item.get(k)) for k in ("o", "h", "l", "c", "v")]
        if date is None or any(v is None for v in values):
            continue                                   # an incomplete row is left out, never zeroed
        bars.append(Bar(date, *values))
    bars.sort(key=lambda bar: bar.date)                # ISO dates sort in time order
    return bars


def previous_close(symbol: str, client: Client | None = None) -> dict | None:
    """The previous trading day's bar: `{"date", "close", "open", "high", "low", "volume"}`.
    An end-of-day figure, not a live quote (the plan has no live quotes); None when there is
    no row."""
    data = _get(f"/v2/aggs/ticker/{_symbol(symbol)}/prev", client)
    rows = [r for r in data.get("results") or [] if isinstance(r, dict) and _number(r.get("c")) is not None]
    if not rows:
        return None
    row = rows[0]
    return {"date": _iso_date(row.get("t")), "close": _number(row.get("c")),
            "open": _number(row.get("o")), "high": _number(row.get("h")),
            "low": _number(row.get("l")), "volume": _number(row.get("v"))}


def related(symbol: str, client: Client | None = None) -> list[str]:
    """Related companies' symbols, normalised (`BRK.B` form), without the symbol itself;
    symbols outside contract.TICKER_RE are left out."""
    own = tickers.normalise(symbol)
    data = _get(f"/v1/related-companies/{_symbol(symbol)}", client, ttl=DAY)
    found: list[str] = []
    for item in data.get("results") or []:
        try:
            other = tickers.normalise(str((item or {}).get("ticker", "")))
        except (ValueError, AttributeError):
            continue
        if other != own and other not in found:
            found.append(other)
    return found


SENTIMENTS = frozenset({"positive", "neutral", "negative"})


def _sentiment(item: dict, ticker: str) -> str | None:
    """The plan's per-ticker sentiment label for `ticker` (`insights[].sentiment`), or None."""
    for insight in item.get("insights") or []:
        if isinstance(insight, dict) and str(insight.get("ticker") or "").upper() == ticker:
            label = str(insight.get("sentiment") or "").strip().lower()
            return label if label in SENTIMENTS else None
    return None


def news(symbol: str, limit: int = 5, client: Client | None = None, *,
         detail: bool = False) -> list[dict]:
    """Recent articles about the symbol: `[{title, url, published, publisher}]`. Items without
    an http(s) link are left out (every source must be openable). With `detail=True` each item
    also has `description` (the provider's short summary, "" when none), `tickers` (every
    symbol the provider tagged the article with, upper case; Massive tags each one it mentions)
    and `sentiment` ("positive" | "neutral" | "negative" for this symbol when the plan returns
    insights, else None)."""
    ticker = tickers.for_massive(symbol)
    params = {"ticker": ticker, "limit": max(1, min(int(limit), 50))}
    data = _get("/v2/reference/news", client, params=params, ttl=15 * 60)
    items = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("article_url") or "")
        if not url.startswith(("https://", "http://")):
            continue
        publisher = item.get("publisher")
        row = {"title": str(item.get("title") or ""), "url": url,
               "published": str(item.get("published_utc") or ""),
               "publisher": str(publisher.get("name") or "") if isinstance(publisher, dict) else ""}
        if detail:
            row["description"] = str(item.get("description") or "")
            row["tickers"] = [t.strip().upper() for t in item.get("tickers") or []
                              if isinstance(t, str) and t.strip()]
            row["sentiment"] = _sentiment(item, ticker)
        items.append(row)
    return items


def dividends(symbol: str, limit: int = 8, client: Client | None = None) -> list[dict]:
    """The raw `results` rows of `/stocks/v1/dividends` for the symbol, as Massive sends them."""
    params = {"ticker": tickers.for_massive(symbol), "limit": max(1, min(int(limit), 1000))}
    data = _get("/stocks/v1/dividends", client, params=params, ttl=DAY)
    results = data.get("results")
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []
