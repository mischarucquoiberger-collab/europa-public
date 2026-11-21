"""Massive adapter over synthetic fixtures in Massive's response shapes."""
import datetime as dt
import urllib.parse
from pathlib import Path

import pytest

from backend.sources import massive
from backend.sources.http import Client, SourceUnavailable

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"
KEY = "mk-FAKE-offline-4444eeee5555ffff"                  # what tests/conftest.py sets
TODAY = dt.date(2026, 11, 20)


def route(path: str) -> str | None:
    if path.startswith("/v2/aggs/ticker/BRK.B/range/1/day/"):
        return "massive_aggs_daily.json"
    return {
        "/v3/reference/tickers/BRK.B": "massive_details.json",
        "/v2/aggs/ticker/BRK.B/prev": "massive_prev.json",
        "/v2/aggs/ticker/ZZZZ/prev": "massive_prev_empty.json",
        "/v1/related-companies/AAPL": "massive_related.json",
        "/v2/reference/news": "massive_news.json",
        "/stocks/v1/dividends": "massive_dividends.json",
    }.get(path)


class FixtureTransport:
    def __init__(self, status: int | None = None, body: bytes | None = None):
        self.status, self.body = status, body
        self.calls: list[dict] = []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": dict(headers)})
        if self.status is not None:
            return self.status, self.body or b"{}"
        parts = urllib.parse.urlsplit(url)
        name = route(parts.path) if parts.hostname == "api.massive.com" else None
        return (200, (FIXTURES / name).read_bytes()) if name else (404, b'{"status": "NOT_FOUND"}')


class Still:
    now = 1_000_000.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make(tmp_path, transport, mode="live"):
    still = Still()
    return Client(mode, cache_dir=tmp_path / "cache", replay_dir=tmp_path / "replay",
                  transport=transport, sleep=still.sleep, clock=still.clock)


@pytest.fixture
def transport():
    return FixtureTransport()


@pytest.fixture
def client(tmp_path, transport):
    return make(tmp_path, transport)


def query(url: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# --- prices --------------------------------------------------------------------------------

def test_daily_bars_are_capped_at_1825_days_and_converted_to_iso_dates_ascending(client, transport):
    bars = massive.daily_bars("brk-b", 5000, client, today=TODAY)
    url = transport.calls[-1]["url"]
    assert urllib.parse.urlsplit(url).path == "/v2/aggs/ticker/BRK.B/range/1/day/2021-11-21/2026-11-20"
    assert query(url) == {"adjusted": "true", "sort": "asc", "limit": "50000"}
    assert [b.date for b in bars] == ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]
    assert bars[0] == massive.Bar("2026-11-16", 475.0, 477.7, 474.3, 476.8, 2500000.0)
    # the row without a close is left out, not filled with zero
    assert all(b.close > 0 for b in bars)


def test_a_short_window_asks_for_just_that_window(client, transport):
    massive.daily_bars("BRK.B", 30, client, today=TODAY)
    assert urllib.parse.urlsplit(transport.calls[-1]["url"]).path.endswith("/2026-10-21/2026-11-20")


def test_previous_close_is_the_last_end_of_day_row(client):
    assert massive.previous_close("BRK.B", client) == {
        "date": "2026-11-19", "close": 483.0, "open": 481.6, "high": 484.1, "low": 480.9, "volume": 3300000.0,
    }


def test_previous_close_is_none_when_there_is_no_row(client, tmp_path):
    assert massive.previous_close("ZZZZ", client) is None
    no_results = make(tmp_path / "other", FixtureTransport(200, b'{"status": "OK", "resultsCount": 0}'))
    assert massive.previous_close("AAPL", no_results) is None


# --- reference data ------------------------------------------------------------------------

def test_details_use_the_dot_form_in_the_path(client, transport):
    assert massive.details("brk-b", client)["name"] == "Synthetic Holding Co. Class B"
    assert urllib.parse.urlsplit(transport.calls[-1]["url"]).path == "/v3/reference/tickers/BRK.B"


def test_related_gives_normalised_symbols_without_itself(client):
    assert massive.related("aapl", client) == ["MSFT", "GOOGL", "BRK.B"]


