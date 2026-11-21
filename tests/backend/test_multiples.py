"""Own multiples: hand-checked numbers, not-available reasons, never added to the ledger, and the
new format units (x, years)."""
import re

import pytest

from backend import format as fmt
from backend.analysis import multiples, ratios, scenarios
from backend.ledger import Fact, Ledger, Source

K24 = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24.htm",
             title="Form 10-K, filed 2025-02-01", date="2025-02-01")
YE = "2024-12-31"
COVER = "2025-01-31"            # the cover-page share count, a later date than the year end

BASE = {
    ("eps_diluted", "FY2024"): 6.5,
    ("shares_outstanding", YE): 990.0, ("shares_outstanding", COVER): 1000.0,
    ("revenue", "FY2024"): 26_000.0, ("operating_income", "FY2024"): 7_000.0,
    ("operating_cash_flow", "FY2024"): 6_000.0, ("capex", "FY2024"): 800.0,     # FCF 5,200
    ("long_term_debt", YE): 20_000.0, ("cash", YE): 10_000.0,                   # net debt 10,000
    ("shareholders_equity", YE): 52_000.0,                                      # P/B 130,000 / 52,000
}
UNITS = {"eps_diluted": "USD/share", "shares_outstanding": "shares"}
PRICE, DAY = 130.0, "2025-03-20"
BANNED = ("undervalued", "overvalued", "upside", "target", "fair value", "buy", "sell")


def _ledger(values=None, units=None):
    ledger = Ledger()
    sid = ledger.add_source(K24)
    for (key, period), value in (BASE if values is None else values).items():
        unit = {**UNITS, **(units or {})}.get(key, "USD")
        ledger.add_fact(Fact(key=key, period=period, value=value, unit=unit, source_ids=(sid,)))
    ledger.set_period_end("FY2024", YE)
    ratios.compute(ledger)
    return ledger


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_multiples_match_hand_numbers():
    ledger = _ledger()
    rows = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))
    # market cap = 130 x 1,000 (the newest share count) = 130,000; EV = 130,000 + 10,000
    expected = {"price_to_earnings": (130 / 6.5, "20.0x"),
                "market_cap_to_revenue": (130_000 / 26_000, "5.0x"),
                "market_cap_to_fcf": (130_000 / 5_200, "25.0x"),
                "ev_to_operating_income": (140_000 / 7_000, "20.0x"),
                "price_to_book": (130_000 / 52_000, "2.5x")}
    assert list(rows) == list(expected)
    for key, (value, text) in expected.items():
        assert rows[key]["value"] == pytest.approx(value)
        assert rows[key]["text"] == text
        assert rows[key]["price_note"] == "Price: $130.00, end of day 2025-03-20 (market data)"
        assert rows[key]["formula"] and rows[key]["label"]


def test_inputs_are_linked_ledger_values():
    ledger = _ledger()
    rows = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))
    eps = ledger.get("eps_diluted", "FY2024")
    assert rows["price_to_earnings"]["inputs_html"] == [fmt.cited(eps, ledger)]
    shares = ledger.get("shares_outstanding", COVER)
    fcf = ledger.get("free_cash_flow", "FY2024")
    assert rows["market_cap_to_fcf"]["inputs_html"] == [fmt.cited(shares, ledger), fmt.cited(fcf, ledger)]
    ev_inputs = rows["ev_to_operating_income"]["inputs_html"]
    for key, period in (("long_term_debt", YE), ("cash", YE), ("operating_income", "FY2024")):
        assert fmt.cited(ledger.get(key, period), ledger) in ev_inputs
    assert rows["price_to_earnings"]["inputs"][0]["period"] == "fiscal 2024"


def test_multiples_are_not_added_to_the_ledger():
    ledger = _ledger()
    before = ledger.to_json()
    multiples.compute(ledger, price=PRICE, price_date=DAY)
    assert ledger.to_json() == before


def test_negative_eps_gives_the_not_available_text():
    ledger = _ledger({**BASE, ("eps_diluted", "FY2024"): -1.2})
    row = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))["price_to_earnings"]
    assert row["value"] is None
    assert row["text"].startswith(fmt.NOT_AVAILABLE)
    assert "zero or negative" in row["text"]


