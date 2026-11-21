"""backend.analysis.peers over small company-facts fixtures; every backend.sources.sec call and
massive.previous_close is faked."""
import threading
import time

import pytest

from backend import format as fmt
from backend.analysis import peers, ratios
from backend.facts import select
from backend.ledger import Ledger
from backend.sources import massive, sec

FY_START, FY_END, PRIOR_START, PRIOR_END = "2023-07-01", "2024-06-30", "2022-07-01", "2023-06-30"


def _company_facts(accn, *, revenue, prior_revenue, operating_income, net_income, equity, debt=None,
                   eps=None, cash=None, shares=None, shares_end=FY_END, currency="USD", sti=None):
    def flow(val, start, end):
        return {"start": start, "end": end, "val": val, "accn": accn, "fy": 2024, "fp": "FY",
                "form": "10-K", "filed": "2024-07-30"}

    def balance(val, end=FY_END):
        return {"end": end, "val": val, "accn": accn, "fy": 2024, "fp": "FY", "form": "10-K",
                "filed": "2024-07-30"}
    gaap = {
        "Revenues": {"units": {currency: [flow(revenue, FY_START, FY_END), flow(prior_revenue, PRIOR_START, PRIOR_END)]}},
        "OperatingIncomeLoss": {"units": {currency: [flow(operating_income, FY_START, FY_END)]}},
        "NetIncomeLoss": {"units": {currency: [flow(net_income, FY_START, FY_END)]}},
        "StockholdersEquity": {"units": {currency: [balance(equity)]}},
    }
    if debt is not None:
        gaap["LongTermDebt"] = {"units": {currency: [balance(debt)]}}
    if eps is not None:
        gaap["EarningsPerShareDiluted"] = {"units": {f"{currency}/shares": [flow(eps, FY_START, FY_END)]}}
    if cash is not None:
        gaap["CashAndCashEquivalentsAtCarryingValue"] = {"units": {currency: [balance(cash)]}}
    if shares is not None:
        gaap["CommonStockSharesOutstanding"] = {"units": {"shares": [balance(shares, shares_end)]}}
    if sti is not None:
        gaap["ShortTermInvestments"] = {"units": {currency: [balance(sti)]}}
    if revenue is None:
        del gaap["Revenues"]
    return {"facts": {"us-gaap": gaap}}


def _peer(cik, name, doc, n, **figures):
    accn = f"{int(cik):010d}-24-00000{n}"
    filing = sec.Filing(accession=accn, form="10-K", filed="2024-07-30", period=FY_END, primary_doc=doc, cik=cik)
    return {"cik": cik, "name": name, "filings": [filing], "facts": _company_facts(accn, **figures)}


VALU = dict(revenue=100e9, prior_revenue=90e9, operating_income=20e9, net_income=15e9, equity=50e9,
            debt=30e9, cash=10e9, eps=6.0, shares=2.5e9)


