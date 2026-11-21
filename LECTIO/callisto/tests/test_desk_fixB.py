"""Non-Apple ticker: the answer says the demo covers Apple only, not 'data unavailable'."""
import pytest

from backend import desk
from tests.test_desk import Fakes, pack

NOT_APPLE = "are checked for Apple only"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("EUROPA_CHECKER", raising=False)
    monkeypatch.delenv("EUROPA_SKEPTIC", raising=False)
    monkeypatch.setattr(desk, "_massive_available", lambda: True)  # so the guard lets MSFT through


def _fakes():
    return Fakes(packs={"filings": pack("filings", "unavailable", reason="no filings for MSFT")})


@pytest.mark.parametrize("t", ["MSFT", "TSLA", "NVDA"])
def test_non_apple_ticker_says_apple_only(t):
    out = desk.answer(t, "What were net sales?", deps=_fakes().deps)
    assert out["status"] == "I_DONT_KNOW"
    assert NOT_APPLE in out["answer"] and "can't" not in out["answer"] and "I don't know" not in out["answer"]
    assert "unavailable right now" not in out["answer"]


def test_aapl_outage_keeps_old_message():
    out = desk.answer("AAPL", "What were net sales?", deps=_fakes().deps)
    assert out["status"] == "I_DONT_KNOW"
    assert "did not respond just now" in out["answer"] and NOT_APPLE not in out["answer"]


def test_advice_refusal_does_not_offer_apple_filings_for_another_ticker():
    from backend import desk
    other = desk._advice_answer("TSLA", "Should I buy Tesla stock?")
    assert "Apple (AAPL)" in other and "Tesla's stock" in other and "what Apple's filings say" not in other
    out = desk._guard({"question": "Should I buy Tesla stock?", "ticker": "TSLA"})
    assert out["stop"] == ("DECLINED_ADVICE", other)
    out = desk._guard({"question": "Should I buy Apple stock?", "ticker": "AAPL"})
    assert out["stop"][0] == "DECLINED_ADVICE" and "Apple's filings" in out["stop"][1]


def test_notices_never_say_cant_and_hold_no_digits():
    for t in (desk.NOTICE_FILINGS_OTHER, desk.NOTICE_FILINGS_OTHER_ASK, desk.NOTICE_NEWS_OTHER, desk.NOTICE_OUTAGE,
              desk.NOTICE_NOTHING):
        low = t.lower()
        assert "can't" not in low and "cannot" not in low and "won't" not in low and "don't know" not in low
        assert not any(ch.isdigit() for ch in t)


def test_ticker_name_uses_massive_for_unknown_tickers(monkeypatch):
    from backend import desk, massive
    monkeypatch.setattr(massive, "available", lambda: True)
    monkeypatch.setattr(massive, "ticker_overview", lambda t: {"name": "lululemon athletica inc."})
    assert desk._ticker_name("LULU") == "lululemon athletica"      # legal tail dropped for readable notices
    assert desk._ticker_name("NVDA") == "Nvidia"          # built-in names win
    assert desk._ticker_name("AAPL") == "Apple Inc."
    monkeypatch.setattr(massive, "ticker_overview", lambda t: {"name": "3M Company"})
    assert desk._ticker_name("MMM") is None               # digit in the name: notices fall back to the ticker


def test_ticker_name_is_none_when_massive_is_down(monkeypatch):
    from backend import desk, massive

    def boom(t):
        raise massive.Unavailable("network", "could not reach Massive")
    monkeypatch.setattr(massive, "available", lambda: True)
    monkeypatch.setattr(massive, "ticker_overview", boom)
    assert desk._ticker_name("LULU") is None


def test_unknown_ticker_is_true_only_on_not_found(monkeypatch):
    from backend import desk, massive

    def raiser(code):
        def f(t):
            raise massive.Unavailable(code, "x")
        return f
    monkeypatch.setattr(massive, "available", lambda: True)
    monkeypatch.setattr(massive, "ticker_overview", raiser("not_found"))
    assert desk._unknown_ticker("ZZZZQ") is True
    assert desk._unknown_ticker("AAPL") is False           # loaded ticker: never asked
    monkeypatch.setattr(massive, "ticker_overview", raiser("network"))
    assert desk._unknown_ticker("ZZZZQ") is False          # an outage is not "no such ticker"
    monkeypatch.setattr(massive, "ticker_overview", lambda t: {"name": "Real Co"})
    assert desk._unknown_ticker("REAL") is False
    assert not any(ch.isdigit() for ch in desk.NOTICE_UNKNOWN_TICKER)
