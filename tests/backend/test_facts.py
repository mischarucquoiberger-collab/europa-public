"""Facts are chosen by their own dates, never by the filing's fy/fp label (fixtures: synthetic
companyfacts documents in the SEC's shape, tests/backend/fixtures/facts_*.json)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.facts import select
from backend.facts.metrics import METRICS, label
from backend.ledger import Ledger

FIXTURES = Path(__file__).resolve().parent / "fixtures"
B = 1_000_000

K24_ACCN = "0009999001-24-000045"
K24_VIEWER = ("https://www.sec.gov/ix?doc=/Archives/edgar/data/9999001/000999900124000045/"
              "orch-20240928.htm")
K24_FILING = {"accession": K24_ACCN, "form": "10-K", "filed": "2024-11-01",
              "primary_doc": "orch-20240928.htm",
              "url": "https://www.sec.gov/Archives/edgar/data/9999001/000999900124000045/orch-20240928.htm",
              "viewer_url": K24_VIEWER}


def _doc(name):
    return json.loads((FIXTURES / f"facts_{name}.json").read_text())


def _load(name, filings=()):
    doc = _doc(name)
    ledger = Ledger()
    summary = select.statement_facts(doc, list(filings), ledger, cik=f"{doc['cik']:010d}")
    return ledger, summary


def _source_of(ledger, key, period):
    fact = ledger.get(key, period)
    assert fact is not None, (key, period)
    (source,) = ledger.cite(fact)
    return source


# ---- period_of ------------------------------------------------------------------------------
@pytest.mark.parametrize("start,end,fye,expected", [
    ("2023-10-01", "2024-09-28", 9, "FY2024"),     # 52-week year ending late September
    ("2022-09-25", "2023-09-30", 9, "FY2023"),     # 53-week year
    ("2024-01-01", "2024-12-31", 12, "FY2024"),
    ("2023-10-01", "2023-12-30", 9, "Q1-2024"),    # first quarter of fiscal 2024
    ("2023-12-31", "2024-03-30", 9, "Q2-2024"),
    ("2024-03-31", "2024-06-29", 9, "Q3-2024"),
    ("2024-06-30", "2024-09-28", 9, "Q4-2024"),
    ("2024-01-01", "2024-03-31", 12, "Q1-2024"),
    ("2024-10-01", "2024-12-31", 12, "Q4-2024"),
    ("2023-10-01", "2024-03-30", 9, None),         # six months year to date
    ("2023-10-01", "2024-06-29", 9, None),         # nine months year to date
    ("2024-01-01", "2024-01-31", 12, None),        # a month
    ("2024-09-28", "2023-10-01", 9, None),         # end before start
])
def test_period_of_durations(start, end, fye, expected):
    assert select.period_of({"start": start, "end": end, "fy": 2099, "fp": "Q2"}, "duration", fye) == expected


def test_period_of_ignores_fy_and_fp():
    entry = {"start": "2021-09-26", "end": "2022-09-24", "fy": 2024, "fp": "FY"}
    assert select.period_of(entry, "duration", 9) == "FY2022"


def test_period_of_instants_and_kind_mismatches():
    assert select.period_of({"end": "2024-09-28"}, "instant") == "2024-09-28"
    assert select.period_of({"start": "2024-01-01", "end": "2024-12-31"}, "instant") is None
    assert select.period_of({"end": "2024-12-31"}, "duration") is None
    assert select.period_of({"end": "not a date"}, "instant") is None


def test_a_52_53_week_year_ending_in_early_january_belongs_to_the_previous_year():
    # years ending 28 Dec 2019, 2 Jan 2021 and 1 Jan 2022 must not skip FY2020 or share a name
    assert select.period_of({"start": "2018-12-30", "end": "2019-12-28"}, "duration") == "FY2019"
    assert select.period_of({"start": "2019-12-29", "end": "2021-01-02"}, "duration") == "FY2020"
    assert select.period_of({"start": "2021-01-03", "end": "2022-01-01"}, "duration") == "FY2021"
    assert select.period_of({"start": "2021-10-03", "end": "2022-01-01"}, "duration") == "Q4-2021"
    # the ISO date of a balance is never shifted
    assert select.period_of({"end": "2021-01-02"}, "instant") == "2021-01-02"


# ---- (a) three years in one filing -----------------------------------------------------------
def test_three_years_in_one_filing_give_three_periods_with_the_right_values():
    raw = _doc("three_years")["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    in_k24 = [e for e in raw if e["accn"] == K24_ACCN]
    assert len(in_k24) == 3 and {e["fy"] for e in in_k24} == {2024} and {e["fp"] for e in in_k24} == {"FY"}
    ledger, _ = _load("three_years")
    assert ledger.get("revenue", "FY2024").value == 391_035 * B
    assert ledger.get("revenue", "FY2023").value == 383_285 * B
    assert ledger.get("revenue", "FY2022").value == 394_328 * B
    assert ledger.get("revenue", "FY2021").value == 365_817 * B   # only in the FY2023 10-K


# ---- (b) restatement -------------------------------------------------------------------------
def test_a_restated_value_from_a_newer_filing_wins_and_cites_that_filing():
    ledger, _ = _load("three_years", [K24_FILING])
    assert ledger.get("net_income", "FY2023").value == 97_100 * B     # not the original 96,995
    source = _source_of(ledger, "net_income", "FY2023")
    assert source.title == "Form 10-K, filed 2024-11-01"
    assert source.url == K24_VIEWER
    # a value only the older filing carries keeps the older filing
    assert _source_of(ledger, "net_income", "FY2021").title == "Form 10-K, filed 2023-11-03"


def test_figures_from_a_registration_statement_are_ignored():
    ledger, _ = _load("three_years")
    assert ledger.get("revenue", "FY2024").value == 391_035 * B       # not the S-4's pro forma 450,000
    assert all("S-4" not in s.title for s in ledger.sources())


# ---- (c) fallback tags -----------------------------------------------------------------------
def test_without_revenues_the_next_tag_in_the_list_is_used():
    assert "Revenues" not in _doc("fallback")["facts"]["us-gaap"]
    ledger, summary = _load("fallback")
    assert summary["tags"]["revenue"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert ledger.get("revenue", "FY2024").value == 48_200 * B
    assert ledger.get("revenue", "FY2023").value == 45_900 * B


def test_a_tag_the_company_stopped_using_does_not_hide_recent_years():
    ledger, summary = _load("stale_tag")
    assert summary["tags"]["revenue"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert [p for p in ledger.periods("revenue") if p >= "FY2022"] == ["FY2024", "FY2023", "FY2022"]
    assert ledger.get("revenue", "FY2024").value == 9_300 * B
    # the years before the current tag's first come from the retired one (a clean switch: the two
    # share no year), each citing its own filing
    assert ledger.get("revenue", "FY2017").value == 5_100 * B
    assert _source_of(ledger, "revenue", "FY2017").title == "Form 10-K, filed 2018-02-26"
    assert summary["backfilled"]["revenue"] == ["us-gaap:Revenues"]


def test_fallback_order_holds_when_both_tags_are_current():
    # the balance-sheet share count comes first; the cover-page count dated 20 days later is kept
    # beside it under its own date (the same quantity, see test_shares_keep_...)
    ledger, summary = _load("three_years")
    assert summary["tags"]["shares_outstanding"] == "us-gaap:CommonStockSharesOutstanding"
    assert ledger.periods("shares_outstanding") == ["2024-10-18", "2024-09-28", "2023-09-30"]
    assert ledger.get("shares_outstanding", "2024-09-28").value == 15_116_786_000


# ---- (d) a bank ------------------------------------------------------------------------------
def test_a_bank_yields_what_it_has_and_lists_the_rest_as_missing():
    ledger, summary = _load("bank")
    assert ledger.get("gross_profit", "FY2024") is None
    assert ledger.get("cost_of_revenue", "FY2024") is None
    for key in ("cost_of_revenue", "gross_profit", "operating_income"):
        assert key in summary["metrics_missing"]
        assert ledger.periods(key) == []
    # "cash and due from banks" is only part of a bank's cash: it is not shown as its cash
    assert "cash" not in summary["tags"] and ledger.periods("cash") == []
    assert ledger.get("revenue", "FY2024").value == 18_400 * B
    assert ledger.get("net_income", "FY2024").value == 5_060 * B
    assert ledger.get("total_assets", "2024-12-31").value == 412_000 * B
    assert ledger.get("long_term_debt", "2024-12-31").value == 61_000 * B
    assert ledger.get("dividends_per_share", "FY2024").value == pytest.approx(1.60)
    assert ledger.get("operating_cash_flow", "FY2024").value == -3_200 * B   # negative is kept, not dropped


def test_a_missing_metric_is_absent_never_zero():
    for name in ("three_years", "fallback", "stale_tag", "bank", "ifrs"):
        ledger, summary = _load(name)
        for key in summary["metrics_missing"]:
            assert ledger.periods(key) == [], (name, key)
        assert all(f.value != 0 for f in ledger.facts()), name
        assert set(summary["metrics_missing"]) | set(summary["tags"]) == set(METRICS)


# ---- (e) IFRS / 20-F -------------------------------------------------------------------------
def test_an_ifrs_20f_filer_is_read_from_ifrs_full_in_its_own_currency():
    ledger, summary = _load("ifrs")
    assert summary["taxonomy"] == "ifrs-full"
    assert summary["tags"]["revenue"] == "ifrs-full:Revenue"
    assert summary["tags"]["net_income"] == "ifrs-full:ProfitLossAttributableToOwnersOfParent"
    revenue = ledger.get("revenue", "FY2024")
    assert revenue.value == 31_250 * B and revenue.unit == "EUR"         # never relabelled as dollars
    assert ledger.get("eps_basic", "FY2024").unit == "EUR/share"
    assert ledger.get("shareholders_equity", "2024-12-31").value == 21_900 * B
    assert ledger.get("revenue", "FY2019") is None                      # the retired US GAAP tag
    assert _source_of(ledger, "revenue", "FY2024").title == "Form 20-F, filed 2025-03-12"


def test_taxonomy_summary_values():
    assert _load("three_years")[1]["taxonomy"] == "us-gaap"
    empty = Ledger()
    summary = select.statement_facts({"cik": 1, "facts": {}}, [], empty, cik="1")
    assert summary["facts"] == 0 and summary["taxonomy"] is None
    assert set(summary["metrics_missing"]) == set(METRICS)
    assert empty.keys() == []


# ---- (f) a non-December fiscal year -----------------------------------------------------------
def test_a_september_year_is_named_by_the_year_of_its_end():
    ledger, summary = _load("three_years")
    assert summary["fiscal_year_end_month"] == 9
    assert ledger.period_end("FY2024") == "2024-09-28"
    assert ledger.period_end("FY2023") == "2023-09-30"
    assert select.year_end_instant(ledger, 2024) == "2024-09-28"
    assert select.year_end_instant(ledger, 2030) is None
    # the quarter ending 30 Dec 2023 is the first quarter of fiscal 2024
    assert ledger.get("revenue", "Q1-2024").value == 119_575 * B
    assert ledger.get("revenue", "Q1-2023").value == 117_154 * B
    assert select.fiscal_years(ledger) == [2024, 2023, 2022, 2021]


def test_the_fiscal_year_end_month_can_be_given():
    doc = _doc("three_years")
    ledger = Ledger()
    select.statement_facts(doc, [], ledger, cik="9999001", fiscal_year_end_month=12)
    # told December, the quarter ending in December is a Q4 of calendar 2023
    assert ledger.get("revenue", "Q4-2023").value == 119_575 * B


# ---- (g) cumulative entries ------------------------------------------------------------------
def test_six_and_nine_month_totals_are_ignored():
    ledger, _ = _load("three_years")
    assert ledger.periods("revenue") == ["FY2024", "Q3-2024", "Q2-2024", "Q1-2024", "FY2023",
                                         "Q1-2023", "FY2022", "FY2021"]
    values = {f.value for f in ledger.facts()}
    assert 210_328 * B not in values and 296_105 * B not in values
    # operating cash flow is year to date in a 10-Q: no quarter at all
    assert ledger.periods("operating_cash_flow") == ["FY2024", "FY2023", "FY2022"]


# ---- (h) the fourth quarter ------------------------------------------------------------------
def test_q4_is_derived_from_the_year_and_three_quarters_as_a_computed_fact():
    ledger, _ = _load("three_years", [K24_FILING])
    added = select.derive_q4(ledger, 2024)
    assert {f.key for f in added} == {"revenue", "net_income"}
    q4 = ledger.get("revenue", "Q4-2024")
    assert q4.is_computed and q4.formula
    assert q4.value == (391_035 - 119_575 - 90_753 - 85_777) * B
    assert q4.inputs == (("revenue", "FY2024"), ("revenue", "Q1-2024"), ("revenue", "Q2-2024"),
                         ("revenue", "Q3-2024"))
    assert len(ledger.cite(q4)) == 4                                   # the 10-K and three 10-Qs
    assert ledger.period_end("Q4-2024") == "2024-09-28"


def test_q4_is_not_derived_without_all_four_inputs():
    ledger, _ = _load("three_years")
    assert select.derive_q4(ledger, 2023) == []                       # only Q1-2023 is reported
    assert ledger.get("revenue", "Q4-2023") is None
    # gross profit has the year but no quarters; EPS never adds up over quarters
    select.derive_q4(ledger, 2024)
    assert ledger.get("gross_profit", "Q4-2024") is None
    assert ledger.get("eps_basic", "Q4-2024") is None
    assert "eps_basic" not in select.q4_keys()


def test_derive_q4_twice_adds_nothing_new():
    ledger, _ = _load("three_years")
    assert len(select.derive_q4(ledger, 2024)) == 2
    assert select.derive_q4(ledger, 2024) == []


# ---- (i) every source opens on sec.gov --------------------------------------------------------
def test_every_reported_fact_links_to_sec_gov():
    for name in ("three_years", "fallback", "stale_tag", "bank", "ifrs"):
        ledger, _ = _load(name, [K24_FILING])
        for fact in ledger.facts():
            for source in ledger.cite(fact):
                assert source.url.startswith("https://www.sec.gov/"), source
                assert source.type == "edinet"


def test_viewer_link_when_the_filing_is_known_else_the_filing_folder():
    ledger, summary = _load("three_years", [K24_FILING])
    assert _source_of(ledger, "revenue", "FY2024").url == K24_VIEWER
    older = _source_of(ledger, "revenue", "FY2021")
    assert older.url == "https://www.sec.gov/Archives/edgar/data/9999001/000999900123000052/"
    assert older.date == "2023-11-03"
    assert summary["filings_used"] == len(ledger.sources()) == 5


def test_filings_may_be_objects_and_unsafe_links_are_not_used():
    as_object = SimpleNamespace(**K24_FILING)
    ledger, _ = _load("three_years", [as_object])
    assert _source_of(ledger, "revenue", "FY2024").url == K24_VIEWER
    odd = {**K24_FILING, "viewer_url": "javascript:alert(1)", "url": "http://example.com/x"}
    ledger, _ = _load("three_years", [odd])
    assert _source_of(ledger, "revenue", "FY2024").url == \
        "https://www.sec.gov/Archives/edgar/data/9999001/000999900124000045/"


def test_one_source_per_filing():
    ledger, _ = _load("three_years")
    urls = [s.url for s in ledger.sources()]
    assert len(urls) == len(set(urls))


# ---- metric definitions ----------------------------------------------------------------------
def test_metric_definitions():
    required = {"revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income",
                "eps_basic", "eps_diluted", "total_assets", "total_liabilities",
                "shareholders_equity", "cash", "long_term_debt", "operating_cash_flow", "capex",
                "shares_outstanding", "dividends_per_share", "research_and_development"}
    assert required <= set(METRICS)
    for key, m in METRICS.items():
        assert m.key == key and m.label and m.tags
        assert m.unit in ("USD", "USD/share", "shares", "ratio")
        assert m.kind in ("duration", "instant")
        assert all(tax in ("us-gaap", "ifrs-full", "dei") for tax, _tag in m.tags)
    assert METRICS["revenue"].tags[0] == ("us-gaap", "Revenues")
    assert METRICS["total_assets"].kind == "instant" and METRICS["revenue"].kind == "duration"
    assert label("operating_income") == "Operating income"
    assert label("gross_margin") == "Gross margin"


# ---- a quarterly report's trailing twelve months is not a fiscal year ---------------------------
def _ttm_doc():
    def e(start, end, val, form, accn, filed):
        return {"start": start, "end": end, "val": val, "accn": accn, "fy": 2026, "fp": "Q3" if form == "10-Q" else "FY",
                "form": form, "filed": filed}
    k, q = "0009999002-26-000010", "0009999002-26-000040"
    net_income = [
        e("2025-01-01", "2025-12-31", 76_000 * B, "10-K", k, "2026-02-06"),       # the fiscal year
        e("2026-07-01", "2026-09-30", 20_000 * B, "10-Q", q, "2026-10-30"),       # the quarter
        e("2025-10-01", "2026-09-30", 134_000 * B, "10-Q", q, "2026-10-30"),      # trailing twelve months
    ]
    revenue = [
        e("2025-01-01", "2025-12-31", 716_000 * B, "10-K", k, "2026-02-06"),
        e("2026-07-01", "2026-09-30", 201_000 * B, "10-Q", q, "2026-10-30"),
    ]
    return {"cik": 9999002, "entityName": "Calendar Co", "facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": net_income}},
        "Revenues": {"units": {"USD": revenue}}}}}


def test_trailing_twelve_months_in_a_quarterly_report_is_not_a_fiscal_year():
    doc = _ttm_doc()
    assert select.fiscal_year_end_month_of(doc) == 12          # from the annual report, not the 10-Q
    ledger = Ledger()
    summary = select.statement_facts(doc, [], ledger, cik="0009999002")
    assert summary["fiscal_year_end_month"] == 12
    assert ledger.get("net_income", "FY2026") is None          # 134 billion is no fiscal year
    assert 134_000 * B not in {f.value for f in ledger.facts()}
    assert ledger.periods("net_income") == ["Q3-2026", "FY2025"]   # the September quarter is the third
    assert ledger.get("net_income", "FY2025").value == 76_000 * B
    assert select.fiscal_years(ledger) == [2025]
    assert ledger.period_end("FY2026") is None


# ---- synthetic companyfacts documents for the reviewers' cases ---------------------------------
def _e(start, end, val, form, accn, filed, fy=None, fp=None):
    """One companyfacts entry; `start` None for an instant. `fy`/`fp` describe the filing."""
    entry = {"end": end, "val": val, "accn": accn, "form": form, "filed": filed,
             "fy": fy if fy is not None else int(filed[:4]), "fp": fp or ("FY" if form.startswith("10-K") else "Q2")}
    if start:
        entry["start"] = start
    return entry


def _company(*concepts, cik=9999100):
    """concepts: (taxonomy, tag, unit, [entries])"""
    facts: dict = {}
    for taxonomy, tag, unit, entries in concepts:
        facts.setdefault(taxonomy, {})[tag] = {"units": {unit: list(entries)}}
    return {"cik": cik, "entityName": "Synthetic Co", "facts": facts}


def _select(doc, filings=()):
    ledger = Ledger()
    summary = select.statement_facts(doc, list(filings), ledger, cik=f"{doc['cik']:010d}")
    return ledger, summary


K26, Q1, Q2, Q3 = "0009999100-26-000134", "0009999100-26-000045", "0009999100-26-000079", "0009999100-26-000104"


def _visa_rate(tag, rate=0.67, fy_value=None):
    """Visa's shape: the quarterly rate tagged for 3, 6, 9 and 12 months (fiscal year Oct-Sep)."""
    return ("us-gaap", tag, "USD/shares", [
        _e("2025-10-01", "2025-12-31", rate, "10-Q", Q1, "2026-01-30"),
        _e("2025-10-01", "2026-03-31", rate, "10-Q", Q2, "2026-04-29"),
        _e("2026-01-01", "2026-03-31", rate, "10-Q", Q2, "2026-04-29"),
        _e("2025-10-01", "2026-06-30", rate, "10-Q", Q3, "2026-07-29"),
        _e("2026-04-01", "2026-06-30", rate, "10-Q", Q3, "2026-07-29"),
        _e("2025-10-01", "2026-09-30", rate if fy_value is None else fy_value, "10-K", K26, "2026-11-05"),
    ])


