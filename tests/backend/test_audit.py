import pytest

from backend.ledger import Fact, Ledger, Source
from backend.verify import audit


def _ledger():
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", "https://www.sec.gov/Archives/edgar/data/320193/a", "10-K 2024", "2024-11-01"))
    lg.add_fact(Fact("revenue", "FY2024", 391035000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("revenue", "FY2023", 383285000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("revenue_growth", "FY2024", None, "ratio", inputs=(("revenue", "FY2024"), ("revenue", "FY2023")),
                     formula="revenue / prior-year revenue - 1", note="n/a"))
    return lg


def test_valid_token_kept_with_anchor():
    lg = _ledger()
    out, held = audit.apply("Revenue in fiscal 2024 was [[F:revenue|FY2024]], per Form 10-K and Q3 notes.", lg)
    assert 'class="src"' in out and "https://www.sec.gov" in out and out.startswith("<p>")
    assert held == []


@pytest.mark.parametrize("bad", ["Revenue was [[F:revenue|FY2020]].", "Growth was [[F:revenue_growth|FY2024]].",
                                 "Revenue was 391 billion.", "Margin was 25%.", "Revenue was [[F:revenue|FY2024]] or 12."])
def test_withheld(bad):
    out, held = audit.apply(bad, _ledger())
    assert out == "" and len(held) == 1


@pytest.mark.parametrize("word", ["buy", "sell", "should", "recommend", "undervalued", "overvalued", "upside",
                                  "downside target", "price target", "target price", "cheap", "expensive",
                                  "attractive", "opportunity", "worth considering", "bullish", "bearish",
                                  "outperform", "underperform", "hold the stock"])
def test_advice_withheld(word):
    out, held = audit.apply(f"Revenue was [[F:revenue|FY2024]]. Investors {word} here.", _ledger())
    assert "src" in out and len(held) == 1 and word.split()[0] in held[0]


def test_escape_and_placeholder_shown_as_figure():
    lg = _ledger()
    out, held = audit.apply("<script>alert(1)</script> text. Revenue was [[F:revenue|FY2024]] or 7.\n\nPlain <b>words</b>.", lg)
    assert "<script" not in out and "&lt;b&gt;" in out and out.count("<p>") == 1
    assert any("[figure]" in h and "[[" not in h for h in held)
    assert audit.find_placeholders("a [[F:revenue|FY2024]] b [[F:cash|2024-09-28]]") == [("revenue", "FY2024"), ("cash", "2024-09-28")]


def test_a_company_name_with_inc_does_not_cut_the_sentence():
    lg = _ledger()
    text = "In fiscal 2024, Orchard Devices Inc. reported revenue of [[F:revenue|FY2024]]. It was higher."
    out, held = audit.apply(text, lg)
    assert "Orchard Devices Inc. reported revenue of" in out      # one sentence, kept whole
    assert held == []
    # and when that one sentence breaks the rule, all of it goes: no orphaned second half
    out, held = audit.apply("Around 5 analysts say Orchard Devices Inc. reported revenue of [[F:revenue|FY2024]].", lg)
    assert out == "" and len(held) == 1 and "reported revenue of [figure]" in held[0]


def test_the_ledgers_own_dates_are_not_invented_figures():
    lg = _ledger()
    lg.add_fact(Fact("total_assets", "2024-09-28", 364980000000, "USD", source_ids=("S1",)))
    lg.set_period_end("FY2024", "2024-09-28")
    for written in ("September 28, 2024", "28 Sep 2024", "Sept. 28, 2024", "2024-09-28"):
        out, held = audit.apply(f"As of {written}, total assets were [[F:total_assets|2024-09-28]].", lg)
        assert held == [] and "total assets were" in out, written
    # a date the ledger does not hold is still a typed figure
    out, held = audit.apply("As of March 31, 2024, total assets were [[F:total_assets|2024-09-28]].", lg)
    assert out == "" and len(held) == 1



# ---- 2026-11-22 bug-hunt round ---------------------------------------------------------------
@pytest.mark.parametrize("raw, shown", [
    ("Net margin rose to [[F:net_margin|FY2025]] from [[F:net_margin|FY2024",
     "Net margin rose to [figure] from [figure, cut off]"),
    ("...from [[F:eps_basic|FY2", "...from [figure, cut off]"),
    ("compared with [[F:operating", "compared with [figure, cut off]"),
    ("Revenue [F:revenue|FY2024] and [[F:Revenue|FY2024]] and F:revenue|FY2024]] here",
     "Revenue [figure] and [figure] and [figure] here"),
    ("Revenue was [[F:revenue|FY2024] in total", "Revenue was [figure, cut off] in total"),
    ("In fiscal 2025, cash con", "In fiscal 2025, cash con"),
])
def test_readable_never_shows_placeholder_syntax(raw, shown):
    out = audit.readable(raw)
    assert out == shown
    assert "[[" not in out and "]]" not in out and "F:" not in out


@pytest.mark.parametrize("broken", [
    "Net margin rose to [[F:revenue|FY2024]] from [[F:revenue|FY2023",
    "Revenue was [F:revenue|FY2024].",
    "Revenue was F:revenue|FY2024]].",
    "Revenue was [[F:revenue|FY2024].",
    "Revenue was [[F:Revenue|FY2024]].",
])
def test_a_broken_or_unclosed_placeholder_is_withheld_readably(broken):
    out, held = audit.apply(broken, _ledger())
    assert out == "" and len(held) == 1
    assert "[[" not in held[0] and "]]" not in held[0] and "F:" not in held[0]
    assert "[figure" in held[0]
