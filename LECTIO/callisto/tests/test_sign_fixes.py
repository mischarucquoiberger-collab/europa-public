import pytest

from backend.gate import FALLBACK, final_check


def check(answer, packs=()):
    return final_check("AAPL", {"status": "ANSWERED", "answer": answer, "claims": []}, packs)


@pytest.mark.parametrize("answer", [
    "EPS was -$8.98.",
    "EPS was ($8.98).",
    "Apple posted a net loss of $132.2 billion.",
    "Net income fell to $132.2 billion.",
])
def test_contradicted_level_is_cut(answer):
    result = check(answer)
    assert result["answer"] == FALLBACK
    assert result["status"] == "I_DONT_KNOW"
    assert [item["text"] for item in result["blocked"]] == [answer]
    assert [claim["status"] for claim in result["claims"]] == ["MISMATCH"]


@pytest.mark.parametrize("amount, valid", [
    ("$8.98", False),
    ("+$8.98", False),
    ("-$8.98", True),
    ("($8.98)", True),
])
def test_negative_level_requires_negative_amount(amount, valid):
    answer = f"EPS was {amount}."
    pack = {"status": "ok", "facts": {"eps_diluted_fy2026": {
        "label": "Diluted earnings per share, fiscal 2026", "value": -8.98,
        "kind": "usd_per_share", "source": "synthetic test data",
    }}}
    result = check(answer, [pack])
    assert result["answer"] == (answer if valid else FALLBACK)
    assert [claim["status"] for claim in result["claims"]] == ["VERIFIED" if valid else "MISMATCH"]


def test_bad_sign_only_blocks_its_own_sentence():
    result = check("EPS was -$8.98. Diluted EPS was $8.98.")
    assert result["answer"] == "Diluted EPS was $8.98."
    assert [item["text"] for item in result["blocked"]] == ["EPS was -$8.98."]


@pytest.mark.parametrize("answer", [
    "Buybacks fell 4.8% to $86.4 billion.",
    "Diluted EPS rose to $8.98 from $7.46.",
    "Net income rose to $132.2 billion from $112.0 billion.",
    "Revenue was down? no",
])
def test_correct_statements_are_kept(answer):
    result = check(answer)
    assert result["answer"] == answer
    assert result["status"] == "ANSWERED"
    assert result["blocked"] == []