def test_news_keeps_linked_items_in_the_small_shape(client, transport):
    items = massive.news("aapl", limit=3, client=client)
    assert query(transport.calls[-1]["url"]) == {"ticker": "AAPL", "limit": "3"}
    assert items == [
        {"title": "Synthetic headline one", "url": "https://news.example.com/one",
         "published": "2026-11-20T14:30:00Z", "publisher": "Example Wire"},
        {"title": "Synthetic headline two", "url": "https://news.example.com/two",
         "published": "2026-11-18T08:00:00Z", "publisher": "Example Daily"},
    ]


def test_dividends_are_the_raw_results(client, transport):
    rows = massive.dividends("AAPL", client=client)
    assert query(transport.calls[-1]["url"]) == {"ticker": "AAPL", "limit": "8"}
    assert [r["cash_amount"] for r in rows] == [0.27, 0.26]
    assert rows[0]["ex_dividend_date"] == "2026-11-09"


# --- the key -------------------------------------------------------------------------------

def _every_call(client):
    return [
        lambda: massive.details("BRK.B", client),
        lambda: massive.daily_bars("BRK.B", 10, client, today=TODAY),
        lambda: massive.previous_close("BRK.B", client),
        lambda: massive.related("AAPL", client),
        lambda: massive.news("AAPL", client=client),
        lambda: massive.dividends("AAPL", client=client),
    ]


def test_the_key_travels_only_in_the_header(client, transport, tmp_path):
    for call in _every_call(client):
        call()
    assert len(transport.calls) == 6
    for request in transport.calls:
        assert KEY not in request["url"]
        assert "apikey" not in request["url"].lower()
        assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text() and KEY not in path.name


def test_an_empty_key_raises_before_any_request(client, transport, monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    for call in _every_call(client):
        with pytest.raises(SourceUnavailable) as caught:
            call()
        assert caught.value.reason == "MASSIVE_API_KEY is not set"
    assert transport.calls == []


def test_a_403_is_not_entitled(tmp_path):
    transport = FixtureTransport(403, b'{"status": "NOT_AUTHORIZED"}')
    with pytest.raises(SourceUnavailable) as caught:
        massive.daily_bars("AAPL", 365, make(tmp_path, transport), today=TODAY)
    assert caught.value.reason == "not entitled"
    assert len(transport.calls) == 1


def test_massive_answers_are_never_recorded_into_the_replay_folder(tmp_path, transport):
    recorder = make(tmp_path, transport, mode="record")
    massive.details("BRK.B", recorder)
    assert not (tmp_path / "replay").exists() or not any((tmp_path / "replay").rglob("*.json"))
    assert any((tmp_path / "cache").rglob("*.json"))


def test_news_with_detail_adds_the_description_and_this_symbols_sentiment(tmp_path):
    import json
    body = json.dumps({"status": "OK", "results": [
        {"title": "One", "article_url": "https://news.example.com/one", "published_utc": "2026-11-20T14:30:00Z",
         "publisher": {"name": "Example Wire"}, "description": "A short summary.", "tickers": ["AAPL", " msft ", 7],
         "insights": [{"ticker": "MSFT", "sentiment": "negative"}, {"ticker": "AAPL", "sentiment": "positive"}]},
        {"title": "Two", "article_url": "https://news.example.com/two", "published_utc": "2026-11-19T14:30:00Z",
         "insights": [{"ticker": "AAPL", "sentiment": "ecstatic"}]},
        {"title": "Three", "article_url": "https://news.example.com/three", "published_utc": "2026-11-18T14:30:00Z"},
    ]}).encode()
    client = make(tmp_path, FixtureTransport(status=200, body=body))
    items = massive.news("aapl", limit=50, client=client, detail=True)
    assert [(i["description"], i["sentiment"]) for i in items] == [("A short summary.", "positive"),
                                                                   ("", None), ("", None)]
    assert [i["tickers"] for i in items] == [["AAPL", "MSFT"], [], []]
    plain = massive.news("aapl", limit=50, client=client)                  # the default shape is unchanged
    assert set(plain[0]) == {"title", "url", "published", "publisher"}