def _peers():
    return {
        "MSFT": _peer("789019", "Microsoft Corporation", "msft-20240630.htm", 1, revenue=245_122e6,
                      prior_revenue=211_915e6, operating_income=109_433e6, net_income=88_136e6,
                      equity=268_477e6, debt=42_688e6),
        "ORCL": _peer("1341439", "Oracle Corporation", "orcl-20240531.htm", 2, revenue=52_961e6,
                      prior_revenue=49_954e6, operating_income=15_352e6, net_income=10_467e6,
                      equity=8_704e6, debt=76_264e6),
        "ADBE": _peer("796343", "Adobe Inc.", "adbe-20240630.htm", 3, revenue=21_505e6,
                      prior_revenue=19_409e6, operating_income=6_741e6, net_income=5_560e6,
                      equity=14_105e6),                                  # no long-term debt tagged
        "NEGQ": _peer("111111", "Negative Equity Co.", "negq-20240630.htm", 4, revenue=10e9,
                      prior_revenue=9e9, operating_income=1e9, net_income=0.5e9, equity=-2e9, debt=5e9),
        # hand numbers for the multiples: price $120, 2.5 billion shares -> market cap $300 billion;
        # net debt $30 - $10 = $20 billion -> EV $320 billion
        "VALU": _peer("222222", "Value Co.", "valu-20240630.htm", 5, **VALU),
        "NEPS": _peer("222223", "Loss Per Share Co.", "neps.htm", 6, **{**VALU, "eps": -1.0}),
        "NOPI": _peer("222224", "Operating Loss Co.", "nopi.htm", 7, **{**VALU, "operating_income": -5e9}),
        "NDBT": _peer("222225", "No Debt Tag Co.", "ndbt.htm", 8, **{**VALU, "debt": None}),
        "NEQT": _peer("222226", "Negative Book Co.", "neqt.htm", 9, **{**VALU, "equity": -10e9}),
        "EURO": _peer("222227", "Euro Filer N.V.", "euro.htm", 1, **{**VALU, "currency": "EUR"}),
        # net cash: $25 billion of short-term investments against $30 billion of debt and $10 billion cash
        "NETC": _peer("222228", "Net Cash Co.", "netc.htm", 2, **{**VALU, "sti": 25e9}),
        # a pre-revenue biotech, and a company whose data holds no revenue at all
        "ZREV": _peer("222229", "Zero Revenue Therapeutics", "zrev.htm", 3, revenue=0.0, prior_revenue=0.0,
                      operating_income=-50e6, net_income=-40e6, equity=800e6),
        "NREV": _peer("222230", "No Revenue Tag Inc.", "nrev.htm", 4, revenue=None, prior_revenue=None,
                      operating_income=5e9, net_income=4e9, equity=20e9),
        "GIII": _peer("821002", "G III APPAREL GROUP LTD /DE/", "giii.htm", 5, revenue=3e9, prior_revenue=3.1e9,
                      operating_income=0.2e9, net_income=0.15e9, equity=1.6e9),
    }


@pytest.fixture
def fake_sec(monkeypatch):
    """The SEC faked from _peers(); `hooks[ticker]` runs inside company_facts (to block or raise)."""
    data = _peers()
    by_cik = {d["cik"]: (t, d) for t, d in data.items()}
    monkeypatch.setattr(massive, "previous_close", lambda symbol, *a, **k: None)   # no price unless a test sets one
    hooks: dict = {}
    calls = {"facts": []}

    def cik_for(symbol, *a, **k):
        if symbol == "BOOM":
            return "999999"
        return data[symbol]["cik"] if symbol in data else None

    def company_name(symbol, *a, **k):
        return data[symbol]["name"] if symbol in data else None

    def filings(cik, *a, **k):
        return list(by_cik[cik][1]["filings"]) if cik in by_cik else []

    def company_facts(cik, *a, **k):
        if cik == "999999":
            raise RuntimeError("the SEC answered 500")
        ticker, d = by_cik[cik]
        calls["facts"].append((ticker, time.monotonic()))
        if ticker in hooks:
            hooks[ticker]()
        return d["facts"]

    monkeypatch.setattr(sec, "cik_for", cik_for)
    monkeypatch.setattr(sec, "company_name", company_name)
    monkeypatch.setattr(sec, "filings", filings)
    monkeypatch.setattr(sec, "company_facts", company_facts)
    return data, hooks, calls


def _ledger_for(peer: dict) -> Ledger:
    """The peer's ledger built the way the pipeline builds the main company's."""
    ledger = Ledger()
    select.statement_facts(peer["facts"], [peers._filing_dict(f) for f in peer["filings"]], ledger, cik=peer["cik"])
    ratios.compute(ledger)
    return ledger


