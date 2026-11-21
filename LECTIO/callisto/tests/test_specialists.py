"""Specialist tests. All Massive network is mocked; the key is a fake; dates are pinned."""
from datetime import date, datetime, timedelta

import httpx
import pytest

from backend import facts, massive, specialists as sp

FAKE = "test-key"
TODAY = date(2026, 11, 20)
PACK_KEYS = {"agent", "status", "reason", "source", "as_of", "facts", "exclude", "sheet", "allow_text",
             "allow_dates", "items", "crosscheck", "seconds"}


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    old = massive._TRANSPORT
    massive.clear_cache()
    monkeypatch.setattr(massive, "today_et", lambda: TODAY)
    yield
    massive._TRANSPORT = old
    massive.clear_cache()


def _ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=massive.ET).timestamp() * 1000)


def _weekdays(n, end):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


DAYS = _weekdays(300, TODAY)
CLOSES = [100 + i * 0.5 for i in range(300)]


def _bars():
    rows = []
    for i, d in enumerate(DAYS):
        c = CLOSES[i]
        rows.append({"t": _ms(d), "o": c - 0.25, "h": c + 1, "l": c - 1, "c": c,
                     "v": 52_345_678 if i == 299 else 1000})
    rows[0]["h"] = 999.0     # older than one year: must not count for the 52-week high
    rows[200]["h"] = 400.0   # inside the 52-week window
    return rows


OVERVIEW = {"name": "Apple Inc.", "market_cap": 3.456e12, "weighted_shares_outstanding": 15_120_000_000}


def _router(bars_status=200, ov_status=200, income=None, income_status=200, news_rows=None):
    def h(req):
        p = req.url.path
        if p.startswith("/v2/aggs/"):
            return httpx.Response(bars_status, json={"results": _bars()})
        if p.startswith("/v3/reference/tickers/"):
            return httpx.Response(ov_status, json={"results": OVERVIEW})
        if p == "/stocks/financials/v1/income-statements":
            return httpx.Response(income_status, json={"results": income or []})
        if p == "/v2/reference/news":
            return httpx.Response(200, json={"results": news_rows or []})
        return httpx.Response(404)
    massive._TRANSPORT = httpx.MockTransport(h)


def _check_pack(p, agent):
    assert set(p) == PACK_KEYS, set(p) ^ PACK_KEYS
    assert p["agent"] == agent and p["status"] in ("ok", "unavailable")
    assert isinstance(p["seconds"], float)
    if p["status"] == "unavailable":
        assert p["reason"] and p["facts"] == {} and p["sheet"] == ""


# ---- market ----

