"""format is the one place a fact becomes text: units, rounding, links, escaping."""
import pytest

from backend import format as fmt
from backend.ledger import Fact, Ledger, LedgerError, Source

K24 = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24.htm",
             title="Form 10-K, filed 2024-11-01", date="2024-11-01")


def _f(value, unit, key="revenue", period="FY2024"):
    return Fact(key=key, period=period, value=value, unit=unit, source_ids=("S1",))


@pytest.mark.parametrize("value,unit,text", [
    (391_035_000_000, "USD", "$391.0 billion"),
    (4_200_000, "USD", "$4.2 million"),
    (950, "USD", "$950"),
    (12_345, "USD", "$12,345"),
    (-1_200_000_000, "USD", "-$1.2 billion"),
    (1_520_000_000_000, "USD", "$1.5 trillion"),
    (999_960_000_000, "USD", "$1.0 trillion"),            # rounding moves up a scale
    (999_999.6, "USD", "$1,000,000"),
    (999_400_000, "USD", "$999.4 million"),
    (31_250_000_000, "USD", "$31.3 billion"),               # half up, not half to even
    (31_250_000_000, "EUR", "EUR 31.3 billion"),           # a 20-F filer's own currency
    (6.11, "USD/share", "$6.11"),
    (-0.25, "USD/share", "-$0.25"),
    (3.31, "EUR/share", "EUR 3.31"),
    (15_115_823_000, "shares", "15.1 billion shares"),
    (950_000, "shares", "950,000 shares"),
    (0.2531, "ratio", "25.3%"),
    (-0.052, "ratio", "-5.2%"),
    (1.5057, "ratio", "150.6%"),
])
def test_fact_text_by_unit(value, unit, text):
    assert fmt.fact(_f(value, unit)) == text


def test_growth_carries_a_sign():
    assert fmt.fact(_f(0.0202, "ratio", key="revenue_growth")) == "+2.0%"
    assert fmt.fact(_f(-0.041, "ratio", key="net_income_growth")) == "-4.1%"
    assert fmt.fact(_f(0.00004, "ratio", key="revenue_growth")) == "0.0%"
    assert fmt.fact(_f(-0.00004, "ratio", key="gross_margin")) == "0.0%"      # never "-0.0%"
    assert fmt.fact(_f(0.25, "ratio", key="gross_margin")) == "25.0%"          # no sign unless growth


def test_no_value_is_not_available_never_zero():
    for unit in ("USD", "USD/share", "shares", "ratio"):
        assert fmt.fact(_f(None, unit)) == "Not available in the sources"
    assert fmt.fact(_f(float("nan"), "USD")) == "Not available in the sources"


def test_period_labels():
    assert fmt.period_label("FY2024") == "fiscal 2024"
    assert fmt.period_label("Q3-2024") == "Q3 2024"
    assert fmt.period_label("2024-09-28") == "as of 28 Sep 2024"
    assert fmt.period_label("2024-01-05") == "as of 5 Jan 2024"
    assert fmt.period_label("TTM") == "TTM"


def _ledger():
    ledger = Ledger()
    sid = ledger.add_source(K24)
    ledger.add_fact(Fact(key="revenue", period="FY2024", value=391_035_000_000.0, unit="USD",
                         source_ids=(sid,)))
    ledger.add_fact(Fact(key="gross_profit", period="FY2024", value=98_970_000_000.0, unit="USD",
                         source_ids=(sid,)))
    ledger.add_fact(Fact(key="gross_margin", period="FY2024", value=0.2531, unit="ratio",
                         inputs=(("gross_profit", "FY2024"), ("revenue", "FY2024")),
                         formula="gross_profit / revenue"))
    ledger.add_fact(Fact(key="return_on_equity", period="FY2024", value=None, unit="ratio",
                         inputs=(("revenue", "FY2024"),), formula="x",
                         note="shareholders' equity is negative"))
    return ledger


def test_cited_reported_fact_links_to_its_source():
    ledger = _ledger()
    html = fmt.cited(ledger.get("revenue", "FY2024"), ledger)
    assert html == ('<a class="src" href="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24.htm" '
                    'data-source="S1" target="_blank" rel="noopener noreferrer">$391.0 billion</a>')


def test_cited_computed_fact_links_to_its_calculation():
    ledger = _ledger()
    html = fmt.cited(ledger.get("gross_margin", "FY2024"), ledger)
    assert html == ('<a class="calc" href="#calc-gross_margin-FY2024" '
                    'data-calc="calc-gross_margin-FY2024">25.3%</a>')


def test_cited_without_a_value_is_plain_text():
    ledger = _ledger()
    assert fmt.cited(ledger.get("return_on_equity", "FY2024"), ledger) == "Not available in the sources"


def test_cited_escapes_every_text():
    ledger = Ledger()
    sid = ledger.add_source(Source(id="", type="web", url='https://www.sec.gov/x?q=<b>&t="1"',
                                   title="<script>", date=""))
    fact = ledger.add_fact(Fact(key="odd", period="FY2024", value=2.5, unit="<i>units</i>",
                                source_ids=(sid,)))
    html = fmt.cited(fact, ledger)
    assert "<b>" not in html and "<i>" not in html and '"1"' not in html
    assert 'href="https://www.sec.gov/x?q=&lt;b&gt;&amp;t=&quot;1&quot;"' in html
    assert html.endswith(">2.50 &lt;i&gt;units&lt;/i&gt;</a>")


def test_cited_refuses_a_figure_the_ledger_does_not_hold():
    ledger = _ledger()
    forged = Fact(key="revenue", period="FY2024", value=999.0, unit="USD", source_ids=("S1",))
    with pytest.raises(LedgerError):
        fmt.cited(forged, ledger)
    with pytest.raises(LedgerError):
        fmt.cited(Fact(key="revenue", period="FY2031", value=1.0, unit="USD", source_ids=("S1",)), ledger)


def test_a_ratio_of_a_thousand_per_cent_or_more_is_not_meaningful():
    from backend import format as fmt
    from backend.ledger import Fact
    big = Fact(key="operating_margin", period="FY2021", value=-80.291, unit="ratio",
               inputs=(("operating_income", "FY2021"), ("revenue", "FY2021")), formula="operating_income / revenue")
    assert fmt.fact(big) == "n/m"
    assert fmt.fact(Fact(key="revenue_growth", period="FY2022", value=29.145, unit="ratio",
                         inputs=(("revenue", "FY2022"), ("revenue", "FY2021")), formula="g")) == "n/m"
    assert fmt.fact(Fact(key="return_on_equity", period="FY2026", value=1.179, unit="ratio",
                         inputs=(("net_income", "FY2026"), ("shareholders_equity", "2026-09-26")), formula="r")) == "117.9%"
    assert fmt.fact(Fact(key="revenue_growth", period="FY2025", value=9.99, unit="ratio",
                         inputs=(("revenue", "FY2025"), ("revenue", "FY2024")), formula="g")) == "+999.0%"