# ---- profile --------------------------------------------------------------------------------
def test_a_reported_cell_links_to_the_peers_own_filing(fake_sec):
    data, _hooks, _calls = fake_sec
    row = peers.profile("MSFT")
    assert row["error"] is None
    assert (row["ticker"], row["name"]) == ("MSFT", "Microsoft Corporation")
    assert (row["period_label"], row["period_end"]) == ("fiscal 2024", "30 Jun 2024")
    viewer = data["MSFT"]["filings"][0].viewer_url
    cell = row["cells"]["revenue"]
    # the peer's own filing link, without the peer ledger's source number (it means nothing on
    # another company's page, where S27 is a different filing)
    full = fmt.cited(_ledger_for(data["MSFT"]).get("revenue", "FY2024"), _ledger_for(data["MSFT"]))
    assert "data-source" in full and "data-source" not in cell
    assert cell == peers._SOURCE_ID.sub("", full)
    assert f'href="{viewer}"' in cell and 'class="src"' in cell and ">$245.1 billion</a>" in cell


def test_a_computed_cell_links_to_the_filing_with_the_calculation_in_its_title(fake_sec):
    data, _hooks, _calls = fake_sec
    row = peers.profile("MSFT")
    viewer = data["MSFT"]["filings"][0].viewer_url
    for key in ("revenue_growth", "operating_margin", "net_margin", "return_on_equity", "debt_to_equity"):
        cell = row["cells"][key]
        assert "#calc-" not in cell and 'class="calc"' not in cell
        assert f'href="{viewer}"' in cell and 'class="src"' in cell and 'target="_blank"' in cell
        assert "(computed)" in cell
    margin = row["cells"]["operating_margin"]
    assert ('title="Operating income $109.4 billion ÷ revenue $245.1 billion, fiscal 2024 (computed)"'
            in margin)
    assert margin.endswith(">44.6%</a>")
    growth = row["cells"]["revenue_growth"]
    assert ('title="Revenue $245.1 billion (fiscal 2024) ÷ revenue $211.9 billion (fiscal 2023) − 1 (computed)"'
            in growth)
    assert growth.endswith(">+15.7%</a>")
    roe = row["cells"]["return_on_equity"]
    assert "shareholders&#x27; equity $268.5 billion (as of 30 Jun 2024)" in roe     # escaped quote


def test_values_match_the_peers_ledger(fake_sec):
    data, _hooks, _calls = fake_sec
    row = peers.profile("MSFT")
    ledger = _ledger_for(data["MSFT"])
    assert row["values"]["revenue"] == ledger.get("revenue", "FY2024").value == 245_122e6
    for key in ("revenue_growth", "operating_margin", "net_margin", "return_on_equity", "debt_to_equity"):
        assert row["values"][key] == ledger.get(key, "FY2024").value
    assert row["values"]["operating_margin"] == pytest.approx(109_433 / 245_122)
    assert row["values"]["debt_to_equity"] == pytest.approx(42_688 / 268_477)


def test_a_column_without_a_fact_is_na_and_none(fake_sec):
    row = peers.profile("ADBE")
    assert row["error"] is None
    assert row["cells"]["debt_to_equity"] == "n/a" and row["values"]["debt_to_equity"] is None
    assert row["values"]["revenue"] == 21_505e6


def test_a_ratio_that_is_not_meaningful_is_na_with_the_reason(fake_sec):
    row = peers.profile("NEGQ")
    assert row["values"]["return_on_equity"] is None
    assert ">n/a<" in row["cells"]["return_on_equity"]
    assert "negative" in row["cells"]["return_on_equity"]
    assert row["values"]["operating_margin"] == pytest.approx(0.1)


def test_profile_never_raises(fake_sec):
    for ticker in ("NOPE", "BOOM", "not a ticker!", ""):
        row = peers.profile(ticker)
        assert row["error"] == "Not available in the SEC data"
        assert all(v is None for v in row["values"].values())
        assert all(c == "" for c in row["cells"].values())
        assert set(row["cells"]) == set(row["values"]) == {k for k, _l in peers.COLUMNS}