def test_market_synthetic_series(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router()
    p = sp.MARKET.invoke({"ticker": "AAPL", "question": "how did the stock do"})
    _check_pack(p, "market")
    f = p["facts"]
    assert p["status"] == "ok" and p["as_of"] == "2026-11-20"
    assert f["px_close_last"]["value"] == 249.5 and f["px_close_last"]["display"] == "$249.50"
    assert f["px_close_prior"]["value"] == 249.0
    assert f["ret_1d_pct"]["value"] == round((249.5 / 249.0 - 1) * 100, 4) == 0.2008
    assert f["ret_1d_pct"]["display"] == "+0.2%"
    assert f["ret_1m_pct"]["value"] == round((249.5 / CLOSES[299 - 21] - 1) * 100, 4)
    assert f["ret_1m_pct"]["display"] == "+4.4%"
    assert f["px_52w_high"]["value"] == 400.0 and f["px_52w_high"]["display"] == "$400.00"
    assert f["volume_last"]["display"] == "52.3 million"
    assert f["market_cap"]["display"] == "$3.46 trillion" and f["market_cap"]["as_of"] == "2026-11-20"
    assert f["shares_outstanding"]["display"] == "15.12 billion"
    # one year back: last bar on or before 2025-11-20
    base = [c for d, c in zip(DAYS, CLOSES) if d <= date(2025, 11, 20)][-1]
    assert f["ret_1y_pct"]["value"] == round((249.5 / base - 1) * 100, 4)
    base_ytd = [c for d, c in zip(DAYS, CLOSES) if d.year < 2026][-1]
    assert f["ret_ytd_pct"]["value"] == round((249.5 / base_ytd - 1) * 100, 4)
    for fid, fa in f.items():
        assert fa["source"] and fa["as_of"] and fa["kind"] in ("usd", "usd_per_share", "pct", "count")
        assert fa["provider"] == "massive" and fa["display"]
        if fid not in ("px_52w_high", "px_52w_low"):
            assert not any(ch.isdigit() for ch in fa["label"]), fa["label"]
    assert p["sheet"].startswith("MARKET DATA (Massive, end-of-day, as of 2026-11-20; id | what | value):")
    assert "px_close_last | Closing price, last trading day | $249.50" in p["sheet"]
    assert p["allow_text"] == ["52-week", "6 months", "6-month", "6 month"] and p["allow_dates"] == ["2026-11-20", "2026-11-19"]


def test_market_overview_fails_keeps_prices(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(ov_status=403)
    p = sp.market({"ticker": "AAPL", "question": ""})
    assert p["status"] == "ok" and "px_close_last" in p["facts"] and "market_cap" not in p["facts"]


def test_market_bars_fail_keeps_overview(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(bars_status=429)
    p = sp.market({"ticker": "AAPL", "question": ""})
    assert p["status"] == "ok" and set(p["facts"]) == {"market_cap", "shares_outstanding"}


def test_market_no_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    _router()
    p = sp.market({"ticker": "AAPL", "question": ""})
    _check_pack(p, "market")
    assert p["status"] == "unavailable" and "MASSIVE_API_KEY" in p["reason"] and p["facts"] == {}


def test_market_bad_ticker_never_raises(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router()
    p = sp.market({"ticker": "../x", "question": ""})
    _check_pack(p, "market")
    assert p["status"] == "unavailable"


def test_formatters():
    assert sp.fmt_price(1234.555) == "$1,234.56"
    assert sp.fmt_pct(3.25) == "+3.3%" and sp.fmt_pct(-1.44) == "-1.4%"
    assert sp.fmt_usd_big(812.44e9) == "$812.4 billion"
    assert sp.fmt_count(52_300_000) == "52.3 million"


# ---- fundamentals ----

def _income(rev_factor=1.0):
    F = facts.FACTS["AAPL"]
    rows = []
    for fy, pe in [("fy2026", "2026-09-26"), ("fy2025", "2025-09-27")]:
        rows.append({"period_end": pe, "timeframe": "annual",
                     "revenue": F[f"revenue_{fy}"]["value"] * (rev_factor if fy == "fy2026" else 1.0),
                     "gross_profit": F[f"gross_margin_{fy}"]["value"],
                     "research_development": F[f"rnd_{fy}"]["value"],
                     "operating_income": F[f"operating_income_{fy}"]["value"],
                     "consolidated_net_income_loss": F[f"net_income_{fy}"]["value"],
                     "diluted_earnings_per_share": F[f"eps_diluted_{fy}"]["value"] + 0.004})
    return rows


def test_fundamentals_all_agree(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(income=_income())
    p = sp.FUNDAMENTALS.invoke({"ticker": "AAPL", "question": ""})
    _check_pack(p, "fundamentals")
    assert p["status"] == "ok" and p["exclude"] == [] and p["facts"] == {}
    assert len(p["crosscheck"]) == 12 and all(c["result"] == "AGREE" for c in p["crosscheck"])
    assert "do not use: none." in p["sheet"]


def test_fundamentals_revenue_disagrees(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(income=_income(rev_factor=1.01))
    p = sp.fundamentals({"ticker": "AAPL", "question": ""})
    bad = [c for c in p["crosscheck"] if c["result"] == "DISAGREE"]
    assert [c["fact_id"] for c in bad] == ["revenue_fy2026"]
    for i in ["revenue_fy2026", "revenue_change_pct", "revenue_change_amount", "gross_margin_pct_fy2026",
              "gross_margin_pct_fy2025", "gross_margin_pct_change_pts"]:
        assert i in p["exclude"]
    assert len(p["exclude"]) == len(set(p["exclude"])) == 6
    assert "revenue_fy2026" not in p["sheet"].split("NOT confirmed")[0]
    # no counts or other digits in the sheet outside fact ids
    import re
    assert not re.findall(r"\d", re.sub(r"[a-z_]+[a-z0-9_]*", "", p["sheet"]))


def test_fundamentals_unknown_field_names_confirm_nothing(monkeypatch):
    """Rows for both years but none of the expected field names: nothing compared, so nothing is 'confirmed'."""
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(income=[{"period_end": pe, "timeframe": "annual", "revenues_total": 1.0}
                    for pe in ("2026-09-26", "2025-09-27")])
    p = sp.fundamentals({"ticker": "AAPL", "question": ""})
    assert p["status"] == "ok" and p["exclude"] == []
    assert len(p["crosscheck"]) == 12 and all(c["result"] == "NOT_COMPARED" for c in p["crosscheck"])
    assert "confirmed by a second source: none." in p["sheet"]


def test_fundamentals_not_entitled(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(income_status=403)
    p = sp.fundamentals({"ticker": "AAPL", "question": ""})
    _check_pack(p, "fundamentals")
    assert p["status"] == "unavailable" and p["reason"] == "the Massive plan on this key does not include this data"


def test_fundamentals_no_rows_and_unknown_ticker(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(income=[{"period_end": "2020-09-26", "revenue": 1}])
    p = sp.fundamentals({"ticker": "AAPL", "question": ""})
    assert p["status"] == "unavailable" and "no annual income statement" in p["reason"]
    p = sp.fundamentals({"ticker": "MSFT", "question": ""})
    assert p["status"] == "unavailable" and p["reason"] == "no SEC facts loaded to cross-check against"


# ---- news ----

NEWS = [
    {"id": "n1", "title": "Apple reports record services revenue", "publisher": {"name": "Wire A"},
     "published_utc": "2026-11-20T14:00:00Z", "article_url": "https://example.com/a"},
    {"id": "n2", "title": "Is Apple a Buy before earnings?", "publisher": {"name": "Wire B"},
     "published_utc": "2026-11-19T14:00:00Z", "article_url": "https://example.com/b"},
    {"id": "n3", "title": "Analyst upgrades Apple, raises price target", "publisher": {"name": "Wire C"},
     "published_utc": "2026-11-18T14:00:00Z", "article_url": "https://example.com/c"},
]


def test_news_filters_and_maps(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(news_rows=NEWS)
    p = sp.NEWS.invoke({"ticker": "AAPL", "question": ""})
    _check_pack(p, "news")
    assert p["status"] == "ok" and p["sheet"] == "" and p["facts"] == {}
    assert p["items"] == [{"id": "n1", "title": "Apple reports record services revenue", "publisher": "Wire A",
                           "published_utc": "2026-11-20T14:00:00Z", "url": "https://example.com/a", "summary": ""}]


def test_news_drops_number_claims_and_other_companies(monkeypatch):
    """An unverified number never reaches the screen, and a headline must name the company or its ticker."""
    rows = [("x1", "Costco's U.S. Comparable Sales Jumped 12.6%. Is the Rally Sustainable?"),
            ("x2", "Apple Services Revenue Climbs 14 Percent"),
            ("x3", "Apple Adds $100 Billion to Its Repurchase Plan"),
            ("x4", "Apple Supplier Says Orders Rose 3x"),
            ("x5", "Advisor Insights \u2014 Brought to You By The Motley Fool"),
            ("x6", "Stock Market Today, Nov. 20: Stocks Plunge as AI Trade Unwinds"),
            ("x7", "Applebee's Opens New Restaurants"),
            ("k1", "Apple Unveils New Chip at Developer Event on Nov. 20"),
            ("k2", "Why AAPL Shares Moved on Friday"),
            ("k3", "Apple's Latest iPhone 18 Reviewed")]
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(news_rows=[{"id": i, "title": t, "publisher": {"name": "Wire"}, "published_utc": "2026-11-20T14:00:00Z",
                        "article_url": "https://example.com/" + i} for i, t in rows])
    p = sp.news({"ticker": "AAPL", "question": ""})
    assert p["status"] == "ok" and [it["id"] for it in p["items"]] == ["k1", "k2", "k3"]
    for title in ["Shares Jump 12.6%", "Up 5 percent", "a $1 Million Portfolio", "9.3% ARPU Rise", "Gains 40 bps",
                  "Rose 2.5x", "a 3-fold jump", "adds 200 points", "\u20ac500 fine"]:
        assert sp.NUMBER_HEADLINE.search(title), title
    for title in ["Stock Market Today, Nov. 20: Stocks Plunge", "Apple's Latest iPhone 18 Reviewed", "Top 10 moments"]:
        assert not sp.NUMBER_HEADLINE.search(title), title


def test_news_unavailable(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", FAKE)
    _router(news_rows=NEWS[1:])
    assert sp.news({"ticker": "AAPL", "question": ""})["reason"] == "no recent headlines that mention the company"
    _router(news_rows=[{"id": "m1", "title": "Stock Market Today: Tech Shares Slide", "publisher": {"name": "W"},
                        "published_utc": "2026-11-20T14:00:00Z", "article_url": "https://example.com/m"}])
    massive.clear_cache()
    assert sp.news({"ticker": "AAPL", "question": ""})["status"] == "unavailable"
    monkeypatch.delenv("MASSIVE_API_KEY")
    p = sp.news({"ticker": "AAPL", "question": ""})
    _check_pack(p, "news")
    assert p["status"] == "unavailable" and "MASSIVE_API_KEY" in p["reason"]


# ---- filings ----

def test_filings():
    p = sp.FILINGS.invoke({"ticker": "AAPL", "question": ""})
    _check_pack(p, "filings")
    assert p["status"] == "ok" and "revenue_fy2026" in p["sheet"] and p["facts"] == {}
    assert p["allow_dates"] == ["2026-09-26", "2025-09-27", "2026-11-03"]
    p = sp.filings({"ticker": "MSFT", "question": ""})
    _check_pack(p, "filings")
    assert p["reason"] == "no SEC filings are loaded for MSFT in this demo"


def test_registry_names():
    assert set(sp.SPECIALISTS) == {"filings", "market", "fundamentals", "news"}
    assert sp.MARKET.name == "specialist_market" and sp.FILINGS.name == "specialist_filings"
    assert sp.FUNDAMENTALS.name == "specialist_fundamentals" and sp.NEWS.name == "specialist_news"


def test_every_pack_has_every_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    for name, fn in [("filings", sp.filings), ("market", sp.market), ("fundamentals", sp.fundamentals),
                     ("news", sp.news)]:
        for t in ("AAPL", "MSFT", ""):
            _check_pack(fn({"ticker": t, "question": ""}), name)
