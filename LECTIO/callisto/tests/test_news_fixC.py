"""Fix C: news about another company is not answered with Apple headlines; the headline-only answer names its dates.
All offline: Massive is a mock transport and the desk uses fake agents."""
import pytest

from backend import desk, massive, specialists as sp
from tests.test_desk import Fakes, pack
from tests.test_specialists import NEWS, _iso, _router  # noqa: F401  (_iso is an autouse fixture)

OTHER = "Callisto's headlines follow the selected ticker (AAPL), so none are listed for another company."


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")


def test_other_company_gets_no_headlines(monkeypatch):
    _router(news_rows=NEWS)
    for q in ["What is the latest news on Samsung?", "Any news about Tesla today?", "nvidia headlines"]:
        p = sp.news({"ticker": "AAPL", "question": q})
        assert p["status"] == "unavailable" and p["items"] == [], q
        assert p["reason"] == sp.OTHER_COMPANY_REASON


def test_both_companies_keeps_apple_headlines():
    _router(news_rows=NEWS)
    p = sp.news({"ticker": "AAPL", "question": "How does Apple compare to Samsung in the news?"})
    assert p["status"] == "ok" and p["items"]
    p = sp.news({"ticker": "AAPL", "question": "AAPL vs Microsoft news"})
    assert p["status"] == "ok"


def test_plain_apple_question_unchanged():
    _router(news_rows=NEWS)
    assert sp.news({"ticker": "AAPL", "question": "latest news on Apple"})["status"] == "ok"
    assert sp.news({"ticker": "AAPL", "question": ""})["status"] == "ok"


def test_desk_says_it_honestly():
    f = Fakes(route={"specialists": ["news"], "advice": False, "reason": "", "model": "m", "fallback": False},
              packs={"news": pack("news", "unavailable", reason=sp.OTHER_COMPANY_REASON)})
    out = desk.answer("AAPL", "What is the latest news on Samsung?", deps=f.deps)
    assert OTHER in out["answer"] and "unavailable right now" not in out["answer"]
    assert out["news"] == []


def _items(dates):
    return [{"id": f"n{i}", "title": f"Title {i}", "publisher": "Pub", "published_utc": d,
             "url": f"https://example.com/{i}"} for i, d in enumerate(dates)]


def test_headline_answer_names_newest_date():
    f = Fakes(route={"specialists": ["news"], "advice": False, "reason": "", "model": "m", "fallback": False},
              packs={"news": pack("news", items=_items(["2026-11-17T10:00:00Z", "2026-11-15T10:00:00Z"]))})
    out = desk.answer("AAPL", "Any Apple news today?", deps=f.deps)
    assert "Callisto has not verified them." in out["answer"]
    assert "The newest one is dated 2026-11-17." in out["answer"]
    assert "Title 0" not in out["answer"]
    assert len(out["news"]) == 2


def test_headline_answer_without_dates_unchanged():
    f = Fakes(route={"specialists": ["news"], "advice": False, "reason": "", "model": "m", "fallback": False},
              packs={"news": pack("news", items=_items(["", ""]))})
    out = desk.answer("AAPL", "Apple news", deps=f.deps)
    assert out["answer"].endswith("Callisto has not verified them.") and "dated" not in out["answer"]