# ---- benchmark ------------------------------------------------------------------------------
def test_a_peer_without_a_cik_and_a_peer_whose_fetch_raises_are_error_rows(fake_sec):
    table = peers.benchmark(["MSFT", "NOPE", "BOOM", "ORCL"])
    rows = {r["ticker"]: r for r in table["rows"]}
    assert rows["NOPE"]["error"] == rows["BOOM"]["error"] == "Not available in the SEC data"
    assert rows["MSFT"]["error"] is None and rows["ORCL"]["error"] is None
    assert rows["ORCL"]["values"]["revenue"] == 52_961e6
    assert (table["asked"], table["answered"]) == (4, 2)
    assert table["columns"] == [list(c) for c in peers.COLUMNS]
    assert table["note"].startswith("Each company's figures are its own latest fiscal year")


def test_the_profiles_run_at_the_same_time(fake_sec):
    _data, hooks, calls = fake_sec
    barrier = threading.Barrier(3, timeout=5)       # passes only if all three are inside at once
    for t in ("MSFT", "ORCL", "ADBE"):
        hooks[t] = barrier.wait
    started = time.monotonic()
    table = peers.benchmark(["MSFT", "ORCL", "ADBE"], timeout=10)
    assert [r["error"] for r in table["rows"]] == [None, None, None]
    assert time.monotonic() - started < 4
    assert len(calls["facts"]) == 3


def test_a_peer_that_does_not_finish_in_time_says_so(fake_sec):
    _data, hooks, _calls = fake_sec
    release = threading.Event()
    hooks["ORCL"] = lambda: release.wait(10)
    try:
        started = time.monotonic()
        table = peers.benchmark(["MSFT", "ORCL", "ADBE"], timeout=0.5)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert elapsed < 3                                  # the slow peer is not waited for
    assert [r["ticker"] for r in table["rows"]] == ["MSFT", "ORCL", "ADBE"]
    assert table["rows"][1]["error"] == "Took too long"
    assert table["rows"][1]["values"]["revenue"] is None
    assert table["rows"][0]["error"] is None and table["rows"][2]["error"] is None
    assert table["answered"] == 2


def test_order_is_kept_and_duplicates_are_dropped(fake_sec):
    table = peers.benchmark(["orcl", "MSFT", "ORCL", " msft ", "ADBE", "", "MSFT"])
    assert [r["ticker"] for r in table["rows"]] == ["ORCL", "MSFT", "ADBE"]
    assert table["asked"] == 3


def test_an_empty_list_gives_empty_rows_and_no_medians(fake_sec):
    for empty in ([], None):
        table = peers.benchmark(empty)
        assert table["rows"] == [] and (table["asked"], table["answered"]) == (0, 0)
        assert table["medians"] == {k: {"value": None, "text": None, "n": 0} for k, _l in peers.COLUMNS}


def _fake_row(ticker, error=None, units=None, **values):
    return {"ticker": ticker, "name": "", "period_label": "fiscal 2024", "period_end": "", "cells": {},
            "values": {k: values.get(k) for k, _l in peers.COLUMNS}, "units": units or {}, "error": error}