# 1. a quarterly dividend rate tagged over twelve months is not the year's dividend
def test_a_quarterly_dividend_rate_tagged_over_the_year_is_not_used():
    ledger, summary = _select(_company(_visa_rate("CommonStockDividendsPerShareDeclared"),
                                       _visa_rate("CommonStockDividendsPerShareCashPaid")))
    assert ledger.get("dividends_per_share", "FY2026") is None        # never 0.67, never 4 x 0.67
    assert ledger.periods("dividends_per_share") == []
    assert "dividends_per_share" in summary["metrics_missing"]


def test_the_next_dividend_tag_is_used_when_it_holds_real_totals():
    cumulative = ("us-gaap", "CommonStockDividendsPerShareCashPaid", "USD/shares", [
        _e("2025-10-01", "2025-12-31", 0.67, "10-Q", Q1, "2026-01-30"),
        _e("2025-10-01", "2026-03-31", 1.34, "10-Q", Q2, "2026-04-29"),
        _e("2026-01-01", "2026-03-31", 0.67, "10-Q", Q2, "2026-04-29"),
        _e("2025-10-01", "2026-06-30", 2.01, "10-Q", Q3, "2026-07-29"),
        _e("2026-04-01", "2026-06-30", 0.67, "10-Q", Q3, "2026-07-29"),
        _e("2025-10-01", "2026-09-30", 2.68, "10-K", K26, "2026-11-05"),
    ])
    ledger, summary = _select(_company(_visa_rate("CommonStockDividendsPerShareDeclared"), cumulative))
    assert summary["tags"]["dividends_per_share"] == "us-gaap:CommonStockDividendsPerShareCashPaid"
    assert ledger.get("dividends_per_share", "FY2026").value == pytest.approx(2.68)


