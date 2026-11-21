"""Wrong-year and plain-direction sentences must be cut; true ones must pass whole."""
import pytest
from backend.gate import final_check


def run(text):
    return final_check("AAPL", {"status": "ANSWERED", "answer": text, "claims": []}, [])


def shown_whole(text):
    r = run(text)
    return r["status"] == "ANSWERED" and r["answer"].strip() == text.strip()


@pytest.mark.parametrize("text", [
    "Revenue rose 15.1% to $416.2 billion in fiscal 2025.",
    "Revenue was off 15.1% from the year before.",
    "Net income deteriorated 18.0% in fiscal 2026.",
    "Revenue of $478.8 billion in fiscal 2026 was lower than the year before.",
])
def test_false_sentence_not_shown_whole(text):
    assert not shown_whole(text)


def test_lead_year_wrong_number_cut():
    r = run("Fiscal 2026 was a record year. Revenue was $416.2 billion.")
    assert "416.2" not in r["answer"]


@pytest.mark.parametrize("text", [
    "Revenue rose 15.1% to $478.8 billion in fiscal 2026.",
    "Share repurchases fell 4.8% to $86.4 billion.",
    "Net income was $132.2 billion, up from $112.0 billion.",
    "Fiscal 2026 was a strong year. Revenue was $478.8 billion.",
    "It was 48.8% of net sales, compared with 46.9% in fiscal 2025, a change of +1.9 percentage points.",
])
def test_true_sentence_passes(text):
    assert shown_whole(text)


def test_pointing_back_sentence_keeps_the_previous_metric():
    """ "That is up from ..." takes its metric from the sentence before, not from a trailing word like "profit"."""
    from backend.gate import final_check
    good = ("Diluted EPS was $8.98 per share in fiscal 2026. That is up from $7.46 per share in fiscal 2025, "
            "a rise of 20.4%, which means each share earned noticeably more profit than the year before.")
    r = final_check("AAPL", {"status": "ANSWERED", "answer": good, "claims": []}, [])
    assert not r.get("blocked") and "$7.46" in r["answer"] and "20.4%" in r["answer"]
    bad = "Revenue was $478.8 billion in fiscal 2026. That is up from $112.0 billion in fiscal 2025."
    r = final_check("AAPL", {"status": "ANSWERED", "answer": bad, "claims": []}, [])
    assert "$112.0" not in r["answer"]