@pytest.mark.parametrize("change,key,reason", [
    ({("operating_income", "FY2024"): 0.0}, "ev_to_operating_income", "operating income is zero"),
    ({("operating_cash_flow", "FY2024"): 500.0}, "market_cap_to_fcf", "free cash flow is zero or negative"),
    ({("revenue", "FY2024"): -1.0}, "market_cap_to_revenue", "revenue is zero or negative"),
])
def test_non_positive_denominators(change, key, reason):
    ledger = _ledger({**BASE, **change})
    row = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))[key]
    assert row["value"] is None and reason in row["text"]


def test_missing_inputs_give_reasons():
    values = {k: v for k, v in BASE.items() if k != ("cash", YE)}
    row = _by_key(multiples.compute(_ledger(values), price=PRICE, price_date=DAY))["ev_to_operating_income"]
    assert row["value"] is None and "net debt is not available" in row["text"]
    values = {k: v for k, v in BASE.items() if k != ("eps_diluted", "FY2024")}
    row = _by_key(multiples.compute(_ledger(values), price=PRICE, price_date=DAY))["price_to_earnings"]
    assert row["value"] is None and "not in the sources" in row["text"] and row["inputs_html"] == []


def test_no_price_means_no_multiple():
    rows = multiples.compute(_ledger(), price=None, price_date=None)
    assert len(rows) == 5
    assert all(r["value"] is None and r["text"].startswith(fmt.NOT_AVAILABLE) for r in rows)
    assert rows[0]["price_note"].startswith("No share price")


def test_supplied_share_count_and_a_currency_mismatch():
    rows = _by_key(multiples.compute(_ledger(), price=PRICE, price_date=DAY, shares=2000.0))
    assert rows["market_cap_to_revenue"]["text"] == "10.0x"                # 260,000 / 26,000
    assert "supplied with the price" in rows["market_cap_to_revenue"]["price_note"]
    eur = _ledger(units={"eps_diluted": "EUR/share"})
    row = _by_key(multiples.compute(eur, price=PRICE, price_date=DAY))["price_to_earnings"]
    assert row["value"] is None and "EUR/share" in row["text"]


def test_uses_the_ledger_net_debt_when_scenarios_computed_it():
    ledger = _ledger()
    scenarios.compute(ledger)
    row = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))["ev_to_operating_income"]
    assert row["text"] == "20.0x"
    assert any('href="#calc-net_debt-FY2024"' in h for h in row["inputs_html"])


def test_no_fiscal_year_gives_an_empty_list():
    assert multiples.compute(Ledger(), price=PRICE, price_date=DAY) == []


def test_never_advises():
    for rows in (multiples.compute(_ledger(), price=PRICE, price_date=DAY),
                 multiples.compute(_ledger({**BASE, ("eps_diluted", "FY2024"): -1.0}), price=None,
                                   price_date=None)):
        for row in rows:
            for value in (row["label"], row["text"], row["formula"], row["price_note"],
                          *row["inputs_html"]):
                visible = re.sub(r"<[^>]+>", " ", value).lower()
                for word in BANNED:
                    assert word not in visible, (word, value)


@pytest.mark.parametrize("value,unit,text", [
    (24.25, "x", "24.3x"),                 # half up
    (-3.24, "x", "-3.2x"),
    (1234.56, "x", "1,234.6x"),
    (-0.01, "x", "0.0x"),                  # never "-0.0x"
    (2.0014, "years", "2.0 years"),
    (4.0, "years", "4.0 years"),
])
def test_format_new_units(value, unit, text):
    assert fmt.fact(Fact(key="m", period="FY2024", value=value, unit=unit)) == text


def test_a_share_count_from_years_ago_is_not_multiplied_by_todays_price():
    """A company with several share classes may stop tagging one total. Its count from years ago
    times today's price would be a wrong market capitalisation."""
    ledger = _ledger()
    rows = _by_key(multiples.compute(ledger, price=PRICE, price_date="2026-11-20"))      # 20 months later
    assert rows["price_to_earnings"]["value"] == pytest.approx(130 / 6.5)               # needs no share count
    for key in ("market_cap_to_revenue", "market_cap_to_fcf", "ev_to_operating_income"):
        assert rows[key]["value"] is None
        assert "too old to use with the price" in rows[key]["text"]
    # market data's count is used then, and the row says so
    rows = _by_key(multiples.compute(ledger, price=PRICE, price_date="2026-11-20", fallback_shares=2000.0))
    assert rows["market_cap_to_revenue"]["value"] == pytest.approx(130 * 2000 / 26_000)
    assert "(market data; the newest share count in the filings is" in rows["market_cap_to_revenue"]["price_note"]
    # a fresh count from the filings always wins over market data's
    rows = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY, fallback_shares=2000.0))
    assert rows["market_cap_to_revenue"]["value"] == pytest.approx(130_000 / 26_000)
    assert "market data;" not in rows["market_cap_to_revenue"]["price_note"]