def test_one_dividend_a_year_is_a_real_total_and_is_kept():
    # paid once, in the first quarter: the year equals that quarter and the year to date, but the
    # later quarters are zero, so the year to date is the sum of its quarters: a real total
    once = ("us-gaap", "CommonStockDividendsPerShareDeclared", "USD/shares", [
        _e("2025-10-01", "2025-12-31", 1.00, "10-Q", Q1, "2026-01-30"),
        _e("2025-10-01", "2026-03-31", 1.00, "10-Q", Q2, "2026-04-29"),
        _e("2026-01-01", "2026-03-31", 0.00, "10-Q", Q2, "2026-04-29"),
        _e("2025-10-01", "2026-06-30", 1.00, "10-Q", Q3, "2026-07-29"),
        _e("2026-04-01", "2026-06-30", 0.00, "10-Q", Q3, "2026-07-29"),
        _e("2025-10-01", "2026-09-30", 1.00, "10-K", K26, "2026-11-05"),
    ])
    ledger, _ = _select(_company(once))
    assert ledger.get("dividends_per_share", "FY2026").value == pytest.approx(1.00)
    # a year with only the annual figure (no year to date to compare) is kept as well
    ledger, _ = _select(_company(_visa_rate("CommonStockDividendsPerShareDeclared", fy_value=2.68)))
    assert ledger.get("dividends_per_share", "FY2026").value == pytest.approx(2.68)


