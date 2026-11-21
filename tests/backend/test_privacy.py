import pytest

from backend import privacy


@pytest.mark.parametrize("text, kind", [
    ("my card is 4111 1111 1111 1111, what was revenue?", "a payment card number"),
    ("card 4111-1111-1111-1111", "a payment card number"),
    ("my SSN is 123-45-6789", "a Social Security number"),
    ("my password is Hunter2!x and tell me about Apple", "a password or access code"),
    ("api key: abcd1234efgh", "a password or access code"),
    ("my account number is 12345678901", "a bank account number"),
    ("IBAN DE89 3704 0044 0532 0130 00", "a bank account number"),
    ("email me at jane.doe@example.com", "an email address"),
    ("call +1 212-555-0147", "a phone number"),
    ("(212) 555-0147 is my phone", "a phone number"),
    ("date of birth: 12/03/1988", "a date of birth"),
])
def test_personal_and_account_data_is_found_and_removed(text, kind):
    kinds, cleaned = privacy.scan(text)
    assert kind in kinds
    assert privacy.REMOVED in cleaned
    for secret in ("4111", "6789", "Hunter2", "abcd1234efgh", "12345678901", "DE89", "jane.doe", "555-0147", "1988"):
        if secret in text:
            assert secret not in cleaned


@pytest.mark.parametrize("text", [
    "What was Apple's revenue in fiscal 2024?",
    "Revenue was 391,035 million in 2024 and 383,285 million in 2023, right?",
    "Is 4161610000 the revenue figure?",                         # ten bare digits: a figure, not a phone number
    "Compare 2022-2023 with 2024-2025",
    "What is the P/E at $342.56 on 2026-11-20?",
    "1234 5678 9012 3456 is not a real card",                    # fails the check digit
    "EPS of 6.08 and 6.13; shares 15,116,786,000",
    "How did the pin-compatible chip business do?",
])
def test_ordinary_questions_about_figures_are_left_alone(text):
    assert privacy.scan(text) == ([], text)


def test_the_notice_names_the_kinds_never_the_values_and_empty_input_is_safe():
    kinds, cleaned = privacy.scan("card 4111 1111 1111 1111 and jane@example.com, what was net income?")
    note = privacy.notice(kinds)
    assert kinds == ["a payment card number", "an email address"]
    assert "a payment card number and an email address" in note and "4111" not in note and "jane" not in note
    assert "not used or stored" in note and "removed" in note
    assert privacy.has_question(cleaned) is True
    assert privacy.has_question(privacy.scan("my SSN is 123-45-6789")[1]) is False
    assert privacy.scan("") == ([], "") and privacy.scan(None) == ([], "")
