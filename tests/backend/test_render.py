import re
from datetime import date, timedelta

from markupsafe import Markup

from backend import render
from backend.ledger import Fact, Ledger, Source

SEC = "https://www.sec.gov/Archives/edgar/data/320193/a"
# the owner asked for the bull / bear case and the investment thesis back; a target, a rating or an
# upside against the market stays out
FORBIDDEN = re.compile(r"\b(rating|target price|price target|upside|downside)\b|\bTP:", re.IGNORECASE)
CJK = re.compile(r"[　-ヿ㐀-䶿一-鿿豈-﫿＀-￯]")
ALL_SECTIONS = {"overview": "<p>An overview.</p>", "results": "<p>Results text.</p><p>Second paragraph.</p>",
                "financial_position": "<p>Position text.</p>", "cash_flow": "<p>Cash text.</p>"}


def _ledger():
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", SEC, "Form 10-K, filed 2024-11-01", "2024-11-01"))
    lg.set_period_end("FY2024", "2024-09-28")
    lg.set_period_end("FY2023", "2023-09-30")
    lg.add_fact(Fact("revenue", "FY2024", 391035000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("revenue", "FY2023", 383285000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("operating_income", "FY2024", 123216000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("net_income", "FY2024", 93736000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("total_assets", "2024-09-28", 364980000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("total_assets", "2023-09-30", 352583000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("shareholders_equity", "2024-09-28", -5000000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("long_term_debt", "2024-09-28", 85750000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("shares_outstanding", "2024-09-28", 15116786000, "shares", source_ids=(sid,)))
    m = lg.add_fact(Fact("operating_margin", "FY2024", 123216000000 / 391035000000, "ratio",
                         inputs=(("operating_income", "FY2024"), ("revenue", "FY2024")),
                         formula="operating_income / revenue"))
    lg.add_fact(Fact("debt_to_equity", "FY2024", None, "ratio",
                     inputs=(("long_term_debt", "2024-09-28"), ("shareholders_equity", "2024-09-28")),
                     formula="long_term_debt / shareholders_equity at year end",
                     note="shareholders' equity is negative"))
    return lg, m


def _bars():
    """Daily bars ending 2024-06-28: an old spike (outside the 52 weeks) and a known range inside."""
    end = date(2024, 6, 28)
    bars = [{"date": (end - timedelta(days=500)).isoformat(), "open": 500, "high": 510.0, "low": 495.0,
             "close": 500.0, "volume": 1e6}]
    for i in range(300, -1, -1):
        d = end - timedelta(days=i)
        bars.append({"date": d.isoformat(), "open": 180, "high": 190.0 if i == 40 else 185.0,
                     "low": 170.0 if i == 80 else 175.0, "close": 180.0, "volume": 2e6})
    return bars


def _context(**over):
    lg, m = _ledger()
    kw = dict(job={"job_id": "a" * 32},
              company={"name": "Apple Inc.", "ticker": "AAPL", "cik": "320193", "details": {}},
              ledger=lg, sections={"overview": "<p>Overview of <b>it</b>.</p>", "results": "<p>Revenue was given.</p>",
                                   "financial_position": "<p>Position.</p>"},
              withheld=[], bars=[], previous_close=None, peers=[{"ticker": "MSFT"}], notes=["A note."])
    kw.update(over)
    return render.build_context(**kw), lg, m


def _page(**over):
    ctx, lg, m = _context(**over)
    return render.html(ctx), lg, m


def test_structure_follows_the_original():
    page, _, _ = _page()
    assert 'class="dashboard"' in page and 'class="header"' in page and 'class="ticker-box">AAPL<' in page
    assert 'class="top-section"' in page and 'class="top-left"' in page and "kpi-sidebar" in page
    assert 'class="charts"' in page and 'class="dense-table statements' in page
    assert 'class="bottom-grid"' in page and page.count('<div class="col">') == 2
    assert "width: 210mm" in page and "@media screen and (max-width: 640px)" in page
    assert "Apple Inc. (AAPL) Research Dashboard" in page and "A note." in page


def test_figures_are_cited_and_missing_ones_say_so():
    page, lg, m = _page()
    assert re.search(r'<a class="src" href="https://www\.sec\.gov[^"]*"[^>]*>\$391\.0 billion</a>', page)
    assert "$365.0 billion" in page
    # no dividends in the ledger: the sidebar says so in words, never a zero
    assert re.search(r'DPS</span>\s*<span class="sidebar-metric-value"><span class="na">'
                     r'Not available in the sources</span>', page)
    cid = lg.calc_id(m)
    assert page.count(f'id="{cid}"') == 1 and f'href="#{cid}"' in page
    # a ratio without a value links to its calculation, whose entry gives the reason
    assert 'id="calc-debt_to_equity-FY2024"' in page and "shareholders&#39; equity is negative" in page
    for href in re.findall(r'href="([^"]*)"', page):
        assert href.startswith("https://") or href.startswith("#calc-"), href


def test_context_carries_figures_as_cited_markup():
    ctx, _, _ = _context()
    d = ctx["dashboard"]
    revenue = d["kpi_ribbon"]["headline"][0]["value"]
    assert isinstance(revenue, Markup) and 'class="src"' in revenue
    assert all(isinstance(c, Markup) for row in d["income_statement"]["rows"] for c in row["cells"])
    for key in ("company_header", "kpi_ribbon", "narrative_outlook", "charts_data", "income_statement",
                "capital_structure_section", "column_3_market", "scenarios", "risk_themes", "sources",
                "calculations", "withheld", "footer_disclosures", "report_metadata"):
        assert key in d


def test_sources_and_calculations_lists():
    page, lg, _ = _page()
    assert ">Sources (1) <" in page and 'class="dense-table sources"' in page and 'id="source-S1"' in page
    assert "Form 10-K, filed 2024-11-01" in page
    n_calc = sum(1 for f in lg.facts() if f.is_computed)
    assert f">Calculations ({n_calc}) <" in page and 'class="dense-table calc-table stack-phone"' in page
    assert "Operating income ÷ revenue" in page
    assert page.count('class="calc-entry"') == sum(1 for f in lg.facts() if f.is_computed)


def test_narrative_titles_and_gaps():
    page, _, _ = _page(sections=ALL_SECTIONS)
    for title in ("Company Profile", "Business Performance", "Financial Position", "Cash Flow"):
        assert f"<strong>{title}</strong> — " in page
    assert "Second paragraph." in page and "Not available for this report" not in page
    page, _, _ = _page()
    assert "Not available for this report (cash flow)." in page
    page, _, _ = _page(sections={"overview": "<p>Kept.</p>", "results": ""})
    assert "Not included: this part could not be confirmed against the sources (business performance)." in page
    assert "Not available for this report (financial position, cash flow)." in page


def test_withheld_sentences_are_listed():
    page, _, _ = _page(withheld=["Revenue was [figure] or more."])
    assert ">Withheld (1) <" in page and "Revenue was [figure] or more." in page
    page, _, _ = _page()
    assert ">Withheld (" not in page


def test_no_scripts_external_requests_or_japan_wording():
    page, _, _ = _page(withheld=["x"], bars=_bars(), sections=ALL_SECTIONS)
    low = page.lower()
    assert "<script" not in low and "<link" not in low and "@import" not in low and "http://" not in low
    assert "¥" not in page and "&#165;" not in page and "&yen;" not in low
    assert not CJK.search(page)
    assert not FORBIDDEN.search(page), FORBIDDEN.search(page)
    for word in ("edinet", "tse", "topix", "nikkei", "jpx", "tanshin", "ordinary profit", "ord. profit"):
        assert not re.search(rf"\b{re.escape(word)}\b", low), word


def test_stock_block_from_bars():
    page, _, _ = _page(bars=_bars())
    block = page.split(">Stock data<", 1)[1].split(">Peer benchmarking<", 1)[0]
    assert '<span class="week-high">$190.00</span>' in block and '<span class="week-low">$170.00</span>' in block
    assert "$510.00" not in page                       # outside the 52 weeks
    assert "<svg" in block and "intraday" in block and "Latest close (28 Jun 2024)" in block
    assert "Market data: Massive, end of day, 28 Jun 2024." in block
    assert "Prices are not available" not in page
    # the close appears in the stock block and at the top of the sidebar, both with the mark
    sidebar = page.split('kpi-sidebar">', 1)[1].split('<div class="charts">', 1)[0]
    assert "$180.00" in block and "$180.00" in sidebar and page.count("$180.00") == 2
    assert "Market data: Massive, end of day, 28 Jun 2024." in sidebar
    assert "52w Range (intraday)" in sidebar and "$170.00–$190.00" in sidebar


def test_previous_close_without_bars():
    page, _, _ = _page(previous_close={"date": "2024-07-01", "close": 181.5})
    assert "Latest close (1 Jul 2024)" in page and "$181.50" in page and "52-WEEK RANGE" not in page
    page, _, _ = _page()
    assert "Prices are not available in this report." in page and 'class="price-chart"' not in page


def test_scenarios_and_risk_themes():
    lg, m = _ledger()
    from backend import format as fmt
    scen = {"title": "Revenue at stated growth", "columns": ["Case", "Growth"],
            "assumptions": [{"label": "Base revenue", "value_html": fmt.cited(lg.get("revenue", "FY2024"), lg)}],
            "rows": [{"label": "Low case", "cells": ["<span>stated 1 percent</span>"]}],
            "note": "Each row applies the stated growth to the cited revenue."}
    risks = [{"title": "Supply concentration", "summary_html": "<em>Few suppliers.</em>",
              "quote": "We depend on a few suppliers.",
              "source": {"title": "Form 10-K, filed 2024-11-01", "url": SEC, "date": "2024-11-01"}}]
    ctx = render.build_context(job={}, company={"name": "Apple Inc.", "ticker": "AAPL"}, ledger=lg,
                               sections={}, withheld=[], bars=[], previous_close=None, peers=[], notes=[],
                               scenarios=scen, risk_themes=risks)
    page = render.html(ctx)
    assert "Scenario arithmetic" in page and "Arithmetic under stated assumptions, not an opinion of value." in page
    assert "Revenue at stated growth" in page and "Low case" in page and "stated 1 percent" in page
    assert "<th>Case</th><th>Growth</th>" in page and "Each row applies" in page
    assert "Supply concentration" in page and "<em>Few suppliers.</em>" in page
    assert "“We depend on a few suppliers.”" in page and f'href="{SEC}"' in page
    assert "Not part of this report." not in page and "Risk themes are not available" not in page

    page, _, _ = _page(scenarios=None, risk_themes=[])
    assert "Scenario arithmetic" in page and "Not part of this report." in page
    assert "Risk themes are not available for this report." in page


def test_peers_strings_and_dicts():
    page, _, _ = _page(peers=["GOOGL", {"ticker": "MSFT", "name": "Microsoft Corporation",
                                         "cells": {"Revenue": "<a class=\"src\" href=\"https://www.sec.gov/x\">$1.0</a>"}}])
    block = page.split(">Peer benchmarking<", 1)[1].split(">Corporate info<", 1)[0]
    assert "GOOGL" in block and "MSFT – Microsoft Corporation" in block and "<th>Revenue</th>" in block
    assert 'href="https://www.sec.gov/x"' in block
    page, _, _ = _page(peers=[])
    assert "No named peer table for this company." in page


def test_corporate_info_from_details():
    details = {"sic_description": "ELECTRONIC COMPUTERS", "sic_code": "3571", "primary_exchange": "XNAS",
               "list_date": "1980-12-12", "homepage_url": "http://insecure.example", "total_employees": 161000,
               "market_cap": 3.4e12, "address": {"address1": "One Apple Park Way", "city": "Cupertino",
                                                  "state": "CA", "postal_code": "95014"}}
    page, _, _ = _page(company={"name": "Apple Inc.", "ticker": "AAPL", "cik": "320193", "details": details})
    assert "Nasdaq" in page and "Electronic Computers (SIC 3571)" in page and "12 Dec 1980" in page
    assert "ELECTRONIC COMPUTERS" not in page
    assert "One Apple Park Way, Cupertino, CA 95014" in page
    assert "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=320193" in page
    assert "insecure.example" not in page                  # not an https link
    info = page.split(">Corporate info<", 1)[1]
    assert re.search(r"Employees</td><td[^>]*>161,000 <span class=\"ref-mark\">\(Massive\)</span>", info)
    assert re.search(r"Market cap</td><td[^>]*>\$3\.4 trillion <span class=\"ref-mark\">\(Massive\)</span>", info)


def test_old_arguments_still_work():
    lg, _ = _ledger()
    ctx = render.build_context(job={"job_id": "a" * 32}, company={"name": "Apple Inc.", "ticker": "AAPL"},
                               ledger=lg, sections={"results": "<p>Revenue was given.</p>"}, withheld=[],
                               bars=[], previous_close=None, peers=[{"ticker": "MSFT"}], notes=[])
    page = render.html(ctx)
    assert "Not part of this report." in page and "Risk themes are not available for this report." in page


def test_empty_ledger_renders():
    page = render.html(render.build_context(job={}, company={"ticker": "ZZZZ"}, ledger=Ledger(), sections={},
                                            withheld=[], bars=[], previous_close=None, peers=[], notes=[]))
    assert "Statements not available" in page and 'class="dashboard"' in page
    assert "Not available for this report (company profile, business performance, financial position, cash flow)." in page


# ---- the blocks the owner asked back (round 2) ------------------------------------------------
def _cited(lg, key, period):
    from backend import format as fmt
    return fmt.cited(lg.get(key, period), lg)


def _inputs(lg):
    """Every new input, filled the way the feeding modules shape them."""
    from backend.analysis import multiples
    thesis = {
        "thesis": [{"title": "Scale", "html": f"Revenue reached {_cited(lg, 'revenue', 'FY2024')}.", "method": "code"},
                   {"title": "Margins", "html": f"The operating margin was {_cited(lg, 'operating_margin', 'FY2024')}.",
                    "method": "model"}],
        "bull": [{"html": f"Revenue rose to {_cited(lg, 'revenue', 'FY2024')}.", "method": "code",
                  "signal": "revenue_growth", "rule": "Revenue growth above 0% & rising"}],
        "bear": [{"html": "Shareholders' equity was negative at the year end.", "method": "model",
                  "signal": "negative_equity", "rule": "Equity below zero"}],
        "withheld": [], "method": "rules", "counts": {"favourable": 1, "unfavourable": 1}}
    scenarios = {
        "title": "Two-stage free cash flow arithmetic", "period": "fiscal 2024",
        "assumptions": [{"label": "Base revenue", "value_html": _cited(lg, "revenue", "FY2024")}],
        "columns": ["Discount rate", "2% terminal"], "rows": [{"label": "discount rate 9.0%", "cells": ["$1.9 trillion"]}],
        "note": "Each cell applies the stated rates to the cited free cash flow.",
        "cases": [{"key": "bear", "label": "Bear case", "growth_text": "1.0%", "assumption": "Growth at the low end",
                   "low": 1.2e12, "base": 1.5e12, "high": 1.8e12,
                   "low_text": "$1.2 trillion", "base_text": "$1.5 trillion", "high_text": "$1.8 trillion"},
                  {"key": "base", "label": "Base case", "growth_text": "3.1%", "assumption": "Growth at the blended CAGR",
                   "low": 1.9e12, "base": 2.3e12, "high": 2.8e12,
                   "low_text": "$1.9 trillion", "base_text": "$2.3 trillion", "high_text": "$2.8 trillion"},
                  {"key": "bull", "label": "Bull case", "growth_text": "6.0%", "assumption": "Growth at the high end",
                   "low": 2.9e12, "base": 3.4e12, "high": None,
                   "low_text": "$2.9 trillion", "base_text": "$3.4 trillion", "high_text": None}],
        "market": {"enterprise_value": 2.8e12, "text": "$2.8 trillion",
                   "note": "Market enterprise value = market cap + net debt, end of day (Massive)."}}
    peer_table = {
        "columns": [["revenue", "Revenue"], ["operating_margin", "EBIT %"], ["price_to_earnings", "P/E"]],
        "rows": [{"ticker": "MSFT", "name": "Microsoft Corporation", "period_label": "fiscal 2024",
                  "cells": {"revenue": '<a class="src" href="https://www.sec.gov/msft">$245.1 billion</a>',
                            "operating_margin": "44.6%", "price_to_earnings": "35.0x"}, "values": {}, "error": None},
                 {"ticker": "DELL", "name": "Dell Technologies", "period_label": None, "cells": {}, "values": {},
                  "error": "No SEC data could be fetched for DELL"}],
        "medians": {"revenue": {"text": None, "n": 0}, "operating_margin": {"text": "44.6%", "n": 1},
                    "price_to_earnings": {"text": "35.0x", "n": 1}},
        "note": "Peers' figures link to their own filings."}
    disclosures = [{"date": "2024-11-01", "date_text": "1 Nov 2024", "form": "10-K", "title": "Annual report",
                    "detail": "Fiscal 2024 annual report", "url": SEC},
                   {"date": "2024-08-02", "date_text": "2 Aug 2024", "form": "8-K", "title": "Current report",
                    "detail": None, "url": "http://not-https.example"}]
    review = {"sentences": 12, "confirmed_by_both": 10, "rejected": 2, "abstained_only": 0, "reviewers_answered": 2}
    risks = [{"title": "Supply concentration", "summary_html": "Few suppliers.", "quote": "We depend on a few suppliers.",
              "source": {"title": "Form 10-K, filed 2024-11-01, Item 1A", "url": SEC, "date": "2024-11-01"}}]
    mult = multiples.compute(lg, price=180.0, price_date="2024-06-28")
    return dict(thesis=thesis, scenarios=scenarios, peer_table=peer_table, disclosures=disclosures,
                review=review, risk_themes=risks, multiples=mult, valuation=_valuation_input(lg),
                news=dict(NEWS), release=dict(RELEASE))


DETAILS = {"description": "Apple designs <b>phones</b>. It sells services. It also runs stores.",
           "market_cap": 3.4e12, "total_employees": 161000}


def _full(**over):
    lg, m = _ledger()
    kw = dict(job={"job_id": "b" * 32},
              company={"name": "Apple Inc.", "ticker": "AAPL", "cik": "320193", "details": dict(DETAILS)},
              ledger=lg, sections=dict(ALL_SECTIONS), withheld=["A held sentence."], bars=_bars(),
              previous_close=None, peers=["MSFT"], notes=[])
    kw.update(_inputs(lg))
    kw.update(over)
    return render.html(render.build_context(**kw)), lg


def _between(page, start, end):
    return page.split(start, 1)[1].split(end, 1)[0]


def test_a_thesis_and_bull_bear_case():
    page, lg = _full()
    top = _between(page, 'class="top-left"', 'kpi-sidebar')
    assert "<strong>Investment Thesis</strong>" in top and "BULL CASE" in top and "BEAR CASE" in top
    assert "<strong>Scale</strong> — Revenue reached <a class=\"src\"" in top      # linked, not escaped
    bull = _between(top, 'class="bull-col"', 'class="bear-col"')
    bear = _between(top, 'class="bear-col"', 'class="bullbear-note"')
    assert 'title="Revenue growth above 0% &amp; rising"' in bull and "analysis-tag" not in bull
    assert 'title="Equity below zero"' in bear and '<span class="analysis-tag"' in bear
    assert top.count('<span class="analysis-tag"') == 2                      # model thesis item + model bear point
    assert "Bull and bear points are chosen by fixed rules on the filed figures and are not a recommendation." in top
    # one side empty
    lg, _ = _ledger()
    one = dict(_inputs(lg)["thesis"], bull=[])
    page, _ = _full(thesis=one)
    assert "No rule fired on this side for the filed figures." in _between(page, 'class="bull-col"', 'class="bear-col"')
    # no thesis: no box, no heading
    page, _, _ = _page()
    assert "BULL CASE" not in page and "Investment Thesis" not in page and 'class="bullbear-note"' not in page


def test_b_sidebar_price_market_cap_and_multiples():
    page, _ = _full()
    side = _between(page, 'kpi-sidebar">', '<div class="charts">')
    assert re.search(r'Price <span class="sidebar-period">\(28 Jun 2024\)</span></span>\s*'
                     r'<span class="sidebar-price-value">\$180\.00</span>', side)
    assert re.search(r'Mkt Cap</span>\s*<span class="sidebar-metric-value" style="font-size:14px;">\$3\.4 trillion<', side)
    assert "Market data: Massive, end of day, 28 Jun 2024; market cap: Massive reference data." in side
    valuation = _between(side, ">Valuation<", ">Margins<")
    assert "P/E (FY diluted)" in valuation and "Mkt cap / revenue" in valuation
    # no diluted EPS in the ledger: the multiple says so, with the reason under it
    assert "diluted EPS for fiscal 2024 is not in the sources" in valuation
    assert re.search(r"Mkt cap / revenue</span>\s*<span class=\"sidebar-metric-value\">\d+(\.\d+)? ?x</span>", valuation)
    defs = _between(side, ">Definitions<", "</div>\n      </div>")
    assert "Market capitalisation / revenue" in defs and "Price × shares outstanding ÷ revenue" in defs
    assert "Price: $180.00, end of day 2024-06-28 (market data)" in defs
    assert re.search(r'Revenue, fiscal 2024: <a class="src" href="https://www\.sec\.gov', defs)
    # without a price and multiples: today's sidebar (revenue headline, no valuation group)
    page, _, _ = _page()
    side = _between(page, 'kpi-sidebar">', '<div class="charts">')
    assert "Revenue <span class=\"sidebar-period\">(fiscal 2024)</span>" in side and ">Valuation<" not in side
    assert "52w Range" not in side and "Mkt Cap" not in side


def test_c_football_field():
    page, _ = _full(valuation=None)
    panel = _between(page, 'class="val-panel scenario-panel"', ">Capital allocation<")
    assert "<strong>Valuation</strong>" in panel
    assert "Scenario arithmetic under stated assumptions · enterprise value · not an opinion of value" in panel
    assert panel.count('class="val-row') == 3 and panel.count('class="val-dot"') == 3
    assert panel.count('class="val-band') == 2                     # the bull case has no high: no band
    assert 'class="val-row val-row-primary"' in panel and "val-band-primary" in panel
    assert 'class="val-current-line"' in panel and "Market enterprise value $2.8 trillion" in panel
    axis = _between(panel, 'class="val-axis">', "</div>")
    assert axis.count("<span>") == 3 and "trillion" in axis
    cases = _between(panel, "val-cases", "</table>")
    assert '<td style="white-space:nowrap;">Bear case</td>' in cases and "3.1%" in cases and "Growth at the blended CAGR" in cases
    assert "$2.3 trillion" in cases and 'title="Not available in the sources">n/a' in cases
    assert "Two-stage free cash flow arithmetic (fiscal 2024)" in panel and "discount rate 9.0%" in panel
    visible = re.sub(r"<[^>]+>", " ", panel)                     # text only, not target="_blank"
    assert not re.search(r"(?i)\btarget\b|\bTP\b|%\s*(above|below)|upside|downside", visible)
    # no cases: today's scenario panel
    lg, _ = _ledger()
    plain = {k: v for k, v in _inputs(lg)["scenarios"].items() if k not in ("cases", "market")}
    page, _ = _full(scenarios=plain, valuation=None)
    assert "<strong>Scenario arithmetic</strong>" in page and "val-field" not in page.split("</style>", 1)[1]
    assert "Arithmetic under stated assumptions, not an opinion of value." in page


def test_d_peer_table():
    page, _ = _full()
    block = _between(page, ">Peer benchmarking<", ">Corporate info<")
    rows = re.findall(r"<tr[^>]*>.*?</tr>", _between(block, "<tbody>", "</tbody>"), re.S)
    assert len(rows) == 3 and 'class="peer-own"' in rows[0] and "AAPL – Apple Inc." in rows[0]
    assert re.search(r'<a class="src" href="https://www\.sec\.gov[^"]*"[^>]*>\$391\.0 billion</a>', rows[0])
    assert 'href="#calc-operating_margin-FY2024"' in rows[0]          # own ratio links to its calculation
    assert "MSFT – Microsoft Corporation" in rows[1] and 'href="https://www.sec.gov/msft"' in rows[1]
    assert '<td class="peer-error" colspan="3">No SEC data could be fetched for DELL</td>' in rows[2]
    assert "<strong>Medians</strong> — EBIT % 44.6%" in block and "P/E 35.0x" in block
    assert "Medians</strong> — Revenue" not in block                 # no text, not shown
    assert "Peers&#39; figures link to their own filings." in block
    page, _, _ = _page(peers=["GOOGL"])
    assert "GOOGL" in _between(page, ">Peer benchmarking<", ">Corporate info<") and 'class="peer-own"' not in page


def test_e_risk_dashboard():
    page, _ = _full()
    dash = _between(page, ">Risk dashboard<", ">Risk themes ")
    assert '<span class="chip-watch">[WATCH]</span> <strong>Equity below zero</strong>: Shareholders' in dash
    assert '<span class="chip-filed">[FILED]</span> <strong>Supply concentration</strong>: see Risk Themes below.' in dash
    page, _, _ = _page()
    assert ">Risk dashboard<" not in page


def test_f_key_disclosures():
    page, _ = _full()
    foot = _between(page, "KEY DISCLOSURES (12 mo):", 'class="meta-line"')
    assert f'1 Nov 2024 — <span class="disc-kind">10-K</span> <a class="src" href="{SEC}"' in foot
    assert "Fiscal 2024 annual report" in foot
    assert "not-https.example" not in foot and "Current report" in foot   # shown, not linked
    page, _ = _full(disclosures=[])
    assert "None in the last 12 months." in page
    page, _, _ = _page()                                                 # None: the ledger's own filings
    assert "Coverage: filings listed are the SEC EDGAR filings" in page


def test_g_company_profile_description():
    page, _ = _full()
    profile = _between(page, 'id="narr-overview"', 'id="narr-results"')
    assert ("<strong>Company Profile</strong> — Apple designs &lt;b&gt;phones&lt;/b&gt;. It sells services. "
            '<span class="desc-mark">(Company description: Massive)</span></p>') in profile
    assert "It also runs stores." not in profile and '<p class="narr-p">An overview.</p>' in profile
    page, _, _ = _page()
    assert "Company description" not in page


def test_h_review_line():
    page, _ = _full()
    assert "Self-check: 12 sentences read by two independent reviewers, 2 removed." in page
    page, _ = _full(review={"sentences": 5, "rejected": 0, "reviewers_answered": 0})
    assert "Self-check did not run." in page
    page, _, _ = _page()
    assert "Self-check did not run." in page


def test_full_page_links_escaping_and_wording():
    page, lg = _full()
    ids = set(re.findall(r'id="([^"]+)"', page))
    for href in re.findall(r'href="([^"]*)"', page):
        assert href.startswith("https://") or (href.startswith("#") and href[1:] in ids), href
    for twice in ("&amp;lt;", "&amp;gt;", "&amp;amp;", "&amp;#", "&amp;quot;", "&lt;a ", "&lt;span"):
        assert twice not in page, twice
    low = page.lower()
    assert "<script" not in low and "<link" not in low and "http://" not in low and "¥" not in page
    assert not CJK.search(page) and not FORBIDDEN.search(page), FORBIDDEN.search(page)


def test_no_sideways_overflow(tmp_path):
    page_html, _ = _full()
    target = tmp_path / "report.html"
    target.write_text(page_html, encoding="utf-8")

    def run(browser):
        for width in (1100, 390):
            tab = browser.new_page(viewport={"width": width, "height": 900})
            tab.goto(target.as_uri())
            for toggle in ("sources", "calcs", "withheld", "grid"):      # opened, too
                tab.locator(f'label[for="fold-{toggle}-toggle"]').click()
            scroll, client = tab.evaluate(
                "[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            assert scroll <= client, (width, scroll, client)
            tab.close()

    _with_browser(run)


def test_formula_words_keep_keys_with_digits_and_acronyms():
    assert render._formula_words("revenue / revenue_cagr_2y - 1").startswith("Revenue ÷ revenue CAGR, 2 years") \
        or render._formula_words("revenue / revenue_cagr_2y - 1") == "Revenue ÷ revenue cagr 2y − 1"
    assert render._formula_words("price x shares_outstanding / revenue") == "Price × shares outstanding ÷ revenue"


def test_a_filed_bear_point_is_not_repeated_in_the_risk_dashboard():
    from backend import render
    view = {"bear": [{"html": "ROE fell.", "method": "code", "signal": "roe_down", "rule": "Return on equity fell"},
                     {"html": "The company states: x", "method": "filed", "signal": "risk_theme", "rule": "A filed risk"}]}
    rows = render._risk_dashboard(view, [{"title": "Supply chain"}])
    assert [(r["chip"], r["name"]) for r in rows] == [("WATCH", "Return on equity fell"), ("FILED", "Supply chain")]
    # the page passes the points on without their method: the signal name marks a quoted risk too
    view = {"bear": [{"html": "ROE fell.", "signal": "roe_down", "rule": "Return on equity fell"},
                     {"html": "The company states: x", "signal": "risk_theme", "rule": "A filed risk"}]}
    assert [r["chip"] for r in render._risk_dashboard(view, [{"title": "Supply chain"}])] == ["WATCH", "FILED"]


# ---- round 3: valuation methods, news, management commentary, collapsed sections ---------------
NEWS = {"articles": [{"id": "N1", "title": "Apple <unveils> new chips", "publisher": "Reuters", "date": "2024-06-20",
                      "date_text": "20 Jun 2024", "url": "https://news.example.com/a", "summary": "Chip coverage.",
                      "sentiment": "positive"},
                     {"id": "N2", "title": "Supplier note", "publisher": "Bloomberg", "date": "2024-06-18",
                      "date_text": "18 Jun 2024", "url": "http://insecure.example/b", "summary": None, "sentiment": None}],
        "topics": [{"title": "Product launches", "summary_html": "Coverage of <em>new chips</em>.", "articles": ["N1", "N9"]}],
        "method": "model", "provider": "Massive", "window_text": "the last 45 days"}
RELEASE = {"title": "Results release", "form": "8-K", "filed_text": "1 Aug 2024", "url": SEC,
           "source_title": "Form 8-K, filed 2024-08-01, Exhibit 99.1",
           "statements": [{"topic": "Results", "quote": "• Revenue was a June quarter record.",
                           "summary_html": "Management called the quarter <em>a record</em>."},
                          {"topic": "Outlook", "quote": "We expect growth to continue.", "summary_html": ""}],
           "method": "model"}
BANNED = re.compile(r"\b(target|upside|downside|undervalued|overvalued|rating|price target)\b", re.IGNORECASE)


def _valuation_input(lg):
    eps = _cited(lg, "revenue", "FY2024")
    method = dict(reason=None, n_peers=None, weight=None, share=None, share_text=None, note=None)
    return {
        "period_label": "fiscal 2024", "price": 180.0, "price_text": "$180.00", "price_date_text": "28 Jun 2024",
        "shares_text": "15.1 billion shares", "shares_note": "as of 28 Sep 2024",
        "methods": [
            dict(method, key="dcf", label="DCF (two-stage)", basis="free cash flow, two stages", inputs_html=f"Revenue {eps}",
                 value=152.3, low=131.0, high=172.9, value_text="$152.30", range_text="$131.00 – $172.90",
                 weight=30, share=0.42, share_text="42%"),
            dict(method, key="pe_peer", label="P/E peer relative", basis="peer median P/E × diluted EPS",
                 inputs_html="EPS <b>$6.08</b>", value=201.5, low=170.0, high=230.0, value_text="$201.50",
                 range_text="$170.00 – $230.00", n_peers=5, weight=20, share=0.33, share_text="33%",
                 note="Peers: MSFT, GOOGL & DELL."),
            dict(method, key="ev_sales_peer", label="EV/Sales peer relative", basis="peer median EV/Sales",
                 inputs_html="", value=240.0, low=200.0, high=280.0, value_text="$240.00",
                 range_text="$200.00 – $280.00", n_peers=5, weight=10, share=0.25, share_text="25%"),
            dict(method, key="graham", label="Graham number", basis="square root of 22.5 × EPS × BPS",
                 inputs_html="", value=None, low=None, high=None, value_text=None, range_text=None,
                 reason="book value per share is negative")],
        "blend": {"value": 190.0, "low": 160.0, "high": 220.0, "value_text": "$190.00",
                  "range_text": "$160.00 – $220.00", "vs_price": 0.056, "vs_price_text": "+5.6%",
                  "basis": "share-weighted average of the 3 priced methods"},
        "quality": {"score": 62, "text": "62", "parts": [{"label": "methods priced", "text": "3 of 4"},
                                                         {"label": "agreement", "text": "moderate"}]},
        "advisor": {"method": "model", "rationale_html": "Cash flows are <em>steady</em>, so the DCF carries the most weight."},
        "methodology": "Each method is computed in Python from the cited figures; the advisor only sets weights.",
        "priced": 3, "total": 4}


def _visible_text(page):
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", page, flags=re.S))


def test_valuation_methods_panel():
    page, lg = _full()
    panel = _between(page, 'class="val-panel scenario-panel val-wide valuation-methods"', ">Capital allocation<")
    head = _between(panel, 'class="val-header">', "</div>")
    assert "<strong>Valuation</strong>" in head
    assert '<span class="val-pill">MODEL VALUE: $190.00 (+5.6% vs last close)</span>' in head
    assert 'class="val-quality-fill" style="width:62%; background:#cc8800;"' in head and "> 62</span>" in head
    assert "3 priced of 4 models" in head and 'title="methods priced: 3 of 4; agreement: moderate"' in head
    assert "Last close $180.00, 28 Jun 2024 (Massive, end of day); shares: 15.1 billion shares (as of 28 Sep 2024)." in panel
    field = _between(panel, 'class="val-field"', 'class="val-axis"')
    labels = re.findall(r'<div class="val-label"[^>]*>([^<]+)</div>', field)
    assert labels == ["DCF (two-stage) 42%", "P/E peer relative 33%", "EV/Sales peer relative 25%", "BLENDED"]
    assert field.count("val-row-primary") == 1 and "DCF (two-stage) 42%" in _between(field, "val-row-primary", "</div>")
    assert "val-band val-band-blended" in field and "val-dot val-dot-blended" in field
    assert 'class="val-current-line"' in field and "Last close $180.00" in field
    # every position on one scale chosen from the data (the price included)
    lo, hi = render._scale([152.3, 131.0, 172.9, 201.5, 170.0, 230.0, 240.0, 200.0, 280.0, 190.0, 160.0, 220.0, 180.0])
    assert f'class="val-dot" style="left: {round((152.3 - lo) / (hi - lo) * 100, 2)}%;"' in field
    assert f"* {round((180.0 - lo) / (hi - lo) * 100, 2)} / 100" in field
    axis = _between(panel, 'class="val-axis">', "</div>")
    assert re.findall(r"<span>([^<]+)</span>", axis) == [render._per_share_text(lo),
                                                          render._per_share_text((lo + hi) / 2), render._per_share_text(hi)]
    table = _between(panel, "valuation-methods-table", "</table>")
    assert "<th>Method</th><th>Basis</th><th>Inputs</th><th>Value ($)</th><th>Range ($)</th><th>Blend share</th>" in table
    rows = re.findall(r"<tr[^>]*>.*?</tr>", _between(table, "<tbody>", "</tbody>"), re.S)
    assert [re.search(r"<td>([^<]+)</td>", r).group(1) for r in rows] == [
        "DCF (two-stage)", "P/E peer relative", "EV/Sales peer relative", "Graham number", "BLENDED"]
    assert 'class="method-primary"' in rows[0] and "EPS <b>$6.08</b>" in rows[1] and "(n=5 peers)" in rows[1]
    assert "Peers: MSFT, GOOGL &amp; DELL." in rows[1] and 'title="advisor weight 20"' in rows[1]
    assert 'class="method-na"' in rows[3] and "n/a — book value per share is negative" in rows[3]
    assert 'class="method-blended"' in rows[4] and "$190.00" in rows[4] and "100%" in rows[4]
    assert ('<div class="val-method-note"><strong class="advisor-label">AI advisor</strong> — '
            "Cash flows are <em>steady</em>, so the DCF carries the most weight.</div>") in panel
    assert "the advisor only sets weights." in panel
    assert "Model arithmetic under stated assumptions. It informs; it is not a recommendation." in panel
    # the scenario cases follow, and the grid is collapsed under its own header
    assert "Scenario arithmetic — Two-stage free cash flow arithmetic (fiscal 2024)" in panel and "val-cases" in panel
    lg2, _ = _ledger()
    same = dict(_inputs(lg2)["scenarios"], title="Scenario arithmetic")
    page2, _ = _full(scenarios=same)
    assert "Scenario arithmetic — Scenario arithmetic" not in page2 and "Scenario arithmetic (fiscal 2024)" in page2
    assert 'for="fold-grid-toggle">Scenario grid and assumptions' in panel
    assert "discount rate 9.0%" in panel.split('id="fold-grid-body"', 1)[1]
    assert not BANNED.search(_visible_text(page)), BANNED.search(_visible_text(page))


def test_valuation_variants():
    lg, _ = _ledger()
    v = _valuation_input(lg)
    v["advisor"] = {"method": "default", "rationale_html": "Equal weights."}
    v["blend"] = dict(v["blend"], value=None, value_text=None)
    page, _ = _full(valuation=v)
    assert "MODEL VALUE" not in page and "Default weights</strong> — Equal weights." in page
    v["advisor"] = {"method": "model", "rationale_html": None}
    page, _ = _full(valuation=v)
    assert 'class="val-method-note"' not in page
    v["blend"] = dict(v["blend"], low=None, high=None)            # no blend at all: no empty BLENDED row
    page, _ = _full(valuation=v)
    assert "val-row-blended" not in page
    # no valuation: the scenario panel of round 2 stays
    page, _ = _full(valuation=None)
    assert "valuation-methods" not in page and "Market enterprise value" in page and "MODEL VALUE" not in page
    assert 'for="fold-grid-toggle"' in page                     # its grid is collapsed too


def test_recent_news():
    page, _ = _full()
    assert page.index(">Risk themes ") < page.index(">Recent news ")
    news = _between(page, ">Recent news ", 'class="appendix"')
    assert '<span class="dh-sub">(web, the last 45 days)</span>' in news
    assert ('<div class="news-topic"><strong>Product launches</strong> — Coverage of <em>new chips</em>. '
            '<span class="news-refs">(<a href="#news-N1">N1</a>)</span></div>') in news   # N9 is not an article
    assert 'id="news-N1"' in news and '<span class="disc-kind">Reuters</span>' in news
    assert '<a class="src" href="https://news.example.com/a"' in news and "Apple &lt;unveils&gt; new chips</a>" in news
    assert '<span class="news-sent">Massive: positive</span>' in news
    assert "insecure.example" not in page and "Supplier note" in news            # shown, not linked
    assert "News is third-party web coverage found through Massive; it is not checked against the filings." in news
    assert "web coverage through Massive" in _between(page, "Coverage:", "</div>")
    for missing in (None, dict(NEWS, articles=[])):
        page, _ = _full(news=missing)
        assert ">Recent news " not in page and "web coverage through" not in page


def test_management_commentary():
    page, _ = _full()
    assert page.index('class="dense-table statements') < page.index(">Management commentary") < page.index('class="bottom-grid"')
    block = _between(page, ">Management commentary", 'class="bottom-grid"')
    assert "latest results release <span class=\"dh-sub\">(1 Aug 2024)</span>" in block
    assert '<span class="disc-kind">Results</span> Management called the quarter <em>a record</em>.' in block
    assert '<div class="risk-quote">“Revenue was a June quarter record.”</div>' in block      # bullet glyph dropped
    assert '<span class="disc-kind">Outlook</span>' in block and "“We expect growth to continue.”" in block
    assert block.count(f'href="{SEC}"') == 1 and "Form 8-K, filed 2024-08-01, Exhibit 99.1" in block
    assert "Quotes are the company&#39;s own words from the release; they are not checked against later filings." in block
    for missing in (None, dict(RELEASE, statements=[])):
        page, _ = _full(release=missing)
        assert ">Management commentary" not in page


def test_collapsed_sections_markup():
    page, lg = _full()
    css = page.split("</style>", 1)[0]
    toggle_rule = re.search(r"\.fold-toggle \{([^}]*)\}", css).group(1)
    assert "display: none" not in toggle_rule and "opacity: 0" in toggle_rule      # hidden, still focusable
    assert ".fold-body:has(:target)" in css and ".fold-toggle:checked ~ .fold-body" in css
    assert re.search(r"@media print \{[^@]*\.fold-body \{ display: block !important; \}", css)
    n_calc = sum(1 for f in lg.facts() if f.is_computed)
    for key, text in (("sources", f"Sources ({len(lg.sources())})"), ("calcs", f"Calculations ({n_calc})"),
                      ("withheld", "Withheld (1)"), ("grid", "Scenario grid and assumptions")):
        assert f'<input type="checkbox" class="fold-toggle" id="fold-{key}-toggle">' in page
        assert re.search(rf'<label class="fold-head [^"]*" for="fold-{key}-toggle"[^>]*>{re.escape(text)} ', page)
        assert f'id="fold-{key}-body"' in page
    assert page.count('<span class="fold-show">show</span><span class="fold-hide">hide</span>') == 4
    assert not re.search(r"<input[^>]*\bchecked\b", page)                      # all closed at load


def _with_browser(test):
    sync = __import__("pytest").importorskip("playwright.sync_api")
    try:
        with sync.sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                test(browser)
            finally:
                browser.close()
    except AssertionError:
        raise
    except Exception as exc:                      # no browser installed: nothing to measure
        __import__("pytest").skip(f"no headless browser: {exc}")


def test_collapsed_sections_in_a_browser(tmp_path):
    page_html, lg = _full()
    target = tmp_path / "report.html"
    target.write_text(page_html, encoding="utf-8")

    def run(browser):
        tab = browser.new_page(viewport={"width": 1100, "height": 900})
        tab.goto(target.as_uri())
        row = tab.locator("#calc-operating_margin-FY2024")
        for body in ("#fold-sources-body", "#fold-calcs-body", "#fold-withheld-body", "#fold-grid-body"):
            assert not tab.locator(body).is_visible(), body                    # closed at load
        assert not row.is_visible()
        # a calculated figure's link opens Calculations and lands on its row
        tab.locator('a.calc[href="#calc-operating_margin-FY2024"]').first.click()
        tab.wait_for_timeout(100)
        assert row.is_visible()
        box, height = row.bounding_box(), tab.viewport_size["height"]
        assert box is not None and 0 <= box["y"] < height, box
        # a click on the header opens, a second closes
        tab.goto(target.as_uri())
        tab.locator('label[for="fold-sources-toggle"]').click()
        assert tab.locator("#fold-sources-body").is_visible()
        assert "hide" in tab.locator('label[for="fold-sources-toggle"] .fold-hint').inner_text()
        tab.locator('label[for="fold-sources-toggle"]').click()
        assert not tab.locator("#fold-sources-body").is_visible()
        # keyboard: the header's control takes focus and Space toggles it
        tab.focus("#fold-withheld-toggle")
        tab.keyboard.press("Space")
        assert tab.locator("#fold-withheld-body").is_visible()
        # print shows everything
        tab.goto(target.as_uri())
        tab.emulate_media(media="print")
        for body in ("#fold-sources-body", "#fold-calcs-body", "#fold-withheld-body", "#fold-grid-body"):
            assert tab.locator(body).is_visible(), body
        tab.close()

    _with_browser(run)


# ---- round 4: the reviewers' findings ------------------------------------------------------------
def _bank_ledger():
    """A bank: negative operating cash flow, no gross profit / operating income / capex, an old
    year-end share count and a newer cover-page count, and an equity gap (preferred stock)."""
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", SEC, "Form 10-K, filed 2026-02-13", "2026-02-13"))
    old = lg.add_source(Source("x", "edinet", SEC + "/old", "Form 10-Q, filed 2009-11-06", "2009-11-06"))
    lg.set_period_end("FY2025", "2025-12-31")
    lg.set_period_end("FY2024", "2024-12-31")
    lg.set_period_end("FY2008", "2008-12-31")
    for key, fy25, fy24 in (("revenue", 182.4e9, 177.6e9), ("net_income", 57.0e9, 58.5e9),
                            ("operating_cash_flow", -147.8e9, -42.0e9)):
        lg.add_fact(Fact(key, "FY2025", fy25, "USD", source_ids=(sid,)))
        lg.add_fact(Fact(key, "FY2024", fy24, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("eps_diluted", "FY2025", 20.02, "USD/share", source_ids=(sid,)))
    lg.add_fact(Fact("total_assets", "2025-12-31", 4424.9e9, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("total_liabilities", "2025-12-31", 4012.5e9, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("shareholders_equity", "2025-12-31", 362.4e9, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("shareholders_equity", "2024-12-31", 344.8e9, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("shares_outstanding", "2025-12-31", 2.6962e9, "shares", source_ids=(sid,)))
    lg.add_fact(Fact("shares_outstanding", "2026-01-31", 2.6556e9, "shares", source_ids=(sid,)))
    for fy, end, rev in (("FY2023", "2023-12-31", 158.1e9), ("FY2022", "2022-12-31", 128.7e9),
                         ("FY2021", "2021-12-31", 121.6e9)):
        lg.set_period_end(fy, end)
        lg.add_fact(Fact("revenue", fy, rev, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("net_income", "FY2008", 5.6e9, "USD", source_ids=(old,)))
    lg.add_fact(Fact("revenue", "FY2008", 67.3e9, "USD", source_ids=(old,)))
    lg.add_fact(Fact("net_margin", "FY2008", 5.6 / 67.3, "ratio", inputs=(("net_income", "FY2008"), ("revenue", "FY2008")),
                     formula="net_income / revenue"))
    for fy in ("FY2025", "FY2024"):
        lg.add_fact(Fact("net_margin", fy, lg.get("net_income", fy).value / lg.get("revenue", fy).value, "ratio",
                         inputs=(("net_income", fy), ("revenue", fy)), formula="net_income / revenue"))
    return lg


BANK_MULTIPLES = [
    {"key": "price_to_book", "label": "Price / book value", "value": 2.27, "text": "2.27x", "reason": None,
     "formula": "price x shares_outstanding / shareholders_equity", "inputs": [], "price_note": "Price: $310.53"},
    {"key": "market_cap_to_revenue", "label": "Market capitalisation / revenue", "value": None,
     "text": "Not used for a bank or insurer", "reason": "revenue multiples are not used for a bank or insurer",
     "formula": "price x shares_outstanding / revenue", "inputs": [], "price_note": "Price: $310.53"},
    {"key": "price_to_earnings", "label": "Price / diluted EPS", "value": 15.5, "text": "15.5x",
     "formula": "price / eps_diluted", "inputs": [], "price_note": "Price: $310.53, end of day 2026-11-20 (market data)"},
    {"key": "market_cap_to_fcf", "label": "Market capitalisation / free cash flow", "value": None,
     "text": "Not available in the sources: free cash flow is not used for a bank or insurer",
     "formula": "price x shares_outstanding / free_cash_flow", "inputs": [], "price_note": "Price: $310.53"},
    {"key": "ev_to_operating_income", "label": "Enterprise value / operating income", "value": None,
     "text": "Not available in the sources: operating income for fiscal 2025 is not in the sources",
     "formula": "x", "inputs": [], "price_note": "Price: $310.53"}]


def _bank_page(**over):
    lg = _bank_ledger()
    kw = dict(job={}, company={"name": "JPMorgan Chase & Co.", "ticker": "JPM", "cik": "19617",
                                "details": {"sic_description": "NATIONAL COMMERCIAL BANKS", "sic_code": "6021",
                                            "name": "JPMorgan Chase & Co. Common Stock"}},
              ledger=lg, sections={}, withheld=[], bars=[], previous_close={"date": "2026-11-20", "close": 310.53},
              peers=[], notes=["The self-check removed 2 sentences.", "Peers are not available: timeout"],
              multiples=BANK_MULTIPLES, financial=True)
    kw.update(over)
    return render.html(render.build_context(**kw)), lg


def test_1_negative_cash_flow_is_red_and_signed():
    page, _ = _bank_page()
    flow = _between(page, 'class="cf-waterfall"', "</table>")
    assert 'class="bar-zero-line"' in flow
    assert re.search(r'<rect class="cf-rect neg" x="0" y="[\d.]+" width="10" height="[\d.]+" fill="#cc4444"', flow)
    assert ">-$147.8B</a>" in flow and "#0a7a0a" not in flow
    # same scale as a positive bar: heights in proportion to the absolute values
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", SEC, "Form 10-K, filed 2025-02-01", "2025-02-01"))
    lg.add_fact(Fact("operating_cash_flow", "FY2024", -100e9, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("capex", "FY2024", 50e9, "USD", source_ids=(sid,)))
    ctx = render.build_context(job={}, company={"ticker": "X"}, ledger=lg, sections={}, withheld=[], bars=[],
                               previous_close=None, peers=[], notes=[])
    bars = ctx["dashboard"]["capital_structure_section"]["cf_bars"]
    assert [b["neg"] for b in bars] == [True, False] and abs(bars[0]["h"] - 2 * bars[1]["h"]) < 0.05
    # the mini charts hang a negative year below a zero line in red
    lg = _bank_ledger()
    lg.replace_fact(Fact("net_income", "FY2024", -3e9, "USD", source_ids=("S1",)))
    page, _ = _bank_page(ledger=lg)
    chart = _between(page, "Net income ($) 5yr", 'class="chart"')
    assert 'class="bar-rect neg"' in chart and 'class="bar-zero-line"' in chart and ">-$3.0B</a>" in chart


def test_2_one_share_count():
    page, lg = _bank_page()
    stock = _between(page, ">Stock data<", ">Peer benchmarking<")
    assert "Shares Out (as of 31 Jan 2026):" in stock and ">2.7 billion shares</a>" in stock
    assert "Not available" not in _between(stock, "Shares Out", "</div>")
    # no recent count in the filings: the count the multiples used, marked as market data
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", SEC, "Form 10-K, filed 2026-02-01", "2026-02-01"))
    lg.set_period_end("FY2025", "2025-12-31")
    lg.add_fact(Fact("revenue", "FY2025", 200e9, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("shares_outstanding", "2011-04-29", 1.2e9, "shares", source_ids=(sid,)))
    mult = [{"key": "price_to_earnings", "label": "Price / diluted EPS", "value": 24.0, "text": "24.0x", "formula": "x",
             "inputs": [], "price_note": "Price: $600.00, end of day 2026-11-20 (market data)"},
            {"key": "price_to_book", "label": "Price / book value", "value": 9.0, "text": "9.0x", "formula": "x",
             "inputs": [], "price_note": "Price: $600.00, end of day 2026-11-20 (market data); shares: 2.6 billion "
                                         "shares (market data; the newest share count in the filings is as of 29 Apr 2011)"}]
    ctx = render.build_context(job={}, company={"ticker": "META"}, ledger=lg, sections={}, withheld=[], bars=[],
                               previous_close={"date": "2026-11-20", "close": 600.0}, peers=[], notes=[], multiples=mult)
    stock = _between(render.html(ctx), ">Stock data<", ">Peer benchmarking<")
    assert ">2.6 billion shares</span> <span class=\"ref-mark\">(market data, Massive)</span>" in stock
    # nothing newer either way: the newest count with its own date, never "not available"
    ctx = render.build_context(job={}, company={"ticker": "META"}, ledger=lg, sections={}, withheld=[], bars=[],
                               previous_close=None, peers=[], notes=[])
    assert "Shares Out (as of 29 Apr 2011)" in render.html(ctx)


def test_3_description_without_figures_or_puffery():
    details = {"description": "JPMorgan Chase is a formidable financial titan with a $5.1 trillion balance sheet. "
                              "It is a leading bank. The firm serves consumers and businesses. "
                              "It operates in investment banking and asset management. It has offices in Ohio."}
    page, _ = _full(company={"name": "Apple Inc.", "ticker": "AAPL", "cik": "320193", "details": details})
    profile = _between(page, 'id="narr-overview"', "</p>")
    assert ("The firm serves consumers and businesses. It operates in investment banking and asset management. "
            '<span class="desc-mark">') in profile
    assert "titan" not in profile and "5.1" not in profile and "leading" not in profile and "Ohio" not in profile
    page, _ = _full(company={"name": "Apple Inc.", "ticker": "AAPL", "details": {"description": "A world-class giant. It had 5 units."}})
    assert "Company description" not in page and "<strong>Company Profile</strong> — An overview." in page


def test_4_bank_or_insurer():
    page, _ = _bank_page()
    head = _between(page, 'class="header"', 'class="top-section"')
    assert '<span class="tag tag-financial">Bank / insurer</span>' in head
    statement = _between(page, 'class="dense-table statements', "</thead>")
    assert "Gross profit" not in statement and "Operating income" not in statement and "Net income" in statement
    side = _between(page, 'kpi-sidebar">', '<div class="charts">')
    for gone in ("Gross margin", "Operating margin", "FCF margin"):
        assert gone not in side, gone
    assert "Net margin" in side
    assert 'Mkt cap / FCF</span>\n            <span class="sidebar-metric-value"><span class="na">n/a — not used for a bank or insurer</span>' in side
    assert "operating income for fiscal 2025 is not in the sources" in side       # truly missing stays missing
    assert "Market capitalisation / free cash flow" not in side                     # no definition for it
    assert 'Mkt cap / revenue</span>\n            <span class="sidebar-metric-value"><span class="na">n/a — not used for a bank or insurer</span>' in side
    assert re.search(r'P/B</span>\s*<span class="sidebar-metric-value">2\.27x</span>', side)
    assert "<strong>Price / book value</strong> — Price × shares outstanding ÷ shareholders" in side
    charts = _between(page, 'class="charts"', 'class="income"')
    assert "Free cash flow" not in charts and "Operating income" not in charts and "Shareholders&#39; equity ($) 5yr" in charts
    grid = _between(page, 'class="bottom-grid"', ">Stock data<")
    assert ">Funding</div>" in grid and "debt is part of how the business is funded" in grid
    assert "Free cash flow" not in grid and "FCF margin" not in grid and "Capital expenditure" not in grid
    alloc = _between(page, ">Capital allocation<", ">Risk themes ")
    assert "Free cash flow" not in alloc and "FCF margin" not in alloc and "Operating cash flow" in alloc
    # not a bank: everything as before
    page, _ = _bank_page(financial=False)
    assert "Bank / insurer" not in page and ">Leverage</div>" in page and "Gross margin" in page


def test_5_scenario_grid_headers_align_with_their_columns():
    page, _ = _full()
    css = page.split("</style>", 1)[0]
    assert ".fold-grid .val-method-table th { text-align: right; }" in css
    assert ".fold-grid .val-method-table th:first-child { text-align: left; }" in css


def test_6_withheld_lines_are_readable(monkeypatch):
    lines = ["Removed by review ('As a result' states a cause; 'As a result' asserts a cause): Net margin rose to "
             "[figure] from [[F:net_margin|FY2024", "Net margin rose to [[F:net_margin|FY2025]].",
             "Net margin rose to [[F:net_margin|FY2025]]."]
    page, _ = _full(withheld=lines)
    held = _between(page, 'class="withheld-list">', "</ul>")
    assert "[[F:" not in held and held.count("<li>") == 2
    assert "Removed by review (&#39;As a result&#39; states a cause): Net margin rose to [figure] from [figure" in held
    from backend.verify import audit
    monkeypatch.setattr(audit, "readable", lambda text: text.replace("Net margin", "The net margin"), raising=False)
    page, _ = _full(withheld=lines[1:2])
    assert "The net margin rose to [figure]." in _between(page, 'class="withheld-list">', "</ul>")


def test_7_peer_table_slow_tickers_and_na_titles():
    lg, _ = _ledger()
    table = dict(_inputs(lg)["peer_table"], slow=["C", "MS"])
    table["rows"] = [dict(table["rows"][0], cells=dict(table["rows"][0]["cells"],
                          operating_margin='<span class="na" title="operating income is not tagged">n/a</span>'))]
    page, _ = _full(peer_table=table)
    block = _between(page, ">Peer benchmarking<", ">Corporate info<")
    assert "Peers&#39; figures link to their own filings. (not loaded in time: C, MS)" in block
    assert '<span class="na" title="operating income is not tagged">n/a</span>' in block


def test_8_page_findings():
    page, _ = _bank_page()
    # the top shows only notes about a missing part; the self-check is in the footer
    top = _between(page, 'class="top-left"', 'kpi-sidebar')
    assert "The self-check removed" not in top and "Peers are not available: timeout" in top
    # readable header: SIC name in normal case with its code; no second line that repeats the name
    head = _between(page, 'class="header"', 'class="top-section"')
    assert "National Commercial Banks<span class=\"sector-code\">SIC 6021</span>" in head
    assert 'class="en"' not in head
    # an equity gap is drawn, not hidden
    bar = _between(page, 'class="cap-stack-bar"', 'class="cap-label-row"')
    assert 'class="cap-stack-other" style="width:1.13%"' in bar
    assert "Other (outside shareholders' equity)" in page
    # the Calculations list the years shown; the Sources list what the page cites
    assert 'id="calc-net_margin-FY2025"' in page and 'id="calc-net_margin-FY2008"' not in page
    assert "Calculations for the fiscal years shown on this page" in page
    sources = _between(page, 'class="dense-table sources"', "</table>")
    assert "Form 10-K, filed 2026-02-13" in sources and "2009-11-06" not in sources
    assert "1 older filings in the report data are not cited on this page." in page
    # a link to an older calculation brings its row back
    lg = _bank_ledger()
    sections = {"overview": f"<p>In fiscal 2008 the net margin was {_cited(lg, 'net_margin', 'FY2008')}.</p>"}
    page, _ = _bank_page(ledger=lg, sections=sections)
    assert 'href="#calc-net_margin-FY2008"' in page and page.count('id="calc-net_margin-FY2008"') == 1
    # the scenario caption only under a drawn market line; trend rows of n/a only are left out
    lg2, _ = _ledger()
    sc = dict(_inputs(lg2)["scenarios"], market={"enterprise_value": None, "text": None, "note": "Market cap plus net debt."})
    page, _ = _full(scenarios=sc, valuation=None)
    assert "Market cap plus net debt." not in page
    sc["market"] = dict(sc["market"], reason="No market enterprise value is drawn: net debt is not available.")
    page, _ = _full(scenarios=sc, valuation=None)
    assert "Market cap plus net debt." not in page and "No market enterprise value is drawn: net debt is not available." in page
    page, _ = _full(scenarios=sc)                       # under the methods panel too
    assert "No market enterprise value is drawn" in page and "Market cap plus net debt." not in page
    page, _, _ = _page()
    trend = _between(page, ">Balance sheet trend ", "</table>")
    assert "<td>Cash</td>" not in trend and "<td>Total assets</td>" in trend
    # the provider's name line when it adds something
    page, _ = _full(company={"name": "Celsius Holdings, Inc.", "ticker": "CELH",
                             "details": {"name": "Celsius Holdings, Inc. Class A Common Stock"}})
    assert 'class="en"' not in _between(page, 'class="header"', 'class="top-section"')
    page, _ = _full(company={"name": "Alphabet Inc.", "ticker": "GOOGL", "details": {"name": "Google parent company"}})
    assert '<div class="en">Google parent company</div>' in page


def test_phone_tables_fit_their_box(tmp_path):
    page_html, _ = _full()
    target = tmp_path / "report.html"
    target.write_text(page_html, encoding="utf-8")

    def run(browser):
        tab = browser.new_page(viewport={"width": 390, "height": 900})
        tab.goto(target.as_uri())
        for toggle in ("sources", "calcs", "withheld", "grid"):
            tab.locator(f'label[for="fold-{toggle}-toggle"]').click()
        for selector in (".val-assumptions", ".val-cases table", ".valuation-methods-table table",
                         ".calc-table", ".corp-info"):
            box = tab.locator(selector).first
            scroll, client = box.evaluate("e => [e.scrollWidth, e.clientWidth]")
            assert scroll <= client + 1, (selector, scroll, client)
        assert tab.locator(".val-assumptions-list").first.is_visible()
        assert not tab.locator(".val-assumptions-table").first.is_visible()
        tab.close()

    _with_browser(run)


# ---- round 5: another currency, nothing priced, ratios on a tiny base --------------------------
def _eur_ledger():
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", SEC + "/asml", "Form 20-F, filed 2026-02-11", "2026-02-11"))
    for i, (fy, end) in enumerate((("FY2025", "2025-12-31"), ("FY2024", "2024-12-31"), ("FY2023", "2023-12-31"))):
        lg.set_period_end(fy, end)
        lg.add_fact(Fact("revenue", fy, (32.7e9, 28.3e9, 27.6e9)[i], "EUR", source_ids=(sid,)))
        lg.add_fact(Fact("operating_income", fy, (10.5e9, 9.0e9, 9.0e9)[i], "EUR", source_ids=(sid,)))
        lg.add_fact(Fact("net_income", fy, (9.6e9, 7.6e9, 7.8e9)[i], "EUR", source_ids=(sid,)))
        lg.add_fact(Fact("operating_cash_flow", fy, (12.0e9, 11.2e9, 5.4e9)[i], "EUR", source_ids=(sid,)))
        lg.add_fact(Fact("total_assets", end, (50.0e9, 48.6e9, 39.0e9)[i], "EUR", source_ids=(sid,)))
    return lg


def _eur_page(**over):
    kw = dict(job={}, company={"name": "ASML Holding N.V.", "ticker": "ASML"}, ledger=_eur_ledger(), sections={},
              withheld=[], bars=[], previous_close=None, peers=[], notes=[])
    kw.update(over)
    return render.html(render.build_context(**kw))


def test_another_currency_and_form_20f():
    page = _eur_page(risk_themes=[{"title": "Export controls", "summary_html": "Rules limit sales.", "quote": "We are subject to export controls.",
                                   "source": {"title": "Form 20-F, filed 2026-02-11, Item 3.D: Risk Factors", "url": SEC + "/asml",
                                              "date": "2026-02-11"}}])
    titles = re.findall(r'class="chart-title">([^<]*)<', page)
    assert titles == ["Revenue (EUR) 5yr ", "Operating income (EUR) 5yr ", "Net income (EUR) 5yr ", "Free cash flow (EUR) 5yr "]
    assert "(fiscal years, EUR, as filed)" in page and "(Form 20-F XBRL data)" in page and "10-K" not in page
    assert "Risk themes <span class=\"dh-sub\">(Form 20-F, Item 3.D: Risk Factors)</span>" in page
    assert "(fiscal 2025, EUR)" in page and "(at fiscal year end, EUR)" in page
    headers = re.findall(r'class="(?:[^"]*\b)?data-header[^"]*"[^>]*>(.*?)</(?:div|label)>', page, re.S) + titles
    assert headers and not any("$" in h or "USD" in h for h in headers), [h for h in headers if "$" in h or "USD" in h]
    # tight labels drop the code: the title names the currency
    bars = re.findall(r'<div class="bar-value"><a [^>]*>([^<]*)</a>', page)
    assert "32.7B" in bars and not any("EUR" in b for b in bars)
    assert not re.search(r'<div class="cf-bar-label"><a [^>]*>EUR', page)
    # no risk themes: just the form
    assert "Risk themes <span class=\"dh-sub\">(Form 20-F)</span>" in _eur_page()
    # a dollar filer keeps its labels
    page, _, _ = _page()
    assert "Revenue ($) 5yr" in page and "(fiscal years, USD, as filed)" in page and "(Form 10-K XBRL data)" in page


def test_nothing_priced_has_no_score_and_no_pill():
    lg, _ = _ledger()
    v = _valuation_input(lg)
    v["methods"] = [dict(m, value=None, low=None, high=None, value_text=None, range_text=None,
                         reason=m.get("reason") or "the inputs are in EUR and the price is in USD") for m in v["methods"]]
    v["blend"] = {"value": None, "low": None, "high": None, "value_text": None, "range_text": None,
                  "vs_price": None, "vs_price_text": None, "basis": "nothing priced"}
    v["priced"] = 0
    page, _ = _full(valuation=v)
    head = _between(page, 'class="val-panel scenario-panel val-wide valuation-methods"', "</div>\n      ")
    assert "No method could be priced" in head and "val-quality" not in head and "MODEL VALUE" not in head
    assert "priced of" not in head and page.count("the inputs are in EUR and the price is in USD") == 3
    page = _eur_page(valuation=dict(v, shares_text="393.2 million shares", shares_note="market data"))
    stock = _between(page, ">Stock data<", ">Peer benchmarking<")
    assert '>393.2 million shares</span> <span class="ref-mark">(market data)</span>' in stock and "Not available" not in stock
    v["quality"] = None                                       # the module may send no quality at all
    page, _ = _full(valuation=v)
    assert "No method could be priced" in page and 'class="val-quality"' not in page


def test_not_meaningful_ratio_keeps_its_link_and_gets_a_footnote(monkeypatch):
    from backend import format as fmt
    real = fmt.fact
    monkeypatch.setattr(fmt, "fact", lambda f: "n/m" if f.unit == "ratio" and f.value is not None
                        and abs(f.value) >= 10 else real(f))
    lg, _ = _ledger()
    lg.replace_fact(Fact("operating_margin", "FY2024", -80.291, "ratio",
                         inputs=(("operating_income", "FY2024"), ("revenue", "FY2024")), formula="operating_income / revenue"))
    page = render.html(render.build_context(job={}, company={"ticker": "RIVN"}, ledger=lg, sections={}, withheld=[],
                                            bars=[], previous_close=None, peers=[], notes=[]))
    assert re.search(r'<a class="calc" href="#calc-operating_margin-FY2024"[^>]*>n/m</a>', page)
    assert page.count("n/m = not meaningful (the base is very small).") == 1
    page, _, _ = _page()
    assert "not meaningful" not in page
