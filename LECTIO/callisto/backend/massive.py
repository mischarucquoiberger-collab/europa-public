"""Massive market data client (formerly Polygon.io). Public market data only.

Auth is the header `Authorization: Bearer <key>` only; the key never goes in a URL.
Every failure becomes `Unavailable(code, reason)`; the reason is plain English and never holds
a URL, a header or a key. No retries, no sleeping. Small in-memory cache with stale-if-error.
Docs used: PLAN-MULTIAGENT.md section 4 (T1). Exact 403 body and rate limit are UNVERIFIED.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from backend._env import load_env  # noqa: E402  keys: repo-root .env

load_env()

BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
ET = ZoneInfo("America/New_York")
_TRANSPORT = None  # tests set this to httpx.MockTransport(handler)
_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_FAIL_TTL = 60.0  # seconds to remember a key / plan rejection

_lock = threading.Lock()
_cache: dict = {}  # key -> (stored_at, data)
_fail: dict = {}   # key -> (stored_at, Unavailable) for unauthorized / not_entitled only
_now = time.monotonic


class Unavailable(Exception):
    """Massive data could not be used. .code is machine-readable, .reason is plain English."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def available() -> bool:
    return bool(os.environ.get("MASSIVE_API_KEY", "").strip())


def valid_ticker(t) -> bool:
    return isinstance(t, str) and bool(_TICKER_RE.match(t))


def today_et() -> date:
    return datetime.now(ET).date()


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _fail.clear()


def _check_ticker(ticker) -> None:
    if not valid_ticker(ticker):
        raise Unavailable("bad_ticker", "that does not look like a valid stock ticker")


def _fetch(path: str, params: dict | None) -> dict:
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not key:
        raise Unavailable("no_key", "MASSIVE_API_KEY is not set")
    try:
        with httpx.Client(transport=_TRANSPORT, timeout=_TIMEOUT) as client:
            r = client.get(BASE_URL.rstrip("/") + path, params=params or None,
                           headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    except httpx.HTTPError:
        raise Unavailable("network", "could not reach Massive") from None
    code = r.status_code
    if code == 401:
        raise Unavailable("unauthorized", "Massive rejected the API key")
    if code == 403:
        raise Unavailable("not_entitled", "the Massive plan on this key does not include this data")
    if code == 429:
        raise Unavailable("rate_limited", "Massive rate limit reached, try again in a minute")
    if code == 404:
        raise Unavailable("not_found", "Massive has no data for that request")
    if not 200 <= code < 300:
        raise Unavailable("http_error", f"Massive returned HTTP {code}")
    try:
        data = r.json()
    except ValueError:
        raise Unavailable("http_error", "Massive returned data that could not be read") from None
    if not isinstance(data, dict):
        raise Unavailable("http_error", "Massive returned data that could not be read")
    return data


def get(path: str, params: dict | None = None, ttl: float = 600) -> dict:
    """GET a Massive path, parsed JSON. Raises Unavailable. Serves a stale entry if a refresh fails."""
    if not available():
        raise Unavailable("no_key", "MASSIVE_API_KEY is not set")
    ck = (path, tuple(sorted((str(k), str(v)) for k, v in (params or {}).items())))
    now = _now()
    with _lock:
        hit = _cache.get(ck)
        failed = _fail.get(ck)
    if hit and now - hit[0] < ttl:
        return hit[1]
    if failed and now - failed[0] < _FAIL_TTL:
        if hit:
            return hit[1]
        raise failed[1]
    try:
        data = _fetch(path, params)
    except Unavailable as e:
        if e.code in ("unauthorized", "not_entitled"):
            with _lock:
                _fail[ck] = (now, e)
        if hit:
            return hit[1]
        raise
    with _lock:
        _cache[ck] = (now, data)
        _fail.pop(ck, None)
    return data


def daily_bars(ticker: str, start: date, end: date) -> list[dict]:
    """Daily bars, oldest first: [{"date","o","h","l","c","v"}]. Dates are America/New_York."""
    _check_ticker(ticker)
    path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}"
    data = get(path, {"adjusted": "true", "sort": "asc", "limit": 5000})
    rows = data.get("results") or []
    bars = []
    for row in rows:
        try:
            d = datetime.fromtimestamp(float(row["t"]) / 1000.0, tz=ET).date()
            bars.append({"date": d.isoformat(), "o": float(row["o"]), "h": float(row["h"]),
                         "l": float(row["l"]), "c": float(row["c"]), "v": float(row.get("v") or 0.0)})
        except (KeyError, TypeError, ValueError):
            continue
    if not bars:
        raise Unavailable("empty", "Massive returned no price bars")
    bars.sort(key=lambda b: b["date"])
    return bars


def ticker_overview(ticker: str) -> dict:
    _check_ticker(ticker)
    res = get(f"/v3/reference/tickers/{ticker}").get("results")
    if not isinstance(res, dict) or not res:
        raise Unavailable("empty", "Massive returned no ticker details")
    return res


def income_statements(ticker: str, limit: int = 8) -> list[dict]:
    _check_ticker(ticker)
    data = get("/stocks/financials/v1/income-statements",
               {"tickers": ticker, "timeframe": "annual", "sort": "period_end.desc", "limit": int(limit)})
    res = data.get("results")
    return res if isinstance(res, list) else []


def news(ticker: str, limit: int = 10) -> list[dict]:
    _check_ticker(ticker)
    data = get("/v2/reference/news",
               {"ticker": ticker, "order": "desc", "sort": "published_utc", "limit": int(limit)})
    res = data.get("results")
    return res if isinstance(res, list) else []


def dividends(ticker: str, limit: int = 8) -> list[dict]:
    """Dividend records, newest ex-dividend date first (cash_amount, ex_dividend_date, pay_date, frequency, dividend_type)."""
    _check_ticker(ticker)
    data = get("/v3/reference/dividends",
               {"ticker": ticker, "order": "desc", "sort": "ex_dividend_date", "limit": int(limit)})
    res = data.get("results")
    return res if isinstance(res, list) else []