# 2, 11. revenue: the all-in totals first
K25 = "0009999100-26-000080"


def _fy(tag, val, year=2025, accn=K25, filed="2026-02-06", taxonomy="us-gaap", unit="USD"):
    return (taxonomy, tag, unit, [_e(f"{year}-01-01", f"{year}-12-31", val, "10-K", accn, filed)])


def test_a_finance_company_gets_total_revenues_net_of_interest_expense():
    stale = ("us-gaap", "Revenues", "USD", [_e("2010-01-01", "2010-12-31", 30_242 * B, "10-K",
                                                "0009999100-11-000010", "2011-02-25")])
    ledger, summary = _select(_company(
        stale, _fy("RevenueFromContractWithCustomerExcludingAssessedTax", 41_304 * B),
        _fy("RevenuesNetOfInterestExpense", 72_229 * B)))
    assert summary["tags"]["revenue"] == "us-gaap:RevenuesNetOfInterestExpense"
    assert ledger.get("revenue", "FY2025").value == 72_229 * B


def test_revenue_including_assessed_tax_and_ifrs_contract_revenue_are_fallbacks():
    ledger, summary = _select(_company(_fy("RevenueFromContractWithCustomerIncludingAssessedTax", 2_957 * B)))
    assert summary["tags"]["revenue"] == "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax"
    ledger, summary = _select(_company(_fy("RevenueFromContractWithCustomerIncludingAssessedTax", 2_990 * B),
                                       _fy("RevenueFromContractWithCustomerExcludingAssessedTax", 2_957 * B)))
    assert ledger.get("revenue", "FY2025").value == 2_957 * B
    ledger, summary = _select(_company(_fy("RevenueFromContractsWithCustomers", 201_196 * B,
                                           taxonomy="ifrs-full", unit="EUR")))
    assert summary["tags"]["revenue"] == "ifrs-full:RevenueFromContractsWithCustomers"
    assert ledger.get("revenue", "FY2025").unit == "EUR"
    tags = METRICS["revenue"].tags
    assert tags.index(("us-gaap", "Revenues")) < tags.index(("us-gaap", "RevenuesNetOfInterestExpense")) \
        < tags.index(("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")) \
        < tags.index(("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax")) \
        < tags.index(("us-gaap", "SalesRevenueNet"))
    assert tags.index(("ifrs-full", "Revenue")) < tags.index(("ifrs-full", "RevenueFromContractsWithCustomers"))


