"""Red-team B fixes (test-runs/redteam-B-council.md #1, #3, #4)."""
import pytest

from backend.gate import final_check


def check(answer, packs=()):
    return final_check("AAPL", {"status": "ANSWERED", "answer": answer, "claims": []}, list(packs))


@pytest.mark.parametrize("answer", [
    "Apple revenue saw a 15.1% year-over-year decline in fiscal 2026.",
    "Revenue cratered 15.1% in fiscal 2026.",
    "Revenue showed 15.1%, a plunge, in fiscal 2026.",
    "EPS was $7.46, compared with $8.98 the year before.",
    "Revenue was $416.2 billion, versus $478.8 billion a year earlier.",
    "EPS was $7.46, compared with $8.98 last year.",
])
def test_cut(answer):
    assert answer not in check(answer)["answer"]


def test_level_direction_survives_dispute_on_sister_fact():
    a = "Revenue fell to $478.8 billion in fiscal 2026."
    out = check(a, [{"agent": "council", "status": "unavailable", "exclude": ["revenue_fy2025"]}])
    assert a not in out["answer"]


@pytest.mark.parametrize("answer", [
    "Revenue rose 15.1% to $478.8 billion in fiscal 2026.",
    "Diluted EPS rose to $8.98 from $7.46.",
    "EPS was $8.98, compared with $7.46 the year before.",
])
def test_still_passes(answer):
    assert answer in check(answer)["answer"]