def test_medians_need_three_values_and_are_right_for_odd_and_even_counts(monkeypatch):
    rows = {
        "A": _fake_row("A", revenue=100e9, operating_margin=0.1, net_margin=0.1, revenue_growth=0.05),
        "B": _fake_row("B", revenue=300e9, operating_margin=0.4, net_margin=0.2, revenue_growth=-0.02),
        "C": _fake_row("C", revenue=200e9, operating_margin=0.3, revenue_growth=0.10),
        "D": _fake_row("D", operating_margin=0.2, return_on_equity=0.5),
        "E": _fake_row("E", error="Took too long", revenue=1e12, net_margin=0.9, return_on_equity=0.9),
        "F": _fake_row("F", units={"revenue": "EUR"}, revenue=5e12),     # another currency: not in the median
    }
    monkeypatch.setattr(peers, "profile", lambda t: rows[t])
    m = peers.benchmark(list(rows))["medians"]
    assert m["revenue"] == {"value": 200e9, "text": "$200.0 billion", "n": 3}                 # odd
    assert m["operating_margin"]["value"] == pytest.approx(0.25)                               # even
    assert (m["operating_margin"]["text"], m["operating_margin"]["n"]) == ("25.0%", 4)
    assert m["revenue_growth"] == {"value": 0.05, "text": "+5.0%", "n": 3}
    assert m["net_margin"] == {"value": None, "text": None, "n": 2}                            # two only
    assert m["return_on_equity"] == {"value": None, "text": None, "n": 1}
    assert m["debt_to_equity"] == {"value": None, "text": None, "n": 0}


def test_benchmark_never_raises_when_a_profile_blows_up(monkeypatch):
    def boom(ticker):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(peers, "profile", boom)
    table = peers.benchmark(["MSFT", "ORCL"])
    assert [(r["ticker"], r["error"]) for r in table["rows"]] == [
        ("MSFT", "Not available in the SEC data"), ("ORCL", "Not available in the SEC data")]


# ---- valuation multiples ----------------------------------------------------------------------
from datetime import date, timedelta  # noqa: E402

PRICE = {"date": "2024-11-20", "close": 120.0, "open": 119.0, "high": 121.0, "low": 118.0, "volume": 1e6}
NO_MARKET = {"shares": None, "shares_as_of": None, "market_cap": None, "net_debt": None, "enterprise_value": None}
NO_MULTIPLES = {"pe": None, "ev_ebit": None, "ev_sales": None, "pb": None}


@pytest.fixture
def prices(fake_sec, monkeypatch):
    """massive.previous_close faked: `prices[ticker]` is the bar, None, or an exception to raise."""
    table: dict = {}
    asked: list = []

    def previous_close(symbol, *a, **k):
        asked.append(symbol)
        value = table.get(symbol)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(massive, "previous_close", previous_close)
    table["_asked"] = asked
    return table


def test_every_multiple_with_hand_numbers(prices):
    prices["VALU"] = PRICE
    row = peers.profile("VALU")
    assert row["error"] is None
    assert row["price"] == {"close": 120.0, "date": "2024-11-20"}
    assert row["market"] == {"shares": 2.5e9, "shares_as_of": "2024-06-30", "market_cap": 300e9,
                             "net_debt": 20e9, "enterprise_value": 320e9}
    m = row["multiples"]
    assert m["pe"] == pytest.approx(120.0 / 6.0) == 20.0                 # price / diluted EPS
    assert m["ev_ebit"] == pytest.approx(320e9 / 20e9) == 16.0          # EV / operating income
    assert m["ev_sales"] == pytest.approx(320e9 / 100e9) == pytest.approx(3.2)
    assert m["pb"] == pytest.approx(300e9 / 50e9) == 6.0                # market cap / equity
    b = row["multiples_basis"]
    assert b["pe"] == "price $120.00 on 20 Nov 2024 ÷ diluted EPS $6.00, fiscal 2024"
    cap = "market cap $300.0 billion (price $120.00 on 20 Nov 2024 × 2.5 billion shares as of 30 Jun 2024)"
    assert b["pb"] == f"{cap} ÷ shareholders' equity $50.0 billion at 30 Jun 2024"
    ev = (f"; enterprise value = {cap} + net debt $20.0 billion (long-term debt $30.0 billion less cash "
          "$10.0 billion at 30 Jun 2024)")
    assert b["ev_ebit"] == f"enterprise value $320.0 billion ÷ operating income $20.0 billion, fiscal 2024{ev}"
    assert b["ev_sales"] == f"enterprise value $320.0 billion ÷ revenue $100.0 billion, fiscal 2024{ev}"
    assert "VALU" in prices["_asked"]
    # the earlier keys are all still there and unchanged in kind
    assert row["values"]["revenue"] == 100e9 and row["cells"]["revenue"].startswith('<a class="src"')


