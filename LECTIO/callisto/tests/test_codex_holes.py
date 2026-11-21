"""Codex council review findings 2-4 (scratchpad codex-council-review.md)."""
import pytest

from backend.gate import final_check


def check(answer, packs=()):
    return final_check("AAPL", {"status": "ANSWERED", "answer": answer, "claims": []}, list(packs), [])


def close_pack():
    # Synthetic market pack: last trading day Nov 20, but this close fact is the Nov 19 close.
    return {"agent": "market", "status": "ok", "as_of": "2026-11-20", "exclude": [], "allow_dates": ["2026-11-19", "2026-11-20"],
            "facts": {"px_close_prior": {"label": "Prior close", "value": 90.0, "kind": "usd_per_share",
                                         "source": "synthetic", "as_of": "2026-11-19"}}}


@pytest.mark.parametrize("answer", [
    "Revenue rose 15.1% in fiscal 2025.",
    "Diluted EPS was − $8.98.",
    "Diluted EPS was - $8.98.",
    "Diluted EPS was —$8.98.",
])
def test_cut(answer):
    assert answer not in check(answer)["answer"]


def test_close_wrong_date_cut():
    a = "The stock closed at $90 on Nov 20."
    assert a not in check(a, [close_pack()])["answer"]


def test_close_right_date_passes():
    a = "The stock closed at $90 on Nov 19."
    assert a in check(a, [close_pack()])["answer"]


@pytest.mark.parametrize("answer", [
    "Revenue rose 15.1% to $478.8 billion in fiscal 2026.",
    "Revenue rose 15.1% in fiscal 2026.",
    "Diluted EPS rose to $8.98 from $7.46.",
])
def test_still_passes(answer):
    assert answer in check(answer)["answer"]
