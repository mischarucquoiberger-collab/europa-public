"""Massive client tests. All network is mocked with httpx.MockTransport; the key is a fake."""
from datetime import date, datetime

import httpx
import pytest

from backend import massive

FAKE = "test-key"


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    old = massive._TRANSPORT
    massive.clear_cache()
    yield
    massive._TRANSPORT = old
    massive.clear_cache()


def _mock(handler):
    calls = []

    def h(req):
        calls.append(req)
        return handler(req)
    massive._TRANSPORT = httpx.MockTransport(h)
    return calls


def test_no_key_never_calls(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    calls = _mock(lambda r: httpx.Response(200, json={}))
    assert massive.available() is False
    with pytest.raises(massive.Unavailable) as e:
        massive.get("/v3/reference/tickers/AAPL")
    assert e.value.code == "no_key" and "MASSIVE_API_KEY" in e.value.reason
    assert calls == []


def test_auth_header_and_no_key_in_url(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    calls = _mock(lambda r: httpx.Response(200, json={"results": {"name": "Apple"}}))
    assert massive.ticker_overview("AAPL") == {"name": "Apple"}
    req = calls[0]
    assert req.headers["Authorization"] == f"Bearer {FAKE}"
    assert FAKE not in str(req.url)
    assert req.url.path == "/v3/reference/tickers/AAPL"


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (403, "not_entitled"),
                                         (429, "rate_limited"), (500, "http_error"), (404, "not_found")])
def test_error_map(monkeypatch, status, code):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _mock(lambda r: httpx.Response(status, json={"status": "ERROR", "error": "x"}))
    with pytest.raises(massive.Unavailable) as e:
        massive.get("/v2/reference/news", {"ticker": "AAPL"})
    assert e.value.code == code
    assert FAKE not in e.value.reason and "://" not in e.value.reason
    assert "massive.com" not in e.value.reason and "Bearer" not in e.value.reason


def test_timeout_and_bad_json(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)

    def boom(r):
        raise httpx.ReadTimeout("slow", request=r)
    _mock(boom)
    with pytest.raises(massive.Unavailable) as e:
        massive.get("/x")
    assert e.value.code == "network" and FAKE not in e.value.reason and "/x" not in e.value.reason
    _mock(lambda r: httpx.Response(200, content=b"not json"))
    with pytest.raises(massive.Unavailable) as e:
        massive.get("/y")
    assert e.value.code == "http_error"


def test_cache_and_stale_if_error(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    calls = _mock(lambda r: httpx.Response(200, json={"n": 1}))
    assert massive.get("/c", {"a": 1}) == {"n": 1}
    assert massive.get("/c", {"a": 1}) == {"n": 1}
    assert len(calls) == 1
    # refresh (ttl=0 forces it) fails -> older entry served
    calls2 = _mock(lambda r: httpx.Response(500))
    assert massive.get("/c", {"a": 1}, ttl=0) == {"n": 1}
    assert len(calls2) == 1


def test_not_entitled_cached_briefly(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    calls = _mock(lambda r: httpx.Response(403))
    for _ in range(2):
        with pytest.raises(massive.Unavailable):
            massive.get("/stocks/financials/v1/income-statements", {"tickers": "AAPL"})
    assert len(calls) == 1
    calls = _mock(lambda r: httpx.Response(500))
    for _ in range(2):
        with pytest.raises(massive.Unavailable):
            massive.get("/z")
    assert len(calls) == 2  # other failures are not cached


def test_valid_ticker():
    for bad in ["../x", "AAPL/prev", "", "aapl", None, "TOOLONGTICKER"]:
        assert not massive.valid_ticker(bad)
    for good in ["AAPL", "BRK.B", "BF-B", "X"]:
        assert massive.valid_ticker(good)


def test_bad_ticker_raises_before_network(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    calls = _mock(lambda r: httpx.Response(200, json={}))
    with pytest.raises(massive.Unavailable) as e:
        massive.news("../x")
    assert e.value.code == "bad_ticker" and calls == []


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=massive.ET).timestamp() * 1000)


def test_bars_parse_et_dates_ascending(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    rows = [{"t": _ms(date(2026, 11, 20)), "o": 2, "h": 3, "l": 1, "c": 2.5, "v": 10},
            {"t": _ms(date(2026, 3, 9)), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 5}]  # day after DST start
    calls = _mock(lambda r: httpx.Response(200, json={"results": rows}))
    bars = massive.daily_bars("AAPL", date(2026, 1, 1), date(2026, 11, 20))
    assert [b["date"] for b in bars] == ["2026-03-09", "2026-11-20"]
    assert bars[1]["c"] == 2.5
    q = dict(calls[0].url.params)
    assert q == {"adjusted": "true", "sort": "asc", "limit": "5000"}
    assert calls[0].url.path == "/v2/aggs/ticker/AAPL/range/1/day/2026-01-01/2026-11-20"


def test_bars_empty(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _mock(lambda r: httpx.Response(200, json={"resultsCount": 0}))
    with pytest.raises(massive.Unavailable) as e:
        massive.daily_bars("AAPL", date(2026, 1, 1), date(2026, 1, 2))
    assert e.value.code == "empty"