@pytest.mark.parametrize("ticker, none, kept", [
    ("NEPS", {"pe"}, {"ev_ebit", "ev_sales", "pb"}),                       # negative EPS
    ("NOPI", {"ev_ebit"}, {"pe", "ev_sales", "pb"}),                       # negative operating income
    ("NDBT", {"ev_ebit", "ev_sales"}, {"pe", "pb"}),                       # no long-term debt: no net debt, no EV
    ("NEQT", {"pb"}, {"pe", "ev_ebit", "ev_sales"}),                       # negative equity
])
def test_a_multiple_is_none_when_its_input_does_not_allow_it(prices, ticker, none, kept):
    prices[ticker] = PRICE
    row = peers.profile(ticker)
    assert row["error"] is None
    assert {k for k, v in row["multiples"].items() if v is None} == none
    assert {k for k, v in row["multiples"].items() if v is not None} == kept
    assert set(row["multiples_basis"]) == kept                             # a basis only for a value
    if ticker == "NDBT":
        assert row["market"]["net_debt"] is None and row["market"]["enterprise_value"] is None
        assert row["market"]["market_cap"] == 300e9


def test_a_stale_share_count_is_not_used_but_pe_still_works(prices):
    end = date(2024, 6, 30)
    prices["VALU"] = {**PRICE, "date": (end + timedelta(days=400)).isoformat()}
    assert peers.profile("VALU")["market"]["shares"] == 2.5e9              # 400 days: still used
    prices["VALU"] = {**PRICE, "date": (end + timedelta(days=401)).isoformat()}
    row = peers.profile("VALU")
    assert row["market"] == {**NO_MARKET, "net_debt": 20e9}
    assert row["multiples"] == {**NO_MULTIPLES, "pe": 20.0}
    assert set(row["multiples_basis"]) == {"pe"}


@pytest.mark.parametrize("bar", [None, RuntimeError("the price service is down"),
                                 {"date": "2024-11-20", "close": None}, {"date": "", "close": 120.0},
                                 {"date": "2024-11-20", "close": 0.0}])
def test_no_price_or_a_price_fetch_that_raises_gives_no_multiples(prices, bar):
    prices["VALU"] = bar
    row = peers.profile("VALU")
    assert row["error"] is None and row["values"]["revenue"] == 100e9     # the filed figures stand
    assert row["price"] is None
    assert row["multiples"] == NO_MULTIPLES and row["multiples_basis"] == {}
    assert row["market"]["market_cap"] is None and row["market"]["shares"] is None


def test_a_non_usd_filer_gets_no_money_multiples(prices):
    prices["EURO"] = PRICE
    row = peers.profile("EURO")
    assert row["error"] is None and row["units"]["revenue"] == "EUR"
    assert row["multiples"] == NO_MULTIPLES                                # EUR/share EPS, EUR equity, EUR debt
    assert row["market"]["net_debt"] is None and row["market"]["enterprise_value"] is None
    assert row["multiples_basis"] == {}


def test_an_error_row_has_no_price_market_or_multiples(prices):
    prices["NOPE"] = PRICE
    prices["BOOM"] = PRICE
    for ticker in ("NOPE", "BOOM"):
        row = peers.profile(ticker)
        assert row["error"] == "Not available in the SEC data"
        assert row["price"] is None and row["market"] == NO_MARKET
        assert row["multiples"] == NO_MULTIPLES and row["multiples_basis"] == {}
    late = peers.benchmark([])
    assert late["multiple_medians"] == {k: {"value": None, "n": 0} for k in NO_MULTIPLES}


