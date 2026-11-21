"""Fix E: true market sentences must pass whole; false ones must not survive. Market pack is SYNTHETIC."""
import os
from datetime import date, timedelta
from math import sin

import pytest

os.environ.setdefault("PYTEST_CURRENT_TEST", "fixE")
from backend import specialists as sp  # noqa: E402
from backend.gate import final_check  # noqa: E402


def _bars():  # SYNTHETIC end-of-day bars
    out, d, i = [], date(2025, 10, 1), 0
    while d <= date(2026, 11, 20):
        if d.weekday() < 5:
            i += 1
            px = 470 + 40 * sin(i / 17) + ((i * 37) % 11 - 5)
            out.append({"date": d.isoformat(), "o": px, "h": px * 1.01, "l": px * 0.99, "c": px, "v": 25_000_000 + i})
        d += timedelta(days=1)
    out[-2]["c"], out[-1].update(c=484.52, h=490.10, l=480.33, o=495.20)
    out[-2]["c"] = 498.30
    return out


_FACTS, _AS_OF = sp._price_facts(_bars())
PACK = {"agent": "market", "status": "ok", "as_of": _AS_OF, "allow_text": ["52-week"], "allow_dates": [_AS_OF],
        "facts": _FACTS}


def _shown_whole(t, ticker="MSFT", packs=None):
    r = final_check(ticker, {"status": "ANSWERED", "answer": t, "claims": []}, [PACK] if packs is None else packs)
    return r["status"] == "ANSWERED" and r["answer"].strip() == t.strip()


def test_pack_values():
    f = {k: v["display"] for k, v in _FACTS.items()}
    assert f["px_close_last"] == "$484.52" and f["px_close_prior"] == "$498.30" and f["ret_1d_pct"] == "-2.8%"
    assert f["ret_1w_pct"] == "+12.4%" and f["ret_1y_pct"] == "-3.7%" and f["px_52w_high"] == "$520.03"


TRUE = [
    "Microsoft closed at $484.52 on 2026-11-20, down 2.8% from $498.30 the trading day before.",
    "Microsoft closed at $484.52 on 2026-11-20, down from $498.30 the day before.",
    "Microsoft closed at $484.52 on 2026-11-20, down 2.8% on the day.",
    "Microsoft closed at $484.52 on 2026-11-20 (down 2.8%).",
    "Microsoft closed at $484.52 on 2026-11-20, below the $498.30 close the day before.",
    "The previous close was $498.30, and the stock closed at $484.52 on 2026-11-20.",
    "Microsoft's closing price, the last trade price of the day, was $484.52 on 2026-11-20, down from $498.30 the trading day before.",
    "Price return, the percent change in share price, was -2.8% over the last trading day and +12.4% over the past week.",
    "It was +10.6% since the start of the year and -3.7% over the past year.",
    "The 52-week high, the highest price in a year, was $520.03, and the 52-week low, the lowest price in a year, was $420.75.",
    "Deeper read: the one-month return of +7.5% is large next to the one-year return of -3.7%.",
    "The stock's lowest price on 2026-11-20 was $480.33 and its highest was $490.10.",
    "Microsoft is down 2.8% today from $498.30, a close of $484.52.",
    "Over the past 52 weeks the stock has traded between $420.75 and $520.03.",
    "Volume, the number of shares traded, was 25.0 million shares on 2026-11-20.",
    "The stock opened at $495.20 on 2026-11-20 and closed at $484.52.",
]
FALSE = [
    "Microsoft returned -3.7% over the past week.",
    "Microsoft closed at $498.30 on 2026-11-20.",
    "The prior close was $484.52.",
    "Microsoft was up 2.8% on the day.",
    "The 52-week low was $520.03.",
    "The highest price in a year was $490.10.",
    "Microsoft closed at $490.00 on 2026-11-20.",
    "The stock returned +12.4% over the past year.",
    "The stock rose 3.7% over the past year.",
    "Over the last two years the stock returned -3.7%.",
    "A month ago the stock closed at $484.52.",
    "Microsoft closed at $484.52, down 12.4%.",
]


@pytest.mark.parametrize("t", TRUE)
def test_true_market_sentence_shown_whole(t):
    assert _shown_whole(t), t


@pytest.mark.parametrize("t", FALSE)
def test_false_market_sentence_cut(t):
    assert not _shown_whole(t), t


def test_single_quoted_fake_quote_cut():
    assert not _shown_whole("Apple 10-K says 'we expect revenue to decline sharply next year'.", "AAPL", [])


def test_apostrophes_are_not_quotes():
    assert _shown_whole("Apple's net income was $132.2 billion, and the company's results were strong in fiscal 2026.", "AAPL", [])


@pytest.mark.parametrize("t", ["Apple's revenue was $62.7 billion in fiscal 2026.", "Apple's net sales were $62.7 billion."])
def test_change_amount_as_level_cut(t):
    assert not _shown_whole(t, "AAPL", [])


@pytest.mark.parametrize("t", [
    "Revenue rose $62.7 billion to $478.8 billion in fiscal 2026.",
    "That is $62.7 billion more than the year before.",
    "Revenue increased by $62.7 billion in fiscal 2026.",
])
def test_change_amount_as_change_passes(t):
    assert _shown_whole(t, "AAPL", [])
