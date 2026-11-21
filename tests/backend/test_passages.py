from pathlib import Path

from backend.filings import passages
from backend.filings.passages import Passage, find_span, risk_passages, search, split_items

FIXTURE = Path(__file__).parent / "fixtures" / "filing_10k_sample.txt"
TEXT = FIXTURE.read_text(encoding="utf-8")

RISK_HEADINGS = [
    "We depend on a small number of contract manufacturers, and a disruption at any of them could "
    "delay shipments of our instruments.",
    "Demand for our instruments depends on the capital budgets of research laboratories, which can "
    "be reduced or delayed with little notice.",
    "Competition from larger companies with broader product lines could reduce our sales and margins.",
    "A breach of our information systems, or those of our vendors, could disrupt our operations and "
    "expose us to liability.",
    "If we fail to protect our intellectual property, competitors may copy our designs.",
    "Changes in trade policy, including tariffs on imported components, could increase our costs.",
    "We are subject to environmental, export control and anti-corruption laws, and a violation could "
    "result in penalties.",
    "Our quarterly results may fluctuate, and the market price of our common stock may be volatile.",
]


def test_split_items_finds_the_five_items_past_the_table_of_contents():
    items = split_items(TEXT)
    assert list(items) == ["1", "1A", "7", "7A", "8"]
    assert items["1"].startswith("Calder Ridge Instruments, Inc. designs and sells")
    # Item 1A is the body, not the contents line "Item 1A. Risk Factors 5"
    assert items["1A"].startswith("Investing in our common stock involves risk.")
    assert "Two contract manufacturers assembled substantially all of our instruments" in items["1A"]
    assert "Item 1B" not in items["1A"] and "Unresolved Staff Comments" not in items["1A"]
    assert items["1A"].rstrip().endswith("stockholders could lose part of their investment.")
    assert items["7"].startswith("The following discussion should be read together")
    assert "Item 7A" not in items["7"]
    assert items["7A"].startswith("We are exposed to changes in foreign currency exchange rates")
    assert items["8"].startswith("The consolidated financial statements")
    assert "Changes in and Disagreements" not in items["8"]
    for body in items.values():
        assert body in TEXT


def test_split_items_variants_and_missing_items():
    text = (
        "Contents\n\nITEM 1A.\n\nRisk Factors\n\n12\n\nItem 7 — MD&A\n\n20\n\n"
        "ITEM 1A.\n\nRISK FACTORS\n\nWe face several risks that are described in the paragraphs of this "
        "section, and each of them could harm our business.\n\n"
        "item 7 — Management's Discussion and Analysis\n\nRevenue was discussed with the board in detail "
        "and the discussion is summarised here for readers.\n"
    )
    items = split_items(text)
    assert set(items) == {"1A", "7"}                       # no Item 1, 7A or 8: simply absent
    assert items["1A"].startswith("We face several risks")
    assert items["7"].startswith("Revenue was discussed")
    assert split_items("") == {}
    assert split_items("A letter with no items at all.") == {}


def test_split_items_twenty_f():
    text = (
        "Item 3. Key Information\n\nA. [Reserved]\n\nB. Capitalization and Indebtedness\n\nNot applicable.\n\n"
        "D. Risk Factors\n\nOur operations are exposed to currency movements that could reduce our "
        "reported results in the currency of our financial statements.\n\n"
        "Item 4. Information on the Company\n\nWe make industrial pumps in several countries and sell them "
        "to utilities and to builders of treatment plants.\n\n"
        "Item 5. Operating and Financial Review and Prospects\n\nSales rose because demand from utilities "
        "recovered during the year, as described below.\n\n"
        "Item 6. Directors, Senior Management and Employees\n\nOur board has nine members.\n"
    )
    items = split_items(text)
    assert items["1A"].startswith("Our operations are exposed to currency movements")
    assert "Capitalization" not in items["1A"]
    assert items["1"].startswith("We make industrial pumps")
    assert items["7"].startswith("Sales rose because demand")
    assert "Our board" not in items["7"]


