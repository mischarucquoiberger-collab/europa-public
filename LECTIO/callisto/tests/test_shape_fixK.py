from backend.shape import layout, plain

NOTE = "Market data: Massive, end-of-day, as of 2026-11-20."
WAY1 = ("How to judge the price: compare the P/E ratio with the company's own past levels. A high P/E means "
        "investors are paying for future growth.")
WAY2 = "How to gauge risk: look at the gap between the yearly high and low. No single stock is safe."
BODY = [
    "Apple Inc. closed at $420.69 on 2026-11-20.",
    "The stock rose 3.5% over one day.",
    "Revenue was $20.5 billion in fiscal 2026.",
    "The 52-week range ran from $150.25 to $430.10.",
    "Net income was 20.",
]
SAMPLES = [
    " ".join(BODY + ["What it means: the price moved a lot.", "Deeper read: growth is steady.", WAY1, NOTE]),
    " ".join(BODY[:4] + [WAY2, NOTE]),
    " ".join(BODY[:3] + ["What it means: sales are large.", "It grew."] + [NOTE]),
    "Microsoft Corp. gained 1.2% over one day. It traded near $500.10. Volume was high. " + WAY1,
    "Tesla, Inc. fell 4.1% over one day. Shares ended at $250.00. The range was wide. Bear case: margins shrink. Bull case: sales grow. " + NOTE,
    "Nvidia rose. It is large. " + NOTE,
    " ".join(BODY) + " " + WAY1 + " " + WAY2 + " " + NOTE,
    "The U.S. market opened higher on 2026-11-20. The index rose 0.8% over one day. Tech led gains vs. utilities. Oil fell. " + NOTE,
]


def test_words_unchanged():
    for x in SAMPLES:
        assert plain(layout(x)) == " ".join(x.split())


def test_idempotent():
    for x in SAMPLES:
        assert layout(layout(x)) == layout(x)


def test_existing_newlines_untouched():
    t = "Lead line.\n• one\n• two"
    assert layout(t) == t


def test_short_reply_stays_paragraph():
    t = "Apple rose 2.0% over one day. It closed at $200.00."
    assert layout(t) == t


def test_notes_on_last_line():
    out = layout(SAMPLES[0]).split("\n")
    assert out[-1] == NOTE


def test_ways_on_one_line():
    out = layout(SAMPLES[6]).split("\n")
    assert out[-2] == WAY1 + " " + WAY2
    assert out[-1] == NOTE


def test_labels_start_own_line():
    out = layout(SAMPLES[0]).split("\n")
    assert any(l.startswith("What it means:") for l in out)
    assert any(l.startswith("Deeper read:") for l in out)


def test_label_absorbs_following_body():
    out = layout(SAMPLES[2]).split("\n")
    assert "What it means: sales are large. It grew." in out


def test_lead_and_bullets():
    out = layout(SAMPLES[1]).split("\n")
    assert not out[0].startswith("•")
    assert out[1].startswith("• ")


def test_decimal_and_abbrev_not_split():
    out = layout(SAMPLES[0]).split("\n")
    assert out[0] == BODY[0]
    assert "• " + BODY[2] in out
    assert layout(SAMPLES[3]).split("\n")[0].startswith("Microsoft Corp. gained")


def test_trailing_number_period_not_split():
    out = layout(" ".join(BODY)).split("\n")
    assert out[-1] == "• Net income was 20."


def test_short_with_note_separate_lines():
    out = layout(SAMPLES[5]).split("\n")
    assert out == ["Nvidia rose. It is large.", NOTE]


def test_empty_and_none():
    assert layout("") == ""
    assert layout(None) == ""
    assert plain(None) == ""
    assert plain("") == ""
