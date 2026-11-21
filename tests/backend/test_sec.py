"""SEC EDGAR adapter over synthetic fixtures in the SEC's own response shapes."""
from pathlib import Path

import pytest

from backend.sources import http as source_http
from backend.sources import sec
from backend.sources.http import Client, SourceUnavailable

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"
AGENT = "Offline Tests offline@example.invalid"           # what tests/conftest.py sets
ROUTES = {
    "https://www.sec.gov/files/company_tickers.json": "sec_company_tickers.json",
    "https://data.sec.gov/submissions/CIK0001067983.json": "sec_submissions_CIK0001067983.json",
    "https://data.sec.gov/submissions/CIK0001067983-submissions-001.json": "sec_CIK0001067983-submissions-001.json",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0001067983.json": "sec_companyfacts_CIK0001067983.json",
    "https://www.sec.gov/Archives/edgar/data/1067983/000095017025020002/brka-20241231.htm": "sec_filing_10k.html",
}


class FixtureTransport:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": dict(headers)})
        name = ROUTES.get(url)
        return (200, (FIXTURES / name).read_bytes()) if name else (404, b"")


class Still:
    now = 1_000_000.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def transport():
    return FixtureTransport()


@pytest.fixture
def client(tmp_path, transport):
    still = Still()
    return Client("live", cache_dir=tmp_path / "cache", replay_dir=tmp_path / "replay",
                  transport=transport, sleep=still.sleep, clock=still.clock)


# --- the ticker list -----------------------------------------------------------------------

def test_cik_for_finds_the_dash_written_class_share(client):
    assert sec.cik_for("brk.b", client) == "1067983"
    assert sec.cik_for("BRK-B", client) == "1067983"
    assert sec.cik_for("aapl", client) == "320193"
    assert sec.cik_for("ZZZZ", client) is None
    assert sec.company_name("brk.b", client) == "BERKSHIRE HATHAWAY INC"
    assert sec.company_name("ZZZZ", client) is None


def test_ticker_table_is_keyed_by_the_normalised_symbol(client):
    table = sec.ticker_table(client)
    assert "BRK.B" in table and "BRK-B" not in table
    assert table["BRK.B"] == {"cik": "1067983", "ticker": "BRK.B", "title": "BERKSHIRE HATHAWAY INC"}
    assert "JPM-PD" not in table and "JPM.PD" not in table          # a preferred share is left out
    assert table["AAPL"]["title"] == "Apple Inc."                     # the first row wins a duplicate


def test_cik_for_refuses_a_string_that_is_not_a_symbol(client):
    with pytest.raises(ValueError):
        sec.cik_for("7203", client)


# --- filings -------------------------------------------------------------------------------

def test_filings_are_newest_first_and_include_the_overflow_file(client, transport):
    found = sec.filings("1067983", client=client)
    dates = [f.filed for f in found]
    assert dates == sorted(dates, reverse=True)
    assert [f.accession for f in found] == [
        "0000950170-25-100001", "0001067983-25-000010", "0000950170-25-020002",
        "0000950170-24-110003", "0000950134-09-004001", "0000950134-08-003001",
    ]
    assert "SC 13G" not in {f.form for f in found}                    # not one of the forms asked for
    assert all(f.primary_doc for f in found)                          # a row without a document is left out
    assert "https://data.sec.gov/submissions/CIK0001067983-submissions-001.json" in [c["url"] for c in transport.calls]


def test_filings_filter_by_form(client):
    annual = sec.filings(1067983, forms=("10-K",), client=client)
    assert [(f.form, f.period) for f in annual] == [("10-K", "2024-12-31"), ("10-K", "2008-12-31"), ("10-K", "2007-12-31")]
    everything = sec.filings("1067983", forms=None, client=client)
    assert "SC 13G" in {f.form for f in everything}


