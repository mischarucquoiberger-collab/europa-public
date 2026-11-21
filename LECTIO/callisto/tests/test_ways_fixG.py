"""The fixed "a way to decide" lines (Jayden 2026-11-21): no digits, no buy/sell call, picked by question topic."""
import re

from backend import desk


def test_way_texts_hold_no_digits_and_no_advice():
    for _k, _rx, text in desk.WAYS:
        assert not re.search(r"\d", text)
        assert not re.search(r"\byou should (buy|sell)\b|\bI recommend\b", text, re.I)
    assert not re.search(r"\d", desk.WAY_FILINGS_OTHER)


def test_ways_pick_by_topic():
    assert desk._ways("Is Apple stock overvalued or expensive?")[0].startswith("How to judge the price")
    assert desk._ways("What do analysts think of Nvidia stock?")[0].startswith("Analyst ratings")
    assert desk._ways("Is Apple a safe stock?")[0].startswith("How to gauge risk")
    assert desk._ways("Why is Nvidia stock down today?")[0].startswith("Price data shows")
    assert desk._ways("When does Apple report earnings next?")[0].startswith("Callisto's data does not include")
    assert desk._ways("Is Apple a good long-term investment?")[0].startswith("For a long-term view")
    assert desk._ways("Should I sell my Apple shares?")[0].startswith("If you already own")
    assert desk._ways("What was Apple's revenue in fiscal 2026?") == []
    assert len(desk._ways("Is it safe, overvalued, and what do analysts think long-term?")) == 2
