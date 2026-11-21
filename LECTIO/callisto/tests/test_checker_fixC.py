"""Fix C: a real number attached to the wrong thing must not be shown; honest refusals must pass whole."""
import pytest
from backend.gate import final_check


def shown_whole(text):
    r = final_check("AAPL", {"status": "ANSWERED", "answer": text, "claims": []}, [])
    return r["status"] == "ANSWERED" and r["answer"].strip() == text.strip()


@pytest.mark.parametrize("text", [
    "Apple lost $132.2 billion in fiscal 2026.",
    "Net income was a negative $132.2 billion in fiscal 2026.",
    "Operating margin was 48.8% in fiscal 2026.",
    "Gross margin percentage rose 19.7% in fiscal 2026.",
    "Apple paid a dividend of $8.98 per share in fiscal 2026.",
    "iPhone revenue was $478.8 billion in fiscal 2026.",
    "Microsoft revenue was $478.8 billion in fiscal 2026.",
    "Revenue in Q4 of fiscal 2026 was $478.8 billion.",
    "Apple total debt was $86.4 billion.",
])
def test_wrong_binding_not_shown_whole(text):
    assert not shown_whole(text)


@pytest.mark.parametrize("text", [
    "The data here doesn't cover iPhone revenue, since the sheets only list total net sales. Total net sales in fiscal 2026 were $478.8 billion.",
    "Apple made a profit in fiscal 2026. Net income was $132.2 billion.",
    "That's not right: Apple made a profit, not a loss. Net income was $132.2 billion in fiscal 2026.",
    "Gross margin was 48.8% in fiscal 2026, up from 46.9% in fiscal 2025.",
    "Operating income was $158.1 billion in fiscal 2026.",
    "Share repurchases were $86.4 billion, versus $90.7 billion in fiscal 2025.",
    "The sheets don't list iPhone revenue, but total net sales were $478.8 billion in fiscal 2026.",
    "Gross margin was $233.6 billion, and the gross margin percentage was 48.8% in fiscal 2026.",
    "Gross margin percentage rose 1.9 percentage points in fiscal 2026.",
])
def test_true_sentence_passes(text):
    assert shown_whole(text)