def test_filing_links_use_the_unpadded_cik_and_the_dash_free_accession(client):
    ten_k = next(f for f in sec.filings("0001067983", client=client) if f.form == "10-K")
    assert ten_k.cik == "1067983"
    assert ten_k.url == "https://www.sec.gov/Archives/edgar/data/1067983/000095017025020002/brka-20241231.htm"
    assert ten_k.viewer_url == "https://www.sec.gov/ix?doc=/Archives/edgar/data/1067983/000095017025020002/brka-20241231.htm"
    assert (ten_k.filed, ten_k.period, ten_k.primary_doc) == ("2025-02-24", "2024-12-31", "brka-20241231.htm")


def test_data_urls_use_the_ten_digit_padded_cik(client, transport):
    facts = sec.company_facts("1067983", client)
    sec.filings(1067983, client=client)
    assert facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["accn"] == "0000950170-25-020002"
    urls = [c["url"] for c in transport.calls]
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0001067983.json" in urls
    assert "https://data.sec.gov/submissions/CIK0001067983.json" in urls


# --- identity ------------------------------------------------------------------------------

def _every_call(client):
    filing = sec.Filing("0000950170-25-020002", "10-K", "2025-02-24", "2024-12-31", "brka-20241231.htm", "1067983")
    return [
        lambda: sec.ticker_table(client),
        lambda: sec.cik_for("AAPL", client),
        lambda: sec.company_name("AAPL", client),
        lambda: sec.filings("1067983", client=client),
        lambda: sec.company_facts("1067983", client),
        lambda: sec.filing_text(filing, client),
    ]


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_user_agent_raises_before_any_request(client, transport, monkeypatch, value):
    monkeypatch.setenv("SEC_USER_AGENT", value)
    for call in _every_call(client):
        with pytest.raises(SourceUnavailable) as caught:
            call()
        assert caught.value.reason.startswith("SEC_USER_AGENT is not set")
    assert transport.calls == []


@pytest.mark.parametrize("value", ["Offline Tests", "offline@example.invalid", "Name at example dot com",
                                   "Name offline@localhost"])
def test_a_user_agent_without_a_name_and_an_email_raises_before_any_request(client, transport, monkeypatch, value):
    monkeypatch.setenv("SEC_USER_AGENT", value)
    for call in _every_call(client):
        with pytest.raises(SourceUnavailable) as caught:
            call()
        assert caught.value.reason.startswith("SEC_USER_AGENT is not set")
        assert value not in str(caught.value)                         # the value is never echoed
    assert transport.calls == []


def test_the_user_agent_is_sent_on_every_call(client, transport):
    for call in _every_call(client):
        call()
    assert len(transport.calls) >= 5
    for request in transport.calls:
        assert request["headers"]["User-Agent"] == AGENT
        assert request["headers"]["Accept-Encoding"] == "gzip, deflate"
        assert "host" not in {name.lower() for name in request["headers"]}


# --- filing text ---------------------------------------------------------------------------

def test_filing_text_is_plain_text_with_paragraph_breaks(client):
    ten_k = next(f for f in sec.filings("1067983", forms=("10-K",), client=client))
    text = sec.filing_text(ten_k, client)
    for hidden in ("SCRIPT TEXT", "HIDDEN XBRL HEADER", "Synthetic annual report", "margin", "<"):
        assert hidden not in text, hidden
    paragraphs = text.split("\n\n")
    assert paragraphs[0] == "Item 1A. Risk Factors"
    assert "Our results depend on markets & rates.\nA second line." in paragraphs
    assert "Item 7. Management’s Discussion" in paragraphs
    assert "Revenue 100\nNet income 10" in text
    assert paragraphs[-1] == "Last paragraph."
    assert "\n\n\n" not in text


# --- the shared client and replay ----------------------------------------------------------

def test_the_default_client_is_used_when_none_is_given(client):
    try:
        source_http.set_default_client(client)
        assert sec.cik_for("brk.b") == "1067983"
    finally:
        source_http.set_default_client(None)