# 3, 4, 5, 13. fallbacks for companies that do not tag the usual concept
def test_net_income_fallbacks_for_companies_without_net_income_loss():
    old = ("us-gaap", "NetIncomeLoss", "USD", [_e("2013-01-01", "2013-12-31", 3_116 * B, "10-K",
                                                   "0009999100-14-000010", "2014-02-14")])
    ledger, summary = _select(_company(old, _fy("ProfitLoss", 14_968 * B)))
    assert summary["tags"]["net_income"] == "us-gaap:ProfitLoss"
    assert ledger.get("net_income", "FY2025").value == 14_968 * B
    ledger, summary = _select(_company(_fy("NetIncomeLossAvailableToCommonStockholdersBasic", -8_182 * B)))
    assert summary["tags"]["net_income"] == "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic"
    # NetIncomeLoss stays first when it is current
    ledger, summary = _select(_company(_fy("NetIncomeLoss", 10 * B), _fy("ProfitLoss", 11 * B)))
    assert ledger.get("net_income", "FY2025").value == 10 * B
    assert METRICS["net_income"].tags[0] == ("us-gaap", "NetIncomeLoss")


def test_capex_other_property_plant_and_equipment_is_a_fallback():
    ledger, summary = _select(_company(_fy("PaymentsToAcquireOtherPropertyPlantAndEquipment", 7_841 * B)))
    assert summary["tags"]["capex"] == "us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment"
    assert ledger.get("capex", "FY2025").value == 7_841 * B
    ledger, _ = _select(_company(_fy("PaymentsToAcquirePropertyPlantAndEquipment", 8 * B),
                                 _fy("PaymentsToAcquireOtherPropertyPlantAndEquipment", 7 * B)))
    assert ledger.get("capex", "FY2025").value == 8 * B