def test_risk_passages_one_per_heading_with_stable_ids_and_offsets():
    found = risk_passages(TEXT)
    assert [p.heading for p in found] == RISK_HEADINGS
    assert [p.id for p in found] == [f"P{i}" for i in range(1, len(RISK_HEADINGS) + 1)]
    assert all(p.item == "1A" for p in found)
    for p in found:
        assert TEXT[p.start:p.end] == p.text
        assert p.text.startswith(p.heading)
        assert len(p.text) <= passages.PASSAGE_CHAR_CAP
        assert len(p.text) > len(p.heading)                 # the heading has its paragraphs
    # group captions, the summary list and the preamble are not passages and not bodies
    joined = "\n".join(p.text for p in found)
    for absent in ("Risks Related to", "General Risk Factors", "Summary of Risk Factors",
                   "• We depend", "Investing in our common stock"):
        assert absent not in joined
    # a page break inside a risk does not cut it
    assert "We maintain security controls and insurance" in found[3].text
    assert risk_passages(TEXT) == found                     # stable across runs
    assert [p.id for p in risk_passages(TEXT, max_passages=3)] == ["P1", "P2", "P3"]


def test_risk_passages_trims_long_passages_and_handles_stubs():
    long_body = " ".join(["Our suppliers may fail to deliver components on time and we may lose orders."] * 40)
    text = ("ITEM 1A. RISK FACTORS\n\nWe depend on suppliers for our components.\n\n" + long_body +
            "\n\nItem 1B. Unresolved Staff Comments\n\nNone.\n")
    (p,) = risk_passages(text)
    assert len(p.text) <= passages.PASSAGE_CHAR_CAP and p.text.endswith(".")
    assert text[p.start:p.end] == p.text
    stub = ("Item 1A. Risk Factors\n\nThere have been no material changes to the risk factors disclosed in "
            "our Annual Report on Form 10-K.\n\nItem 2. Unregistered Sales\n\nNone.\n")
    assert risk_passages(stub) == []
    assert risk_passages("") == []
    assert risk_passages("Item 1. Business\n\nWe make things and sell them to customers.\n") == []


def test_search_keyword_scoring_is_deterministic():
    found = risk_passages(TEXT)
    hits = search(found, "tariffs on imported components")
    assert hits[0].heading.startswith("Changes in trade policy")
    assert search(found, "ransomware breach")[0].heading.startswith("A breach of our information systems")
    assert search(found, "the and of") == []
    assert search(found, "zebra") == []
    assert len(search(found, "our", k=2)) == 0              # a stop word alone scores nothing
    assert search(found, "customers", k=3) == search(found, "customers", k=3)
    assert len(search(found, "customers", k=3)) == 3


def test_find_span_tolerates_curly_quotes_dashes_and_spaces():
    text = "The board’s view — stated  twice — is that “certified” parts\nmatter."
    span = find_span(text, "board's view - stated twice - is that \"certified\" parts matter.")
    assert span is not None
    assert text[span[0]:span[1]] == "board’s view — stated  twice — is that “certified” parts\nmatter."
    assert find_span(text, "  is   that ") == (text.index("is that"), text.index("is that") + len("is that"))
    assert find_span(text, "The board thinks certified parts matter.") is None   # a paraphrase
    assert find_span(text, "") is None and find_span("", "x") is None
    p = risk_passages(TEXT)[3]
    quoted = "competitor's \"certified\" instruments"
    s, e = find_span(p.text, quoted)
    assert p.text[s:e] == "competitor’s “certified” instruments"
    assert isinstance(p, Passage)


