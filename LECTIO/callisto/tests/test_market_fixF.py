"""Fix F: 52-week gap facts and dividend facts. Bars and dividends are SYNTHETIC."""
import os
from datetime import date

import pytest

os.environ.setdefault("PYTEST_CURRENT_TEST", "fixF")
from backend import massive  # noqa: E402
from backend import specialists as sp  # noqa: E402


def _bars():  # SYNTHETIC: last close 90, 52-week intraday high 120, low 60
    out = []
    for i, (d, c) in enumerate([("2026-01-05", 100.0), ("2026-03-02", 110.0), ("2026-06-01", 70.0),
                                ("2026-11-19", 95.0), ("2026-11-20", 90.0)]):
        out.append({"date": d, "o": c, "h": c, "l": c, "c": c, "v": 2_000_000.0})
    out[1]["h"], out[2]["l"] = 120.0, 60.0
    return out


def test_gap_facts():
    f, _ = sp._price_facts(_bars())
    assert f["gap_52w_high_pct"]["value"] == pytest.approx(25.0) and f["gap_52w_high_pct"]["kind"] == "pct"
    assert f["gap_52w_low_pct"]["value"] == pytest.approx(50.0) and f["gap_52w_low_pct"]["display"] == "50.0%"
    assert "Distance below the fifty-two-week high" in f["gap_52w_high_pct"]["label"]


def _run(monkeypatch, divs):
    monkeypatch.setenv("MASSIVE_API_KEY", "k")
    monkeypatch.setattr(massive, "today_et", lambda: date(2026, 11, 21))
    monkeypatch.setattr(massive, "daily_bars", lambda *a, **k: _bars())
    monkeypatch.setattr(massive, "ticker_overview", lambda t: {})
    if isinstance(divs, Exception):
        def boom(*a, **k):
            raise divs
        monkeypatch.setattr(massive, "dividends", boom)
    else:
        monkeypatch.setattr(massive, "dividends", lambda *a, **k: divs)
    return sp._market({"ticker": "MSFT"})


def test_dividend_facts(monkeypatch):
    divs = [{"cash_amount": 0.5, "ex_dividend_date": "2026-11-10", "pay_date": "2026-11-20", "frequency": 4,
             "dividend_type": "CD"},
            {"cash_amount": 9.0, "ex_dividend_date": "2026-11-15", "frequency": 0, "dividend_type": "SC"}]
    p = _run(monkeypatch, divs)
    f = p["facts"]
    assert f["div_cash_last"]["value"] == 0.5 and "2026-11-10" in f["div_cash_last"]["label"]
    assert f["div_annual"]["value"] == 2.0 and f["div_annual"]["kind"] == "usd_per_share"
    assert f["div_yield_pct"]["value"] == pytest.approx(2.0 / 90.0 * 100, abs=1e-3) and f["div_yield_pct"]["kind"] == "pct"
    assert "2026-11-10" in p["allow_dates"] and "2026-11-20" in p["allow_dates"]
    assert "pay date of 2026-11-20" in p["sheet"] and "four times a year" in p["sheet"]


def test_no_recent_dividend(monkeypatch):
    p = _run(monkeypatch, [{"cash_amount": 0.5, "ex_dividend_date": "2024-01-10", "frequency": 4, "dividend_type": "CD"}])
    assert not any(k.startswith("div_") for k in p["facts"])
    assert "DIVIDENDS: Massive lists no cash dividend for this ticker in the past year." in p["sheet"]


def test_dividend_failure_keeps_pack(monkeypatch):
    p = _run(monkeypatch, massive.Unavailable("network", "could not reach Massive"))
    assert p["status"] == "ok" and "px_close_last" in p["facts"] and "DIVIDENDS" not in p["sheet"]