def test_recorded_sec_answers_replay_without_the_network(tmp_path, transport):
    still = Still()
    recorder = Client("record", cache_dir=tmp_path / "cache", replay_dir=tmp_path / "replay",
                      transport=transport, sleep=still.sleep, clock=still.clock)
    cik = sec.cik_for("BRK.B", recorder)
    recorded = sec.filings(cik, client=recorder)
    sec.company_facts(cik, recorder)

    def no_network(*args):
        raise AssertionError("replay mode called the network")

    replayer = Client("replay", replay_dir=tmp_path / "replay", transport=no_network)
    assert sec.cik_for("brk-b", replayer) == cik
    assert sec.filings(cik, client=replayer) == recorded
    assert sec.company_facts(cik, replayer)["entityName"] == "BERKSHIRE HATHAWAY INC"
    with pytest.raises(SourceUnavailable, match="CIK0000320193"):
        sec.filings("320193", client=replayer)                         # never recorded


def test_replay_needs_no_user_agent_because_nothing_is_sent(tmp_path, transport, monkeypatch):
    still = Still()
    recorder = Client("record", cache_dir=tmp_path / "cache", replay_dir=tmp_path / "replay",
                      transport=transport, sleep=still.sleep, clock=still.clock)
    sec.cik_for("BRK.B", recorder)
    monkeypatch.setenv("SEC_USER_AGENT", "")
    replayer = Client("replay", replay_dir=tmp_path / "replay", transport=transport)
    calls_before = len(transport.calls)
    assert sec.cik_for("BRK.B", replayer) == "1067983"
    assert len(transport.calls) == calls_before
    with pytest.raises(SourceUnavailable, match="SEC_USER_AGENT is not set"):
        sec.cik_for("BRK.B", recorder)                                 # live and record still refuse


def test_rows_read_the_8k_items_when_the_index_has_them_and_give_empty_otherwise():
    block = {"accessionNumber": ["0001067983-26-000002", "0001067983-26-000001"],
             "filingDate": ["2026-11-05", "2026-10-30"], "reportDate": ["2026-11-05", "2026-09-30"],
             "form": ["8-K", "10-Q"], "primaryDocument": ["brk8k.htm", "brka-20260930.htm"],
             "items": ["2.02,9.01", ""]}
    assert [f.items for f in sec._rows(block, "1067983")] == ["2.02,9.01", ""]
    without = {k: v for k, v in block.items() if k != "items"}
    assert [f.items for f in sec._rows(without, "1067983")] == ["", ""]


# --- a filing's documents (backend.research.releases) --------------------------------------

EIGHT_K = sec.Filing(accession="0000999999-26-000042", form="8-K", filed="2026-10-30", period="2026-10-30",
                     primary_doc="cldr-20261030.htm", cik="999999", items="2.02,9.01")
EIGHT_K_FOLDER = "https://www.sec.gov/Archives/edgar/data/999999/000099999926000042/"
DOC_ROUTES = {
    EIGHT_K_FOLDER + "0000999999-26-000042-index.htm": (FIXTURES / "sec_8k_index.htm").read_bytes(),
    EIGHT_K_FOLDER + "cldr-ex991q3.htm": b"<html><head><title>x</title></head><body><p>Exhibit 99.1</p>"
                                          b"<p>Calder reports results &amp; more.</p></body></html>",
    EIGHT_K_FOLDER + "notes.txt": b"First line\r\n\r\n\r\n\r\nSecond   line\r\n",
}


@pytest.fixture
def doc_client(tmp_path):
    calls = []

    def transport(url, headers, timeout):
        calls.append({"url": url, "headers": dict(headers)})
        body = DOC_ROUTES.get(url)
        return (200, body) if body is not None else (404, b"")

    still = Still()
    client = Client("live", cache_dir=tmp_path / "cache", replay_dir=tmp_path / "replay",
                    transport=transport, sleep=still.sleep, clock=still.clock)
    client.calls = calls
    return client


