"""Overcut and plain-wording hole fixes from scripts/gate_regressions_B.py (2026-11-21).
Market values are SYNTHETIC (from that script)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gate_regressions_B import GM, MARKET, REV  # noqa: E402

from backend.gate import final_check  # noqa: E402


def _outcome(text, packs=(), claims=()):
    r = final_check("AAPL", {"status": "ANSWERED", "answer": text, "claims": list(claims)}, list(packs))
    if r["status"] == "ANSWERED" and r["answer"].strip() == text.strip():
        return "pass"
    return "block" if r["status"] != "ANSWERED" else "partial"


PASS = [
    ("That is 48.8% of net sales.", [], []),
    ("That is 48.8% of net sales.", [], GM),
    ("It was 48.8% of net sales, compared with 46.9% in fiscal 2025, a change of +1.9 percentage points.", [], GM),
    ("Apple kept 48.8% of each sales dollar after the cost of making its products.", [], GM),
    ("Apple's net sales increased by $62.7 billion between fiscal 2025 and fiscal 2026, rising from $416.2 billion "
     "to $478.8 billion.", [], REV),
    ("Apple's net income increased by $20.2 billion between fiscal 2025 and fiscal 2026, rising from $112.0 billion "
     "to $132.2 billion.", [], []),
    ("Apple closed at $229.87 on 2026-11-20, up from $226.10 the day before.", [MARKET], []),
    ("The last close, on 2026-11-20, was $229.87, up 1.7% on the day.", [MARKET], []),
]

BLOCK = [
    ("Revenue was off 15.1% from the year before.", [], []),
    ("Net income deteriorated 18.0% in fiscal 2026.", [], []),
    ("Revenue of $478.8 billion in fiscal 2026 was lower than the year before.", [], []),
    ("It was 15.1% of net sales.", [], []),
    ("Apple closed at $226.10, down from $229.87 the day before.", [MARKET], []),
]


@pytest.mark.parametrize("text,packs,claims", PASS)
def test_true_sentences_are_kept(text, packs, claims):
    assert _outcome(text, packs, claims) == "pass"


@pytest.mark.parametrize("text,packs,claims", BLOCK)
def test_wrong_sentences_are_not_shown_whole(text, packs, claims):
    assert _outcome(text, packs, claims) != "pass"