def _bal(tag, pairs, taxonomy="us-gaap", unit="USD"):
    """Year-end balances: [(end, val, form, accn, filed)]."""
    return (taxonomy, tag, unit, [_e(None, end, val, form, accn, filed) for end, val, form, accn, filed in pairs])


KB = ("10-K", "0009999100-26-008131", "2026-02-13")


def test_bank_cash_and_debt_fallbacks():
    stale_debt = _bal("LongTermDebt", [("2013-12-31", 267_889 * B, "10-K", "0009999100-14-000010", "2014-02-20")])
    ledger, summary = _select(_company(
        _bal("CashAndDueFromBanks", [("2025-12-31", 21_742 * B, *KB)]),
        stale_debt,
        _bal("LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", [("2025-12-31", 435_206 * B, *KB)])))
    assert "cash" not in summary["tags"] and ledger.periods("cash") == []       # not a bank's whole cash
    assert summary["tags"]["long_term_debt"] == \
        "us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"
    assert ledger.get("long_term_debt", "2025-12-31").value == 435_206 * B
    ledger, summary = _select(_company(_bal("LongTermDebtAndCapitalLeaseObligations", [("2025-12-31", 39_781 * B, *KB)])))
    assert ledger.get("long_term_debt", "2025-12-31").value == 39_781 * B


def test_a_credit_line_is_the_last_fallback_for_long_term_debt():
    old = _bal("LongTermDebt", [("2023-12-31", 125 * B, "10-K", "0009999100-24-000008", "2024-02-22")])
    line = _bal("LineOfCredit", [("2024-12-29", 0, "10-K", "0009999100-26-000008", "2026-02-20"),
                                 ("2025-12-28", 0, "10-K", "0009999100-26-000008", "2026-02-20")])
    ledger, summary = _select(_company(old, line))
    assert summary["tags"]["long_term_debt"] == "us-gaap:LineOfCredit"
    assert ledger.get("long_term_debt", "2025-12-28").value == 0          # a reported zero, not n/a
    assert METRICS["long_term_debt"].tags[-1] == ("us-gaap", "LineOfCredit")
    both = _bal("LongTermDebt", [("2025-12-28", 300 * B, *KB)])
    ledger, _ = _select(_company(both, line))
    assert ledger.get("long_term_debt", "2025-12-28").value == 300 * B