# ---- net debt with short-term investments, banks, price / book ----------------------------------
def test_net_debt_subtracts_short_term_investments_when_held():
    # 20,000 debt - 10,000 cash - 30,000 short-term investments = 20,000 of net CASH
    ledger = _ledger({**BASE, ("short_term_investments", YE): 30_000.0})
    row = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))["ev_to_operating_income"]
    assert row["value"] == pytest.approx((130_000 - 20_000) / 7_000)      # EV 110,000 < market cap
    assert row["text"] == "15.7x"
    assert row["formula"].endswith("net_debt = long_term_debt - cash - short_term_investments at year end")
    sti = ledger.get("short_term_investments", YE)
    assert fmt.cited(sti, ledger) in row["inputs_html"]
    # without them: the two-input form
    row = _by_key(multiples.compute(_ledger(), price=PRICE, price_date=DAY))["ev_to_operating_income"]
    assert row["formula"].endswith("net_debt = long_term_debt - cash at year end")


def test_ledger_net_debt_from_scenarios_includes_short_term_investments():
    ledger = _ledger({**BASE, ("short_term_investments", YE): 30_000.0})
    scenarios.compute(ledger)
    assert ledger.get("net_debt", "FY2024").value == pytest.approx(-20_000.0)
    row = _by_key(multiples.compute(ledger, price=PRICE, price_date=DAY))["ev_to_operating_income"]
    assert row["text"] == "15.7x" and "short_term_investments" in row["formula"]


def test_financial_company_skips_cash_flow_and_enterprise_value_rows():
    rows = _by_key(multiples.compute(_ledger(), price=PRICE, price_date=DAY, financial=True))
    for key in ("market_cap_to_fcf", "ev_to_operating_income"):
        assert rows[key]["value"] is None and rows[key]["inputs_html"] == []
        assert rows[key]["reason"] == multiples.FINANCIAL_REASON
        assert rows[key]["text"].startswith("Not used for a bank or insurer: enterprise value and free cash flow")
        assert fmt.NOT_AVAILABLE not in rows[key]["text"]
    assert rows["price_to_earnings"]["text"] == "20.0x" and rows["market_cap_to_revenue"]["text"] == "5.0x"
    assert rows["price_to_book"]["text"] == "2.5x"


def test_price_to_book_not_available_reasons():
    rows = _by_key(multiples.compute(_ledger({**BASE, ("shareholders_equity", YE): -5.0}), price=PRICE, price_date=DAY))
    assert rows["price_to_book"]["value"] is None and "zero or negative" in rows["price_to_book"]["text"]
    values = {k: v for k, v in BASE.items() if k != ("shareholders_equity", YE)}
    row = _by_key(multiples.compute(_ledger(values), price=PRICE, price_date=DAY))["price_to_book"]
    assert row["value"] is None and "book equity at the fiscal year end is not in the sources" in row["text"]
    shares = _ledger().get("shares_outstanding", COVER)
    row = _by_key(multiples.compute(_ledger(), price=PRICE, price_date=DAY))["price_to_book"]
    assert row["inputs_html"][0] == fmt.cited(shares, _ledger())
    assert row["reason"] is None


def test_the_pe_row_carries_no_share_count_note():
    rows = _by_key(multiples.compute(_ledger(), price=PRICE, price_date="2026-11-20", fallback_shares=2000.0))
    assert rows["price_to_earnings"]["price_note"] == "Price: $130.00, end of day 2026-11-20 (market data)"
    assert "market data;" in rows["market_cap_to_revenue"]["price_note"]


def test_no_output_names_the_original_product():
    for kw in ({}, {"financial": True}, {"price": None}):
        args = {"price": PRICE, "price_date": DAY, **kw}
        for row in multiples.compute(_ledger({**BASE, ("short_term_investments", YE): 1.0}), **args):
            for value in row.values():
                assert "original" not in str(value).lower(), value