def _multiples_row(ticker, error=None, **multiples):
    return {"ticker": ticker, "error": error, "values": {}, "units": {},
            "multiples": {k: multiples.get(k) for k in NO_MULTIPLES}}


def test_multiple_medians_need_three_values(monkeypatch):
    rows = {
        "A": _multiples_row("A", pe=10.0, ev_ebit=12.0, ev_sales=1.0),
        "B": _multiples_row("B", pe=40.0, ev_ebit=8.0, ev_sales=2.0),
        "C": _multiples_row("C", pe=20.0, ev_ebit=10.0),
        "D": _multiples_row("D", pe=30.0),
        "E": _multiples_row("E", error="Took too long", pe=99.0, ev_ebit=99.0, ev_sales=99.0, pb=99.0),
    }
    monkeypatch.setattr(peers, "profile", lambda t: rows[t])
    m = peers.benchmark(list(rows))["multiple_medians"]
    assert m["pe"] == {"value": 25.0, "n": 4}                              # four values: mean of the middle two
    assert m["ev_ebit"] == {"value": 10.0, "n": 3}                         # three values: the middle one
    assert m["ev_sales"] == {"value": None, "n": 2}                        # two values: no median
    assert m["pb"] == {"value": None, "n": 0}


def test_benchmark_carries_the_multiples_of_real_profiles(prices):
    for t in ("VALU", "NEPS", "NOPI", "NDBT"):
        prices[t] = PRICE
    table = peers.benchmark(["VALU", "NEPS", "NOPI", "NDBT"])
    m = table["multiple_medians"]
    assert m["pe"] == {"value": 20.0, "n": 3}                              # NEPS has none
    assert m["pb"] == {"value": 6.0, "n": 4}
    assert m["ev_ebit"] == {"value": None, "n": 2}                         # NOPI and NDBT have none
    assert m["ev_sales"]["n"] == 3 and m["ev_sales"]["value"] == pytest.approx(3.2)


# ---- review round: net cash, peers without revenue, slow peers ---------------------------------
import inspect  # noqa: E402

from backend.facts import metrics  # noqa: E402

STI_METRIC = metrics.Metric("short_term_investments", "Short-term investments", "USD", "instant",
                            (("us-gaap", "ShortTermInvestments"),))


def test_net_debt_takes_off_short_term_investments_when_the_peer_holds_them(prices, monkeypatch):
    monkeypatch.setitem(metrics.METRICS, "short_term_investments", STI_METRIC)
    prices["NETC"] = PRICE
    row = peers.profile("NETC")
    assert row["market"]["net_debt"] == 30e9 - 10e9 - 25e9 == -5e9        # net cash
    assert row["market"]["enterprise_value"] == 300e9 - 5e9
    assert row["multiples"]["ev_ebit"] == pytest.approx(295e9 / 20e9)
    assert row["multiples"]["ev_sales"] == pytest.approx(295e9 / 100e9)
    assert ("net debt -$5.0 billion (long-term debt $30.0 billion less cash $10.0 billion less short-term "
            "investments $25.0 billion at 30 Jun 2024)") in row["multiples_basis"]["ev_ebit"]
    # a peer that holds none: left out, and the basis does not mention them
    prices["VALU"] = PRICE
    plain = peers.profile("VALU")
    assert plain["market"]["net_debt"] == 20e9
    assert "short-term investments" not in plain["multiples_basis"]["ev_ebit"]
    assert "(long-term debt $30.0 billion less cash $10.0 billion at 30 Jun 2024)" in plain["multiples_basis"]["ev_ebit"]


def test_net_debt_works_while_the_metric_is_not_there_yet(prices, monkeypatch):
    monkeypatch.delitem(metrics.METRICS, "short_term_investments", raising=False)
    prices["NETC"] = PRICE
    row = peers.profile("NETC")                                             # the lookup finds nothing
    assert row["market"]["net_debt"] == 20e9
    assert "short-term investments" not in row["multiples_basis"]["ev_ebit"]


