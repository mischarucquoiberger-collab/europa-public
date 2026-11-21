"""The evidence ledger refuses any figure without a source and follows computed facts to filings."""
import json

import pytest

from backend import contract
from backend.ledger import Fact, Ledger, LedgerError, Source

K24 = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24.htm",
             title="Form 10-K, filed 2024-11-01", date="2024-11-01")
K24A = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k24a.htm",
              title="Form 10-K/A, filed 2025-01-10", date="2025-01-10")
Q3 = Source(id="", type="edinet", url="https://www.sec.gov/Archives/edgar/data/1/000000000124000031/",
            title="Form 10-Q, filed 2024-08-02", date="2024-08-02")


def _reported(ledger, key, period, value, source, unit="USD"):
    sid = ledger.add_source(source)
    return ledger.add_fact(Fact(key=key, period=period, value=value, unit=unit, source_ids=(sid,)))


def _margin_ledger():
    """gross profit from the 10-K, revenue from its amendment: two different filings."""
    ledger = Ledger()
    _reported(ledger, "gross_profit", "FY2024", 400.0, K24)
    _reported(ledger, "revenue", "FY2024", 1000.0, K24A)
    margin = ledger.add_fact(Fact(key="gross_margin", period="FY2024", value=0.4, unit="ratio",
                                  inputs=(("gross_profit", "FY2024"), ("revenue", "FY2024")),
                                  formula="gross_profit / revenue"))
    return ledger, margin


def test_source_as_dict_has_exactly_the_interface_fields():
    ledger = Ledger()
    sid = ledger.add_source(K24)
    assert sid == "S1"
    assert tuple(ledger.source(sid).as_dict()) == contract.SOURCE_FIELDS
    assert ledger.source(sid).as_dict()["type"] == "edinet"


def test_same_source_twice_gets_one_id_and_ids_are_short_and_ordered():
    ledger = Ledger()
    assert ledger.add_source(K24) == "S1"
    assert ledger.add_source(Source(id="anything", type="edinet", url=K24.url, title=K24.title,
                                    date="other")) == "S1"
    assert ledger.add_source(K24A) == "S2"
    assert [s.id for s in ledger.sources()] == ["S1", "S2"]


def test_source_type_and_url_are_checked():
    ledger = Ledger()
    with pytest.raises(LedgerError):
        ledger.add_source(Source(id="", type="sec", url=K24.url, title="x", date=""))
    for bad in ("javascript:alert(1)", "/relative/path", "", "ftp://www.sec.gov/x"):
        with pytest.raises(LedgerError):
            ledger.add_source(Source(id="", type="web", url=bad, title="x", date=""))


def test_reported_fact_without_a_source_raises():
    ledger = Ledger()
    with pytest.raises(LedgerError, match="no source"):
        ledger.add_fact(Fact(key="revenue", period="FY2024", value=1.0, unit="USD"))


def test_reported_fact_with_an_unknown_source_id_raises():
    ledger = Ledger()
    ledger.add_source(K24)
    with pytest.raises(LedgerError, match="unknown source"):
        ledger.add_fact(Fact(key="revenue", period="FY2024", value=1.0, unit="USD", source_ids=("S9",)))


def test_reported_fact_without_a_value_raises_absence_is_no_fact():
    ledger = Ledger()
    sid = ledger.add_source(K24)
    with pytest.raises(LedgerError):
        ledger.add_fact(Fact(key="revenue", period="FY2024", value=None, unit="USD", source_ids=(sid,)))
    assert ledger.get("revenue", "FY2024") is None


def test_non_finite_values_raise():
    ledger = Ledger()
    sid = ledger.add_source(K24)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(LedgerError):
            ledger.add_fact(Fact(key="revenue", period="FY2024", value=bad, unit="USD", source_ids=(sid,)))


def test_computed_fact_without_inputs_raises():
    ledger = Ledger()
    with pytest.raises(LedgerError, match="no inputs"):
        ledger.add_fact(Fact(key="gross_margin", period="FY2024", value=0.4, unit="ratio",
                             formula="gross_profit / revenue"))


def test_computed_fact_with_an_unknown_input_raises():
    ledger = Ledger()
    _reported(ledger, "revenue", "FY2024", 1000.0, K24)
    with pytest.raises(LedgerError, match="not in the ledger"):
        ledger.add_fact(Fact(key="gross_margin", period="FY2024", value=0.4, unit="ratio",
                             inputs=(("gross_profit", "FY2024"), ("revenue", "FY2024")),
                             formula="gross_profit / revenue"))


def test_same_key_and_period_again_only_through_replace_fact():
    ledger = Ledger()
    first = _reported(ledger, "revenue", "FY2024", 1000.0, K24)
    with pytest.raises(LedgerError, match="replace_fact"):
        ledger.add_fact(first)
    sid = ledger.add_source(K24A)
    ledger.replace_fact(Fact(key="revenue", period="FY2024", value=1010.0, unit="USD", source_ids=(sid,)))
    assert ledger.get("revenue", "FY2024").value == 1010.0
    assert ledger.get("revenue", "FY2024").source_ids == ("S2",)


def test_replace_fact_refuses_a_cycle():
    ledger, _margin = _margin_ledger()
    with pytest.raises(LedgerError, match="depend on itself"):
        ledger.replace_fact(Fact(key="revenue", period="FY2024", value=1.0, unit="USD",
                                 inputs=(("gross_margin", "FY2024"),), formula="loop"))


def test_is_computed_and_values_are_floats():
    ledger, margin = _margin_ledger()
    assert margin.is_computed
    assert not ledger.get("revenue", "FY2024").is_computed
    stored = _reported(Ledger(), "revenue", "FY2024", 7, K24)
    assert isinstance(stored.value, float)


