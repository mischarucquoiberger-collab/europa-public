import pytest

from backend.naming import display_name


@pytest.mark.parametrize("raw, shown", [
    ("MICROSOFT CORP", "Microsoft Corp."),
    ("AMAZON COM INC", "Amazon.com Inc."),
    ("NVIDIA CORP", "NVIDIA Corp."),
    ("G III APPAREL GROUP LTD /DE/", "G III Apparel Group Ltd."),
    ("BANK OF AMERICA CORP /DE/", "Bank of America Corp."),
    ("JPMORGAN CHASE & CO", "JPMorgan Chase & Co."),
    ("CVS HEALTH CORP", "CVS Health Corp."),
    ("AT&T INC.", "AT&T Inc."),
    ("ELI LILLY & Co", "Eli Lilly & Co."),             # capitals with a mixed-case suffix
    ("ExxonMobil Holdings Corp", "ExxonMobil Holdings Corp"),
    ("Apple Inc.", "Apple Inc."),                      # the company's own spelling is kept
    ("Alphabet Inc.", "Alphabet Inc."),
    ("Duolingo, Inc.", "Duolingo, Inc."),
    ("ASML HOLDING NV", "ASML Holding N.V."),
    ("Rivian Automotive, Inc. / DE", "Rivian Automotive, Inc."),       # a state tag written with a space
    ("COCA COLA CO", "Coca-Cola Co."),
    ("", ""), (None, ""),
])
def test_display_name(raw, shown):
    assert display_name(raw) == shown
