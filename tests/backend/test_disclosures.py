"""backend.filings.disclosures: the last twelve months of a company's filings, from the index only."""
from datetime import date

import pytest

from backend.filings import disclosures
from backend.sources import sec

TODAY = date(2026, 11, 22)


def _filing(n, form, filed, period="", items=""):
    return sec.Filing(accession=f"0000320193-26-{n:06d}", form=form, filed=filed, period=period,
                      primary_doc=f"doc{n}.htm", cik="320193", items=items)


def test_only_the_window_newest_first_with_viewer_links():
    filings = [
        _filing(1, "10-K", "2026-10-30", period="2026-09-26"),
        _filing(2, "8-K", "2026-11-05", items="2.02,9.01"),
        _filing(3, "10-Q", "2025-11-22", period="2025-09-27"),       # exactly 365 days before: in
        _filing(4, "10-Q", "2025-11-21", period="2025-09-27"),       # 366 days before: out
        _filing(5, "8-K", "2026-11-23", items="8.01"),               # after today: out
        _filing(6, "10-Q", "2026-08-01", period="2026-06-27"),
    ]
    rows = disclosures.recent(filings, today=TODAY)
    assert [r["date"] for r in rows] == ["2026-11-05", "2026-10-30", "2026-08-01", "2025-11-22"]
    first = rows[0]
    assert first == {"date": "2026-11-05", "date_text": "5 Nov 2026", "form": "8-K", "title": "Current report",
                     "detail": "Results of operations and financial condition; Financial statements and exhibits",
                     "url": filings[1].viewer_url}
    assert rows[1]["date_text"] == "30 Oct 2026"
    assert all(r["url"].startswith("https://www.sec.gov/ix?doc=") for r in rows)


def test_the_limit_and_the_days():
    filings = [_filing(i, "8-K", f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", items="8.01") for i in range(40)]
    assert len(disclosures.recent(filings, today=TODAY)) == 30
    two = disclosures.recent(filings, today=TODAY, limit=2)
    assert [r["date"] for r in two] == ["2026-02-12", "2026-02-11"]
    assert disclosures.recent(filings, today=TODAY, days=1) == []
    assert [r["date"] for r in disclosures.recent(filings, today=date(2026, 1, 3), days=1)] == [
        "2026-01-03", "2026-01-02"]


@pytest.mark.parametrize("form, title", [
    ("10-K", "Annual report"), ("10-K/A", "Annual report (amended)"), ("10-Q", "Quarterly report"),
    ("10-Q/A", "Quarterly report (amended)"), ("8-K", "Current report"), ("8-K/A", "Current report (amended)"),
    ("20-F", "Annual report (foreign issuer)"), ("6-K", "Report of foreign issuer"),
    ("40-F", "Annual report (Canadian issuer)"), ("DEF 14A", "Proxy statement"),
    ("S-1", "Registration statement"), ("SC 13G", "SC 13G"), ("425", "425"),
])
def test_form_titles(form, title):
    rows = disclosures.recent([_filing(1, form, "2026-11-01")], today=TODAY)
    assert (rows[0]["form"], rows[0]["title"]) == (form, title)


def test_8k_items_in_their_own_order_with_an_unknown_code():
    rows = disclosures.recent([_filing(1, "8-K", "2026-11-01", items="9.01,5.02,1.04,5.02"),
                               _filing(2, "8-K/A", "2026-10-01", items=""),
                               _filing(3, "8-K", "2026-09-01", items="5.07, 7.01")], today=TODAY)
    assert rows[0]["detail"] == ("Financial statements and exhibits; Departure or appointment of directors "
                                 "or officers; Item 1.04")
    assert rows[1]["detail"] == ""
    assert rows[2]["detail"] == "Results of a shareholder vote; Regulation FD disclosure"
    assert len(disclosures.ITEM_TITLES) == 22


def test_period_wording_for_annual_and_quarterly_reports():
    rows = disclosures.recent([_filing(1, "10-Q", "2026-11-01", period="2026-09-30"),
                               _filing(2, "10-K", "2026-10-01", period="2026-06-30"),
                               _filing(3, "10-Q", "2026-09-01", period=""),
                               _filing(4, "DEF 14A", "2026-08-01", period="2026-06-30")], today=TODAY)
    assert [r["detail"] for r in rows] == ["Period ended 30 Sep 2026", "Period ended 30 Jun 2026", "", ""]


def test_dicts_work_as_well_as_filings():
    rows = disclosures.recent([
        {"form": "8-K", "filed": "2026-11-02", "items": "8.01",
         "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000009/a8k.htm"},
        {"form": "10-Q", "filed": "2026-11-01", "period": "2026-09-27",
         "viewer_url": "https://www.sec.gov/ix?doc=/Archives/edgar/data/320193/000032019326000008/q.htm",
         "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000008/q.htm"},
    ], today=TODAY)
    assert [(r["form"], r["detail"], r["url"]) for r in rows] == [
        ("8-K", "Other events", "https://www.sec.gov/Archives/edgar/data/320193/000032019326000009/a8k.htm"),
        ("10-Q", "Period ended 27 Sep 2026",
         "https://www.sec.gov/ix?doc=/Archives/edgar/data/320193/000032019326000008/q.htm"),
    ]


def test_bad_dates_and_unusable_links_are_skipped_and_nothing_raises():
    good = _filing(1, "10-K", "2026-10-30", period="2026-09-26")
    rows = disclosures.recent([
        _filing(2, "8-K", "2026-13-45", items="8.01"),
        _filing(3, "8-K", "", items="8.01"),
        {"form": "8-K", "filed": None, "url": "https://www.sec.gov/x.htm"},
        {"form": "8-K", "filed": "2026-11-01", "url": "javascript:alert(1)"},
        {"form": "8-K", "filed": "2026-11-01", "url": "http://www.sec.gov/x.htm"},
        {"form": "8-K", "filed": "2026-11-01"},
        None, 42, "not a filing",
        good,
    ], today=TODAY)
    assert [r["url"] for r in rows] == [good.viewer_url]
    assert disclosures.recent(None) == [] and disclosures.recent([]) == []
