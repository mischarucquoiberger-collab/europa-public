"""Fix E: prior-close date, return windows, sheet labels. Offline, fake bars with a weekend."""
from backend import specialists as sp


def _bars(dates, closes):
    return [{"date": d, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 2_000_000.0} for d, c in zip(dates, closes)]


def test_prior_close_is_previous_trading_day_across_weekend():
    f, as_of = sp._price_facts(_bars(["2026-11-12", "2026-11-13", "2026-11-16"], [100.0, 110.0, 121.0]))
    assert as_of == "2026-11-16"
    assert f["px_close_prior"]["value"] == 110.0
    assert f["px_close_prior"]["as_of"] == "2026-11-13"
    assert "2026-11-13" in f["px_close_prior"]["source"]
    assert f["px_close_last"]["as_of"] == "2026-11-16"
    assert f["ret_1d_pct"]["value"] == 10.0          # 121 vs Friday's 110, not vs Thursday
    assert f["ret_1d_pct"]["as_of"] == "2026-11-16"


def test_windows_skip_when_base_bar_is_far_off():
    # Two bars a month apart: the "one day" base is 30 days back, so no one-day return is claimed.
    f, _ = sp._price_facts(_bars(["2026-10-12", "2026-11-16"], [100.0, 110.0]))
    assert "ret_1d_pct" not in f and "px_close_prior" in f


def test_market_pack_labels_and_prior_fact_date(monkeypatch):
    from backend import massive
    from datetime import date
    bars = _bars(["2026-11-12", "2026-11-13", "2026-11-16"], [100.0, 110.0, 121.0])
    monkeypatch.setenv("MASSIVE_API_KEY", "k")
    monkeypatch.setattr(massive, "today_et", lambda: date(2026, 11, 17))
    monkeypatch.setattr(massive, "daily_bars", lambda *a, **k: bars)
    monkeypatch.setattr(massive, "ticker_overview", lambda t: {})
    p = sp.market({"ticker": "AAPL", "question": ""})
    assert p["as_of"] == "2026-11-16" and p["allow_dates"] == ["2026-11-16", "2026-11-13"]
    assert p["facts"]["px_close_prior"]["as_of"] == "2026-11-13"
    assert "highest intraday price in the past year" in p["sheet"]
    assert "last close against the close before" in p["sheet"]


def test_company_name_helper():
    assert sp.company_name("NVDA") == "NVIDIA Corporation" and sp.company_name("AAPL") == "Apple Inc."
    assert sp.company_name("ZZZZ") is None


def test_ytd_and_year_labels_explicit():
    dates = ["2025-11-14", "2025-12-31", "2026-11-16"]
    f, _ = sp._price_facts(_bars(dates, [100.0, 105.0, 121.0]))
    assert f["ret_ytd_pct"]["value"] == round((121 / 105 - 1) * 100, 4)
    assert f["ret_1y_pct"]["value"] == 21.0
    assert "previous year" in f["ret_ytd_pct"]["label"]
