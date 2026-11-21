"""Gate fix C (2026-11-21): single/double/triple-digit rates verified against facts; change sizes in words cut."""
import pytest

from backend.gate import final_check


def _outcome(text):
    r = final_check("AAPL", {"status": "ANSWERED", "answer": text, "claims": []}, [])
    return "pass" if r["status"] == "ANSWERED" and r["answer"].strip() == text.strip() else "block"


PASS = [
    "Revenue grew at a double-digit rate.",
    "Net sales rose at a double-digit pace in fiscal 2026.",
    "Net income grew at a double-digit rate in fiscal 2026.",
    "Diluted EPS grew at a double-digit rate in fiscal 2026.",
    "R&D spending grew at a double-digit rate in fiscal 2026.",
    "Buybacks fell at a single-digit rate in fiscal 2026.",
    "Cash grew at a single-digit rate in fiscal 2026.",
    "Revenue rose 15.1% to $478.8 billion in fiscal 2026.",
    "Both rose in fiscal 2026.",
    "Apple sold more in both years than analysts might guess.",
    "Net income grew faster than revenue in fiscal 2026.",
    "Gross margin was 48.8% in fiscal 2026, up 1.9 percentage points (the gap between the two years).",
    "Revenue rose in the fourth quarter and in both years.",
]
BLOCK = [
    "Revenue grew at a single-digit rate in fiscal 2026.",
    "Revenue grew at a triple-digit rate in fiscal 2026.",
    "Buybacks grew at a double-digit rate in fiscal 2026.",
    "Buybacks fell at a double-digit rate in fiscal 2026.",
    "Cash grew at a double-digit rate in fiscal 2026.",
    "Revenue fell at a double-digit rate in fiscal 2026.",
    "Apple grew at a double-digit rate.",
    "Revenue grew by a quarter in fiscal 2026.",
    "Revenue grew a third in fiscal 2026.",
    "Revenue quintupled in fiscal 2026.",
    "Revenue doubled in fiscal 2026.",
    "Revenue grew fifteen-percent.",
    "Revenue grew fifteen percent.",
    "Revenue grew five-fold.",
]


@pytest.mark.parametrize("t", PASS)
def test_true_passes(t):
    assert _outcome(t) == "pass"


@pytest.mark.parametrize("t", BLOCK)
def test_false_blocked(t):
    assert _outcome(t) == "block"