def test_a_peer_with_zero_revenue_has_no_margins_and_is_not_in_the_revenue_median(fake_sec):
    row = peers.profile("ZREV")
    assert row["error"] is None
    assert row["values"]["revenue"] == 0.0 and ">$0</a>" in row["cells"]["revenue"]   # the filed figure stands
    for key in ("operating_margin", "net_margin"):
        assert row["cells"][key] == '<span class="na" title="Not meaningful: revenue is zero">n/a</span>'
        assert row["values"][key] is None
    table = peers.benchmark(["MSFT", "ORCL", "ADBE", "ZREV"])
    assert table["medians"]["revenue"] == {"value": 52_961e6, "text": "$53.0 billion", "n": 3}
    assert table["medians"]["operating_margin"]["n"] == 3


def test_a_peer_without_revenue_has_margin_cells_that_say_so(fake_sec):
    row = peers.profile("NREV")
    assert row["error"] is None and row["cells"]["revenue"] == "n/a"
    for key in ("operating_margin", "net_margin"):
        assert row["cells"][key] == ('<span class="na" title="Not available: revenue is not in the SEC data '
                                     'for this year">n/a</span>')
        assert row["values"][key] is None
    assert row["values"]["return_on_equity"] == pytest.approx(4e9 / 20e9)  # the other columns stand


def test_a_negative_revenue_is_left_out_of_the_median():
    rows = [_fake_row(t, revenue=v) for t, v in (("A", 10e9), ("B", 20e9), ("C", 30e9), ("D", -5e9), ("E", 0.0))]
    assert peers.medians(rows)["revenue"] == {"value": 20e9, "text": "$20.0 billion", "n": 3}


def test_the_default_timeout_is_45_seconds_and_slow_peers_are_listed(fake_sec):
    assert inspect.signature(peers.benchmark).parameters["timeout"].default == 45.0
    _data, hooks, _calls = fake_sec
    release = threading.Event()
    hooks["ORCL"] = hooks["NEGQ"] = lambda: release.wait(10)
    try:
        table = peers.benchmark(["NEGQ", "MSFT", "ORCL", "ADBE"], timeout=0.5)
    finally:
        release.set()
    assert table["slow"] == ["NEGQ", "ORCL"]                                # in the order asked
    assert [r["error"] for r in table["rows"]] == ["Took too long", None, "Took too long", None]
    assert peers.benchmark(["MSFT", "ADBE"])["slow"] == []
    assert peers.benchmark([])["slow"] == []


def test_the_filings_index_and_the_company_facts_load_at_the_same_time(fake_sec, monkeypatch):
    barrier = threading.Barrier(2, timeout=5)       # passes only if both loads are running at once
    real_filings, real_facts = sec.filings, sec.company_facts

    def filings(cik, *a, **k):
        barrier.wait()
        return real_filings(cik)

    def company_facts(cik, *a, **k):
        barrier.wait()
        return real_facts(cik)
    monkeypatch.setattr(sec, "filings", filings)
    monkeypatch.setattr(sec, "company_facts", company_facts)
    row = peers.profile("MSFT")
    assert row["error"] is None and row["values"]["revenue"] == 245_122e6


def test_peer_names_are_shown_in_ordinary_case(fake_sec, monkeypatch):
    assert peers.profile("GIII")["name"] == "G III Apparel Group Ltd."            # capitals and "/DE/" tidied
    assert peers.profile("MSFT")["name"] == "Microsoft Corporation"               # the company's own spelling
    names = {"MSFT": "MICROSOFT CORP", "ORCL": "AMAZON COM INC"}
    monkeypatch.setattr(sec, "company_name", lambda symbol, *a, **k: names[symbol])
    assert [r["name"] for r in peers.benchmark(["MSFT", "ORCL"])["rows"]] == ["Microsoft Corp.", "Amazon.com Inc."]