def test_cite_of_a_margin_returns_exactly_the_two_filings_behind_its_inputs():
    ledger, margin = _margin_ledger()
    cited = ledger.cite(margin)
    assert [s.url for s in cited] == [K24.url, K24A.url]
    assert [s.id for s in cited] == ["S1", "S2"]


def test_cite_lists_a_shared_filing_once():
    ledger = Ledger()
    _reported(ledger, "gross_profit", "FY2024", 400.0, K24)
    _reported(ledger, "revenue", "FY2024", 1000.0, K24)
    margin = ledger.add_fact(Fact(key="gross_margin", period="FY2024", value=0.4, unit="ratio",
                                  inputs=(("gross_profit", "FY2024"), ("revenue", "FY2024")),
                                  formula="gross_profit / revenue"))
    assert [s.id for s in ledger.cite(margin)] == ["S1"]


def test_cite_follows_two_levels_in_first_seen_order():
    ledger = Ledger()
    _reported(ledger, "operating_cash_flow", "FY2024", 300.0, K24)
    _reported(ledger, "capex", "FY2024", 50.0, Q3)
    _reported(ledger, "revenue", "FY2024", 1000.0, K24A)
    fcf = ledger.add_fact(Fact(key="free_cash_flow", period="FY2024", value=250.0, unit="USD",
                               inputs=(("operating_cash_flow", "FY2024"), ("capex", "FY2024")),
                               formula="operating_cash_flow - capex"))
    fcf_margin = ledger.add_fact(Fact(key="fcf_margin", period="FY2024", value=0.25, unit="ratio",
                                      inputs=(("free_cash_flow", "FY2024"), ("revenue", "FY2024")),
                                      formula="free_cash_flow / revenue"))
    assert [s.url for s in ledger.cite(fcf)] == [K24.url, Q3.url]
    assert [s.url for s in ledger.cite(fcf_margin)] == [K24.url, Q3.url, K24A.url]


def test_reported_cite_is_its_own_sources():
    ledger, _margin = _margin_ledger()
    assert [s.id for s in ledger.cite(ledger.get("revenue", "FY2024"))] == ["S2"]


def test_calc_id_is_safe_for_an_html_id():
    ledger, margin = _margin_ledger()
    assert ledger.calc_id(margin) == "calc-gross_margin-FY2024"
    odd = Fact(key="a b<c>", period="2024-09-28", value=1.0, unit="ratio",
               inputs=(("revenue", "FY2024"),), formula="x")
    assert ledger.calc_id(odd) == "calc-a-b-c--2024-09-28"


def test_periods_newest_first_and_keys_in_order():
    ledger = Ledger()
    for period, value in (("FY2023", 1.0), ("Q1-2024", 2.0), ("FY2024", 3.0), ("Q3-2024", 4.0),
                          ("Q2-2024", 5.0)):
        _reported(ledger, "revenue", period, value, K24)
    for period in ("2023-09-30", "2024-09-28", "2022-09-24"):
        _reported(ledger, "total_assets", period, 9.0, K24)
    assert ledger.periods("revenue") == ["FY2024", "Q3-2024", "Q2-2024", "Q1-2024", "FY2023"]
    assert ledger.periods("total_assets") == ["2024-09-28", "2023-09-30", "2022-09-24"]
    assert ledger.periods("missing") == []
    assert ledger.keys() == ["revenue", "total_assets"]


def test_to_json_from_json_round_trip():
    ledger, margin = _margin_ledger()
    ledger.set_period_end("FY2024", "2024-09-28")
    data = json.loads(json.dumps(ledger.to_json()))          # survives real JSON
    again = Ledger.from_json(data)
    assert again.to_json() == ledger.to_json()
    assert again.get("gross_margin", "FY2024") == margin
    assert [s.id for s in again.cite(margin)] == ["S1", "S2"]
    assert again.period_end("FY2024") == "2024-09-28"
    # ids stay unique after a reload
    assert again.add_source(Q3) == "S3"
    assert again.add_source(K24) == "S1"


def test_from_json_accepts_computed_facts_listed_before_their_inputs():
    ledger, _margin = _margin_ledger()
    data = ledger.to_json()
    data["facts"].reverse()
    assert Ledger.from_json(data).to_json()["facts"] != []
    assert Ledger.from_json(data).get("gross_margin", "FY2024").value == 0.4


def test_from_json_rechecks_every_fact():
    ledger, _margin = _margin_ledger()
    data = ledger.to_json()
    data["facts"] = [f for f in data["facts"] if f["key"] != "revenue"]
    with pytest.raises(LedgerError):
        Ledger.from_json(data)
    data = ledger.to_json()
    data["facts"][0]["source_ids"] = []
    with pytest.raises(LedgerError):
        Ledger.from_json(data)


def test_ledger_can_be_read_while_another_thread_adds_facts():
    import threading

    from backend.ledger import Fact, Ledger, Source

    ledger = Ledger()
    sid = ledger.add_source(Source(id="", type="edinet", url="https://www.sec.gov/x", title="10-K",
                                   date="2024-11-01", snippet=""))
    errors: list[BaseException] = []
    stop = threading.Event()

    def read():
        try:
            while not stop.is_set():
                ledger.keys(); ledger.facts(); ledger.periods("m0"); ledger.to_json()
        except BaseException as exc:      # "dictionary changed size during iteration" before the lock
            errors.append(exc)

    readers = [threading.Thread(target=read) for _ in range(4)]
    for t in readers:
        t.start()
    for i in range(3000):
        ledger.add_fact(Fact(key=f"m{i % 50}", period=f"FY{1000 + i}", value=float(i), unit="USD",
                             source_ids=(sid,)))
    stop.set()
    for t in readers:
        t.join()
    assert errors == []
    assert len(ledger.facts()) == 3000