# 6. a balance tag used only in the annual report is not stale next to one also used in 10-Qs
def test_balance_freshness_is_read_from_the_annual_report():
    total = _bal("LongTermDebt", [("2024-12-31", 49_085 * B, "10-K", "0009999100-25-000010", "2025-02-04"),
                                  ("2025-12-31", 46_000 * B, *KB)])
    noncurrent = _bal("LongTermDebtNoncurrent", [
        ("2024-12-31", 46_547 * B, "10-K", "0009999100-25-000010", "2025-02-04"),
        ("2025-12-31", 43_000 * B, *KB),
        ("2026-09-30", 44_000 * B, "10-Q", "0009999100-26-000300", "2026-10-29")])
    ledger, summary = _select(_company(total, noncurrent))
    assert summary["tags"]["long_term_debt"] == "us-gaap:LongTermDebt"
    assert ledger.get("long_term_debt", "2025-12-31").value == 46_000 * B
    assert ledger.get("long_term_debt", "2026-09-30") is None          # one definition per metric
    # with no annual report carrying either tag, the newest date of any form decides
    q_only = _bal("LongTermDebt", [("2025-06-30", 1 * B, "10-Q", "0009999100-25-000200", "2025-08-01")])
    q_newer = _bal("LongTermDebtNoncurrent", [("2026-06-30", 2 * B, "10-Q", "0009999100-26-000200", "2026-08-01")])
    assert _select(_company(q_only, q_newer))[1]["tags"]["long_term_debt"] == "us-gaap:LongTermDebtNoncurrent"


# 7. the balance-sheet count at the year end and the cover-page count weeks later
def test_shares_keep_the_balance_sheet_and_the_cover_page_counts():
    balance = _bal("CommonStockSharesOutstanding", [("2025-12-31", 2_696_200_000, *KB),
                                                    ("2024-12-31", 2_797_600_000, *KB)], unit="shares")
    cover = _bal("EntityCommonStockSharesOutstanding", [
        ("2026-01-31", 2_697_032_375, *KB),
        ("2026-09-30", 2_655_609_509, "10-Q", "0009999100-26-069523", "2026-11-03"),
        ("2025-12-31", 2_696_000_001, *KB)], taxonomy="dei", unit="shares")
    ledger, summary = _select(_company(balance, cover))
    assert summary["tags"]["shares_outstanding"] == "us-gaap:CommonStockSharesOutstanding"
    assert ledger.periods("shares_outstanding") == ["2026-09-30", "2026-01-31", "2025-12-31", "2024-12-31"]
    assert ledger.get("shares_outstanding", "2025-12-31").value == 2_696_200_000   # the balance sheet wins
    assert ledger.get("shares_outstanding", "2026-09-30").value == 2_655_609_509


# 8. the source of a value is the annual report that first carried it
def test_a_year_end_balance_cites_the_annual_report_not_a_later_10q():
    k = ("10-K", "0009999100-26-323660", "2026-07-29")
    q = ("10-Q", "0009999100-26-436133", "2026-10-28")
    assets = _bal("Assets", [("2026-06-30", 758_376 * B, *k), ("2026-06-30", 758_376 * B, *q),
                             ("2026-09-30", 790_000 * B, *q)])
    ledger, _ = _select(_company(assets))
    (source,) = ledger.cite(ledger.get("total_assets", "2026-06-30"))
    assert source.title == "Form 10-K, filed 2026-07-29"
    (source,) = ledger.cite(ledger.get("total_assets", "2026-09-30"))
    assert source.title == "Form 10-Q, filed 2026-10-28"
    # a value restated in a later 10-Q is taken, and cites the filing that restated it
    restated = _bal("Assets", [("2026-06-30", 758_376 * B, *k), ("2026-06-30", 760_000 * B, *q)])
    ledger, _ = _select(_company(restated))
    fact = ledger.get("total_assets", "2026-06-30")
    assert fact.value == 760_000 * B
    assert ledger.cite(fact)[0].title == "Form 10-Q, filed 2026-10-28"
    # a value repeated in the next 10-K cites the first 10-K
    later_k = ("10-K", "0009999100-27-300000", "2027-07-28")
    twice = _bal("Assets", [("2026-06-30", 758_376 * B, *later_k), ("2026-06-30", 758_376 * B, *q),
                            ("2026-06-30", 758_376 * B, *k)])
    ledger, _ = _select(_company(twice))
    assert ledger.cite(ledger.get("total_assets", "2026-06-30"))[0].title == "Form 10-K, filed 2026-07-29"


# 12. an older year from the tag the company used before
def _years(tag, values, accn, filed, taxonomy="us-gaap", unit="USD"):
    return (taxonomy, tag, unit, [_e(f"{y}-01-01", f"{y}-12-31", v, "10-K", accn, filed) for y, v in values])


KNEW, KOLD = ("0009999100-26-000024", "2026-02-26"), ("0009999100-24-000015", "2024-02-29")


