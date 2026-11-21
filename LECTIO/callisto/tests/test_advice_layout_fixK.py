"""Advice layout fix K (2026-11-21): news block stays on-topic and short; source notice sits on its own line."""
from backend import desk, summary


def _item(title, mood="positive", ticker="AAPL"):
    return {"title": title, "publisher": {"name": "Wire"}, "published_utc": "2026-11-20T10:00:00Z",
            "insights": [{"ticker": ticker, "sentiment": mood}]}


def _feed(monkeypatch, items):
    monkeypatch.setattr(summary.massive, "news", lambda t, n=50: items)


def test_off_company_headline_dropped(monkeypatch):
    _feed(monkeypatch, [_item("Amazon expands same-day delivery"), _item("Apple ships new laptops")])
    out = summary.news_lines("AAPL", "Apple")
    assert len(out) == 1 and out[0].startswith("Apple ships new laptops")


def test_pitch_headline_dropped(monkeypatch):
    _feed(monkeypatch, [_item("Better buy: Apple vs. Microsoft"), _item("3 reasons Apple could soar"),
                        _item("Apple stock prediction for next year"), _item("AAPL opens a new store")])
    out = summary.news_lines("AAPL", "Apple")
    assert len(out) == 1 and out[0].startswith("AAPL opens a new store")


def test_long_headline_shortened_only_when_no_short_one(monkeypatch):
    long_t = "Apple " + " ".join(f"word{i}" for i in range(25))
    _feed(monkeypatch, [_item(long_t)])
    out = summary.news_lines("AAPL", "Apple")
    assert len(out) == 1
    head = out[0].split(" (")[0]
    assert head.endswith("…") and len(head.split()) == 16
    _feed(monkeypatch, [_item(long_t), _item("Apple ships new laptops")])
    assert summary.news_lines("AAPL", "Apple")[0].startswith("Apple ships new laptops")


def test_source_notice_on_its_own_last_line():
    brief = ("Strengths: sales rose. Watch-outs: buybacks fell. What it means: steady year. "
             "Deeper read: the risk factors. Market data: Massive, end-of-day, as of a date.")
    out = desk._short_advice("Lead, in short:", ["a", "b"], brief, [], [desk.ADVICE_WEIGH]).split("\n")
    assert out[-1].startswith("Market data: Massive")
    assert any(l.startswith("Deeper read:") and "Market data" not in l for l in out)
    assert any(l.startswith("What it means:") for l in out)
    assert desk.ADVICE_WEIGH in out


def test_fixed_texts_short_and_free_of_demo_words():
    assert "The buy or sell decision is yours." in desk.ADVICE_WEIGH and len(desk.ADVICE_WEIGH.split()) <= 24
    assert "in this demo" not in desk.ADVICE_MKT_NOTE
    assert summary.NEWS_HEAD == "In the news (headlines from Massive, not checked by Callisto):"