# the layouts of real filings: a running "PART I / Item 1A" header on every page (MSFT), a running
# footer ("Example Corp 14", BAC), bullet signs alone on their line, captions in capitals, a risk
# whose caption shares its paragraph (MSFT), a first paragraph shorter than its heading (LLY), a
# "Summary" block with definitions (JPM) and a sentence cut by a page break
PAGED = """Table of Contents
Item 1. Business 3
Item 1A. Risk Factors 9
Item 1B. Unresolved Staff Comments 30

PART I
Item 1

ITEM 1. BUSINESS

We make laboratory instruments and sell them to universities and to industrial customers.

PART I
Item 1A

ITEM 1A. RISK FACTORS

Our business is subject to the risks described below, which could adversely affect our results.

Summary

The principal risk factors include:

“applicable law” means the laws and rules that apply to our businesses in each country.

STRATEGIC AND COMPETITIVE RISKS

We face intense competition across our markets, which could adversely affect our results of operations.

Competition in instruments

Our competitors range from large diversified companies to small specialised firms, and some of them offer laboratories complete sets of instruments under one contract at prices we may not be able to match.

•

Some competitors bundle service and software with their instruments.

•

Others give their instruments away to win long service contracts, which reduces the prices we can charge.

Example Corp 14

PART I
Item 1A

Laboratory budgets can be reduced with little notice, which could lower our sales.

Budgets are cut often.

Most of our instruments are bought out of capital budgets that universities and agencies set each year, and those budgets depend on public funding decisions that can change quickly and without warning to us or to our customers.

RISKS RELATING TO OUR OPERATIONS

We depend on two contract manufacturers. A disruption at either of them could delay our shipments for months, because qualifying a replacement takes time, and our customers may cancel orders while we wait for new capacity to be ready.

Our insurance may not cover every loss arising from a disruption at one of our manufacturers or at

PART I
Item 1A

our own sites, and an uninsured loss could reduce our earnings in the period in which it occurs.

PART I
Item 1B, 1C

ITEM 1B. UNRESOLVED STAFF COMMENTS

None.
"""


def test_running_page_headers_do_not_cut_an_item_into_pages():
    items = split_items(PAGED)
    assert items["1"] == "We make laboratory instruments and sell them to universities and to industrial customers."
    assert items["1A"].startswith("Our business is subject to the risks described below")
    assert items["1A"].endswith("in the period in which it occurs.")   # past three page headers


def test_risk_passages_on_real_filing_layouts():
    found = risk_passages(PAGED)
    assert [p.heading for p in found] == [
        "We face intense competition across our markets, which could adversely affect our results of operations.",
        "Laboratory budgets can be reduced with little notice, which could lower our sales.",
        "We depend on two contract manufacturers.",                 # a caption in its own paragraph
    ]
    for p in found:
        assert PAGED[p.start:p.end] == p.text and p.text.startswith(p.heading)
    first, budgets, makers = found
    # the sub-caption and the bullet items stay inside the risk; the footer does not end it
    assert "Competition in instruments" in first.text and "Others give their instruments away" in first.text
    assert "Summary" not in first.text and "applicable law" not in first.text
    # a first paragraph shorter than its heading is still its body
    assert "Budgets are cut often." in budgets.text and "public funding decisions" in budgets.text
    # a sentence cut by a page header is not a heading of its own
    assert makers.text.endswith("in the period in which it occurs.")
    assert passages.is_furniture("Example Corp 14") and passages.is_furniture("PART I")
    assert passages.is_furniture("Item 1A") and passages.is_furniture("•")
    assert not passages.is_furniture("Competition in instruments")


def test_a_long_passage_is_not_cut_after_an_abbreviation():
    # 18 sentences put "U.S." inside the cap and the end of its sentence past it (where a cut at the
    # last ". " used to stop)
    filler = " ".join(["Our suppliers may fail to deliver components on time and we may lose orders."] * 18)
    text = ("ITEM 1A. RISK FACTORS\n\nWe depend on suppliers for our components.\n\n" + filler +
            " Tariffs imposed by the U.S. or other governments could raise our costs and reduce our margins."
            " " + filler + "\n\nItem 1B. Unresolved Staff Comments\n\nNone.\n")
    (p,) = risk_passages(text)
    assert len(p.text) <= passages.PASSAGE_CHAR_CAP
    assert not p.text.endswith("U.S.")                      # "U.S." does not end a sentence
    assert p.text.endswith("we may lose orders.")