def test_history_backfill_when_the_tags_agree_on_a_shared_year():
    new = _years("RevenueFromContractWithCustomerExcludingAssessedTax",
                 [(2025, 2_515 * B), (2024, 1_356 * B), (2023, 1_318 * B), (2022, 654 * B)], *KNEW)
    old = _years("Revenues", [(2022, 654_500_000), (2021, 314_272_000)], *KOLD)
    ledger, summary = _select(_company(old, new))
    assert summary["tags"]["revenue"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert ledger.get("revenue", "FY2021").value == 314_272_000            # from Revenues
    assert ledger.get("revenue", "FY2022").value == 654 * B                 # the chosen tag keeps its years
    (source,) = ledger.cite(ledger.get("revenue", "FY2021"))
    assert source.title == "Form 10-K, filed 2024-02-29"                    # its own filing


def test_history_backfill_after_a_clean_switch():
    new = _years("RevenueFromContractWithCustomerExcludingAssessedTax", [(2025, 9_300 * B), (2024, 8_700 * B)], *KNEW)
    old = _years("Revenues", [(2023, 8_100 * B), (2022, 7_500 * B)], *KOLD)
    ledger, _ = _select(_company(old, new))
    assert ledger.periods("revenue") == ["FY2025", "FY2024", "FY2023", "FY2022"]


def test_no_backfill_when_the_tags_overlap_and_differ():
    new = _years("RevenueFromContractWithCustomerExcludingAssessedTax", [(2025, 9_300 * B), (2024, 8_700 * B)], *KNEW)
    old = _years("Revenues", [(2024, 9_000 * B), (2023, 8_100 * B)], *KOLD)     # 3.4% apart on FY2024
    ledger, _ = _select(_company(old, new))
    assert ledger.periods("revenue") == ["FY2025", "FY2024"]
    # never across accounting standards or currencies
    ledger, _ = _load("ifrs")
    assert ledger.get("revenue", "FY2019") is None


def test_history_backfill_for_year_end_balances():
    new = _bal("LongTermDebt", [("2025-12-31", 900 * B, *KB), ("2024-12-31", 800 * B, *KB)])
    agree = _bal("LongTermDebtNoncurrent", [("2024-12-31", 801 * B, "10-K", *KOLD),
                                            ("2023-12-31", 700 * B, "10-K", *KOLD),
                                            ("2023-09-30", 650 * B, "10-Q", "0009999100-23-000300", "2023-11-01")])
    ledger, _ = _select(_company(new, agree))
    assert ledger.get("long_term_debt", "2023-12-31").value == 700 * B
    assert ledger.get("long_term_debt", "2024-12-31").value == 800 * B
    assert ledger.get("long_term_debt", "2023-09-30") is None              # year-end balances only
    differ = _bal("LongTermDebtNoncurrent", [("2024-12-31", 700 * B, "10-K", *KOLD),
                                             ("2023-12-31", 650 * B, "10-K", *KOLD)])
    ledger, _ = _select(_company(new, differ))
    assert ledger.get("long_term_debt", "2023-12-31") is None


# 14. the company's own name for its fiscal year
def _retailer(fy_label_of_2026_year):
    k = "0009999100-26-000010"
    def e(start, end, val, form, accn, filed, fy):
        return {"start": start, "end": end, "val": val, "accn": accn, "form": form, "filed": filed, "fy": fy, "fp": "FY"}
    revenue = [
        e("2025-02-02", "2026-01-31", 104_780 * B, "10-K", k, "2026-03-11", fy_label_of_2026_year),
        e("2024-02-04", "2025-02-01", 106_566 * B, "10-K", k, "2026-03-11", fy_label_of_2026_year),
        e("2025-02-02", "2025-05-03", 23_846 * B, "10-Q", "0009999100-25-000100", "2025-05-21", 2099),
    ]
    assets = [{"end": "2026-01-31", "val": 57_000 * B, "accn": k, "form": "10-K", "filed": "2026-03-11",
               "fy": fy_label_of_2026_year, "fp": "FY"}]
    return {"cik": 9999100, "entityName": "Retail Co", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": revenue}}, "Assets": {"units": {"USD": assets}}}}}


def test_a_company_that_names_its_year_by_its_start_keeps_its_own_name():
    doc = _retailer(2025)                       # Target: the year to 31 Jan 2026 is its fiscal 2025
    assert select.fiscal_year_offset_of(doc) == -1
    ledger, summary = _select(doc)
    assert summary["fiscal_year_offset"] == -1
    assert ledger.get("revenue", "FY2025").value == 104_780 * B
    assert ledger.get("revenue", "FY2024").value == 106_566 * B
    assert ledger.get("revenue", "FY2026") is None
    assert ledger.period_end("FY2025") == "2026-01-31"
    assert select.year_end_instant(ledger, 2025) == "2026-01-31"
    assert ledger.get("revenue", "Q1-2025").value == 23_846 * B          # the quarter to May 2025
    assert ledger.get("total_assets", "2026-01-31") is not None           # dates are never shifted


def test_a_company_that_names_its_year_by_its_end_is_unchanged():
    doc = _retailer(2026)                       # NVIDIA, Walmart: the year to January 2026 is fiscal 2026
    assert select.fiscal_year_offset_of(doc) == 0
    ledger, summary = _select(doc)
    assert summary["fiscal_year_offset"] == 0
    assert ledger.get("revenue", "FY2026").value == 104_780 * B
    assert ledger.get("revenue", "Q1-2026").value == 23_846 * B
    assert select.fiscal_year_offset_of(_doc("three_years")) == 0
    assert select.fiscal_year_offset_of({"cik": 1, "facts": {}}) == 0