def test_filing_documents_read_the_index_table_with_types_and_archive_links(doc_client):
    docs = sec.filing_documents(EIGHT_K, doc_client)
    assert doc_client.calls[0]["url"] == EIGHT_K_FOLDER + "0000999999-26-000042-index.htm"
    assert doc_client.calls[0]["headers"]["User-Agent"] == AGENT
    assert [(d["name"], d["type"]) for d in docs] == [
        ("cldr-20261030.htm", "8-K"), ("cldr-ex991q3.htm", "EX-99.1"), ("cldr-ex992q3.htm", "EX-99.2"),
        ("cldr-20261030_g1.jpg", "GRAPHIC"), ("0000999999-26-000042.txt", ""),
        ("cldr-20261030.xsd", "EX-101.SCH")]                 # page furniture and another folder left out
    assert docs[1] == {"name": "cldr-ex991q3.htm", "type": "EX-99.1",
                       "description": "PRESS RELEASE DATED OCTOBER 30, 2026",
                       "url": EIGHT_K_FOLDER + "cldr-ex991q3.htm"}
    assert docs[0]["url"] == EIGHT_K_FOLDER + "cldr-20261030.htm"      # the /ix?doc= link, unwrapped
    assert all(d["url"].startswith("https://www.sec.gov/Archives/edgar/data/999999/") for d in docs)
    as_dict = {"accession": EIGHT_K.accession, "cik": "0000999999"}
    assert sec.filing_documents(as_dict, doc_client) == docs


def test_filing_documents_refuse_a_bad_filing_and_raise_when_the_index_is_missing(doc_client):
    with pytest.raises(ValueError):
        sec.filing_documents({"accession": "../../etc", "cik": "999999"}, doc_client)
    missing = sec.Filing(accession="0000999999-26-000043", form="8-K", filed="2026-10-31", period="",
                         primary_doc="x.htm", cik="999999")
    with pytest.raises(SourceUnavailable, match="not found"):
        sec.filing_documents(missing, doc_client)


def test_document_text_reads_html_and_txt_documents_inside_the_archive_only(doc_client):
    assert sec.document_text(EIGHT_K_FOLDER + "cldr-ex991q3.htm", doc_client) == \
        "Exhibit 99.1\n\nCalder reports results & more."
    assert sec.document_text(EIGHT_K_FOLDER + "notes.txt", doc_client) == "First line\n\nSecond   line"
    for bad in ("http://www.sec.gov/Archives/edgar/data/1/2/x.htm", "https://example.com/x.htm", None):
        with pytest.raises(ValueError):
            sec.document_text(bad, doc_client)
    with pytest.raises(SourceUnavailable):
        sec.document_text(EIGHT_K_FOLDER + "gone.htm", doc_client)


def test_a_reorganised_registrant_gets_its_predecessors_history(monkeypatch):
    """ExxonMobil's ticker now points at a new holding company with two 10-Qs and no annual
    report; the history is filed under the old registrant."""
    from backend.sources import sec

    monkeypatch.setitem(sec.PREDECESSORS, "777", ("111",))
    docs = {
        sec.COMPANY_FACTS_URL.format(cik="0000000777"): {"cik": 777, "entityName": "New Holdings", "facts": {"us-gaap": {
            "Revenues": {"label": "Revenues", "units": {"USD": [{"end": "2026-03-31", "val": 3, "accn": "0000000777-26-000001"}]}}}}},
        sec.COMPANY_FACTS_URL.format(cik="0000000111"): {"cik": 111, "entityName": "Old Corp", "facts": {"us-gaap": {
            "Revenues": {"label": "Revenues", "units": {"USD": [{"end": "2025-12-31", "val": 10, "accn": "0000000111-26-000009"}]}},
            "Assets": {"label": "Assets", "units": {"USD": [{"end": "2025-12-31", "val": 50, "accn": "0000000111-26-000009"}]}}}}},
    }
    monkeypatch.setattr(sec, "_get_json", lambda url, client, ttl: docs[url])
    merged = sec.company_facts("777")
    revenue = merged["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    assert [e["val"] for e in revenue] == [3, 10]                    # the new registrant's first, then the history
    assert merged["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] == 50
    assert merged["entityName"] == "New Holdings"
    assert sec.predecessors("0000000777") == ("111",) and sec.predecessors("320193") == ()
    # a registrant with no predecessor is returned as it is
    assert sec.company_facts("111") is docs[sec.COMPANY_FACTS_URL.format(cik="0000000111")]
