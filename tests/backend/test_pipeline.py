"""pipeline.run with every neighbouring module replaced by a small fake (offline; the fakes are
thread-safe because the pipeline runs its fetches and branches at the same time)."""
import json
import sys
import threading
import types

import pytest

from backend import contract, jobs, pipeline, settings
from backend.ledger import Fact, Source
from backend.sources.http import SourceUnavailable


def _install(monkeypatch, dotted: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(dotted)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, dotted, mod)
    parent_name, _, child = dotted.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is None:
        parent = _install(monkeypatch, parent_name)
        parent.__path__ = []
    monkeypatch.setattr(parent, child, mod, raising=False)
    return mod


class FakeFiling:
    def __init__(self, n):
        self.accession, self.form, self.filed = f"0000320193-24-00000{n}", "10-K", f"202{n}-11-01"
        self.period, self.primary_doc, self.cik = f"202{n}-09-28", "aapl-10k.htm", "0000320193"

    @property
    def url(self):
        return f"https://www.sec.gov/Archives/edgar/data/320193/{self.accession}/{self.primary_doc}"

    @property
    def viewer_url(self):
        return self.url


class Bar:
    def __init__(self, date, close):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, close, close, close, close, 100


@pytest.fixture
def fakes(monkeypatch):
    calls = {"select_filings": None, "sections": None, "context": None}
    state = {"cik": "0000320193", "facts": 1, "massive_down": False, "writer_raises": False,
             "verdicts": {}, "thesis": {"thesis": ["A reported revenue increase."], "bull": ["b1"],
                                        "bear": ["r1"], "withheld": [], "method": "code",
                                        "counts": {"favourable": 1, "unfavourable": 1}},
             "peer_table": {"columns": [["revenue", "Revenue"]], "rows": [{"ticker": "MSFT"}], "medians": {}},
             "disclosures": [{"date": "2024-11-01", "form": "10-K", "title": "Annual report", "url": "https://www.sec.gov/x"}],
             # the newer optional parts are empty by default; the tests that cover them fill them in
             "valuation": None, "advice": None, "news": None, "release": None}
    hooks = {}                     # name -> callable run inside that fake (barriers, blocks)
    release = threading.Event()    # frees any fake that blocks, when the test ends

    def hook(name, *args):
        fn = hooks.get(name)
        if fn is not None:
            fn(*args)

    def normalise(symbol):
        s = symbol.strip().upper().replace("-", ".")
        if not contract.TICKER_RE.fullmatch(s):
            raise ValueError(symbol)
        return s

    def daily_bars(symbol, days):
        hook("daily_bars", symbol)
        if state["massive_down"]:
            raise SourceUnavailable("https://api.massive.com/x", "the price service is down")
        return [Bar("2024-01-02", 185.0), Bar("2024-01-03", 184.0)]

    def previous_close(symbol):
        if state["massive_down"]:
            raise SourceUnavailable("https://api.massive.com/x", "the price service is down")
        return {"close": 184.0}

    def filings(cik):
        hook("filings")
        return [FakeFiling(4), FakeFiling(3)]

    def company_facts(cik):
        hook("company_facts")
        return {"facts": {}}

    def company_name(symbol):
        hook("company_name", symbol)
        return "Apple Inc."

    def statement_facts(company_facts, filings, ledger, *, cik):
        calls["select_filings"] = filings
        if state["facts"]:
            sid = ledger.add_source(Source(id="", type="edinet", url=filings[0]["url"],
                                           title="Apple 10-K 2024", date="2024-11-01"))
            ledger.add_fact(Fact(key="revenue", period="FY2024", value=391035e6, unit="USD", source_ids=(sid,)))
        return {"facts": state["facts"], "filings_used": 1 if state["facts"] else 0, "metrics_missing": []}

    def write_sections(packet, *, session_id):
        hook("write_sections")
        if state["writer_raises"]:
            raise RuntimeError("model down")
        assert session_id.startswith("report-")
        return {"overview": "Revenue was {revenue.FY2024}."}

    def review_sections(raw, packet, *, session_id):
        assert session_id.startswith("report-")
        return {key: list(state["verdicts"].get(key, [])) for key in raw}

    def keep(text, verdicts):
        bad = [v for v in verdicts if v["rejected"]]
        removed = [f"Removed by review ({v['why']}): {v['sentence']}" for v in bad]
        for v in bad:
            text = text.replace(v["sentence"], "").strip()
        return text, removed

    def summary(all_verdicts):
        flat = [v for vs in all_verdicts.values() for v in vs]
        rejected = sum(1 for v in flat if v["rejected"])
        return {"sentences": len(flat), "confirmed_by_both": len(flat) - rejected, "rejected": rejected,
                "abstained_only": 0, "reviewers_answered": 2 if flat else 0}

    def thesis_build(ledger, company, *, session_id, found=None):
        hook("thesis")
        calls["thesis_found"] = found
        return state["thesis"]

    def peer_benchmark(tickers, **kwargs):
        hook("peer_table")
        calls["peer_tickers"] = list(tickers)
        return state["peer_table"]

    def risk_themes(found, annual, *, session_id):
        hook("risk")
        return [{"title": "Supply", "quote": "We depend on suppliers.",
                 "source": {"url": "https://www.sec.gov/Archives/edgar/data/320193/risk.htm",
                            "title": "Form 10-K Item 1A", "date": "2024-11-01"}}]

    def build_context(*, job, company, ledger, sections, withheld, bars, previous_close, peers, notes,
                      scenarios=None, risk_themes=None, multiples=None, review=None, thesis=None,
                      peer_table=None, disclosures=None, valuation=None, news=None, release=None):
        calls["sections"] = sections
        calls["bars"] = bars
        calls["context"] = {"withheld": list(withheld), "peers": peers, "review": review, "thesis": thesis,
                            "peer_table": peer_table, "disclosures": disclosures,
                            "valuation": valuation, "news": news, "release": release,
                            "risk_themes": risk_themes, "notes": list(notes)}
        return {"ticker": company["ticker"], "sections": sections, "notes": notes}

    _install(monkeypatch, "backend.sources.tickers", normalise=normalise)
    _install(monkeypatch, "backend.sources.sec",
             # the report's own company has the registrant under test; each peer has its own
             cik_for=lambda s: state["cik"] if s in ("AAPL", "ZZZZ") else f"cik-{s}", company_name=company_name,
             filings=filings, company_facts=company_facts)
    _install(monkeypatch, "backend.sources.massive", daily_bars=daily_bars, previous_close=previous_close,
             details=lambda s: {"name": "Apple Inc."}, related=lambda s: ["MSFT", "GOOGL", "META", "AMZN", "NVDA", "DELL"])
    _install(monkeypatch, "backend.facts.select", statement_facts=statement_facts)
    _install(monkeypatch, "backend.analysis.ratios", compute=lambda ledger: [])
    _install(monkeypatch, "backend.analysis.scenarios", beta_from_bars=lambda a, b: 1.0,
             compute=lambda ledger, *, beta, market_cap: {"title": "Scenario arithmetic"})
    _install(monkeypatch, "backend.analysis.multiples", compute=lambda ledger, *, price, price_date, **kw: [])
    _install(monkeypatch, "backend.analysis.risk", themes=risk_themes)
    _install(monkeypatch, "backend.filings.passages", risk_passages=lambda text: ["passage"] if text else [])
    _install(monkeypatch, "backend.draft.writer", build_packet=lambda ledger, company: {"company": company},
             write_sections=write_sections)
    _install(monkeypatch, "backend.draft.thesis", signals=lambda ledger: ["signal"], build=thesis_build)
    _install(monkeypatch, "backend.analysis.peers", benchmark=peer_benchmark)

    def valuation_compute(ledger, **kwargs):
        calls["valuation_inputs"] = kwargs
        return dict(state["valuation"]) if state["valuation"] is not None else None

    def valuation_blend(valuation, weights=None, *, rationale_html=None, advisor_method="default"):
        calls["blend"] = {"weights": weights, "advisor_method": advisor_method}
        return dict(valuation, blend={"value_text": "$150.00"},
                    advisor={"method": advisor_method, "rationale_html": rationale_html})

    def advisor_weigh(valuation, company, ledger, *, session_id):
        hook("advisor")
        return state["advice"]

    def news_digest(symbol, name, *, session_id):
        hook("news")
        return state["news"]

    def release_latest(filings, *, session_id):
        hook("release")
        return state["release"]

    _install(monkeypatch, "backend.analysis.valuation", compute=valuation_compute, blend=valuation_blend)
    _install(monkeypatch, "backend.analysis.advisor", weigh=advisor_weigh)
    _install(monkeypatch, "backend.research.news", digest=news_digest)
    _install(monkeypatch, "backend.research.releases", latest=release_latest)
    _install(monkeypatch, "backend.filings.disclosures", recent=lambda filings, **kw: list(state["disclosures"]))
    _install(monkeypatch, "backend.verify.audit", apply=lambda text, ledger: (text.replace("<", "&lt;"), []))
    _install(monkeypatch, "backend.verify.review", review_sections=review_sections, keep=keep, summary=summary,
             describe=lambda c: f"Self-check: {c['sentences']} sentences, {c['confirmed_by_both']} confirmed "
                                f"by both readers, {c['rejected']} removed")
    _install(monkeypatch, "backend.render", build_context=build_context,
             html=lambda ctx: f"<!doctype html><title>{ctx['ticker']}</title><p>report</p>")
    state["hooks"], state["release"] = hooks, release
    yield state, calls
    release.set()


def _overlap(names, parties=None):
    """Hooks that make each named fake wait until all of them are inside at once: a barrier that
    breaks (after 5 s) unless they really run at the same time. Returns (hooks, who-arrived)."""
    barrier = threading.Barrier(parties or len(names), timeout=5)
    arrived, lock = [], threading.Lock()

    def make(name):
        def wait(*args):
            with lock:
                arrived.append(name)
            barrier.wait()
        return wait
    return {n: make(n) for n in names}, arrived, barrier


def _new_job(code="AAPL"):
    return jobs.registry().create(code, "", "full")


def test_walks_every_stage_and_completes(fakes):
    state, calls = fakes
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert tuple(done.stage_history) == contract.STAGES
    assert done.status == "complete" and done.step == "Complete" and done.progress == 100
    assert done.finished_at and done.started_at and done.error is None
    assert contract.REPORT_FILE_RE.fullmatch(done.html_file)
    path = settings.reports_dir() / done.html_file
    assert path.is_file()
    ledger_path = settings.reports_dir() / done.html_file.replace(".html", ".ledger.json")
    doc = json.loads(ledger_path.read_text())
    assert doc["company"]["ticker"] == "AAPL"
    assert done.sources and all(tuple(s) == contract.SOURCE_FIELDS for s in done.sources)
    assert done.source_count == len(done.sources) == 1
    assert done.edinet_total == 2 and done.edinet_scanned == 2 and done.edinet_count == 1
    assert done.financial_rows == 1 and done.price_rows == 2 and done.financials_source == "SEC EDGAR"
    assert done.company_name == "Apple Inc."
    assert set(calls["select_filings"][0]) >= {"accession", "form", "filed", "primary_doc", "url", "viewer_url"}
    assert calls["sections"] == {"overview": "Revenue was {revenue.FY2024}."}


def test_unknown_cik_ends_in_error_at_company_info(fakes):
    state, _ = fakes
    state["cik"] = None
    job = _new_job("ZZZZ")
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "error" and done.step == "Company Info"
    assert done.error == "No SEC registrant found for ZZZZ."
    assert done.html_file is None and done.finished_at


def test_no_figures_ends_in_error_and_html_stays_none(fakes):
    state, _ = fakes
    state["facts"] = 0
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "error" and done.step == "Extraction"
    assert done.error == "No reported figures were found in the SEC data for AAPL."
    assert done.html_file is None
    assert not list(settings.reports_dir().glob("*.html")) if settings.reports_dir().exists() else True


def test_massive_down_still_completes_with_warning(fakes):
    state, calls = fakes
    state["massive_down"] = True
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "warning" and done.step == "Complete"
    assert calls["bars"] == [] and done.price_rows == 0
    assert any(w.startswith("Prices are not available:") for w in done.warnings)
    assert (settings.reports_dir() / done.html_file).is_file()


def test_writer_exception_still_completes(fakes):
    state, calls = fakes
    state["writer_raises"] = True
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "warning" and done.html_file
    assert calls["sections"] == {}
    assert "The written sections could not be produced." in done.warnings


def test_sec_unavailable_ends_with_its_reason(fakes, monkeypatch):
    def down(cik):
        raise SourceUnavailable("https://data.sec.gov/x", "SEC EDGAR did not answer")
    monkeypatch.setattr(sys.modules["backend.sources.sec"], "filings", down)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "error" and done.step == "Data Fetch"
    assert done.error == "SEC EDGAR did not answer" and done.html_file is None


def test_unexpected_exception_gives_plain_message(fakes, monkeypatch):
    def boom(ledger):
        raise KeyError("x")
    monkeypatch.setattr(sys.modules["backend.analysis.ratios"], "compute", boom)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "error" and done.step == "Analysis"
    assert done.error == "The report could not be generated."


def _with_filing_text(monkeypatch):
    monkeypatch.setattr(sys.modules["backend.sources.sec"], "filing_text", lambda f: "Item 1A. Risk Factors",
                        raising=False)


def test_ledger_document_and_renderer_get_the_new_parts(fakes, monkeypatch):
    state, calls = fakes
    _with_filing_text(monkeypatch)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "complete", done.warnings
    doc = json.loads((settings.reports_dir() / done.html_file.replace(".html", ".ledger.json")).read_text())
    assert doc["thesis"] == state["thesis"] and calls["context"]["thesis"] == state["thesis"]
    assert doc["review"]["sentences"] == 0 and calls["context"]["review"] == doc["review"]
    assert [p["ticker"] for p in calls["context"]["peers"]] == ["MSFT", "GOOGL", "META", "AMZN", "NVDA"]
    assert all(p["name"] == "Apple Inc." for p in calls["context"]["peers"])
    assert doc["risk_themes"][0]["title"] == "Supply"
    # the risk theme's source is added on the job's thread, after the filing's own source
    assert [s["url"].rsplit("/", 1)[1] for s in done.sources] == ["aapl-10k.htm", "risk.htm"]
    kinds = [e["type"] for e in done.events]
    assert "branches" in kinds and "review" in kinds and "thesis" in kinds
    assert any(e["message"] == "Bull and bear cases: 1 favourable, 1 unfavourable signals" for e in done.events)


def test_the_fetches_run_at_the_same_time(fakes):
    state, _ = fakes
    hooks, arrived, barrier = _overlap(["filings", "company_facts", "daily_bars"])
    bars_hook = hooks.pop("daily_bars")
    hooks["daily_bars"] = lambda symbol: bars_hook() if symbol == "AAPL" else None   # not the SPY call
    state["hooks"].update(hooks)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert not barrier.broken and sorted(arrived) == ["company_facts", "daily_bars", "filings"]
    assert done.status == "complete" and done.html_file


def test_the_branches_run_at_the_same_time(fakes, monkeypatch):
    state, calls = fakes
    monkeypatch.setattr(sys.modules["backend.sources.sec"], "filing_text", lambda f: "Item 1A. Risk Factors",
                        raising=False)
    hooks, arrived, barrier = _overlap(["write_sections", "risk", "thesis", "company_name"])
    peer_hook = hooks.pop("company_name")
    hooks["company_name"] = lambda symbol: peer_hook() if symbol == "MSFT" else None
    state["hooks"].update(hooks)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert not barrier.broken
    assert sorted(arrived) == ["company_name", "risk", "thesis", "write_sections"]
    assert done.status == "complete", done.warnings
    assert calls["thesis_found"] == ["signal"]       # the wording gets the signals the rules chose


@pytest.mark.parametrize("branch, hook_name, note", [
    ("risk", "risk", "The risk themes took too long and are not in this report."),
    ("thesis", "thesis", "The bull and bear cases took too long and are not in this report."),
    ("drafting", "write_sections", "The written sections took too long and are not in this report."),
])
def test_a_late_branch_gives_its_note_and_the_job_completes(fakes, monkeypatch, branch, hook_name, note):
    state, calls = fakes
    _with_filing_text(monkeypatch)
    monkeypatch.setitem(settings.BRANCH_TIMEOUTS, branch, 0)
    state["hooks"][hook_name] = lambda *a: state["release"].wait(5)   # stuck until the test ends
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "warning" and done.step == "Complete" and done.html_file
    assert note in done.warnings
    assert tuple(done.stage_history) == contract.STAGES
    if branch == "drafting":
        assert calls["sections"] == {}
    if branch == "thesis":
        assert calls["context"]["thesis"] is None
    if branch == "risk":
        assert calls["context"]["risk_themes"] == [] and done.source_count == 1
    else:
        assert calls["context"]["risk_themes"] and done.source_count == 2


def test_late_peer_names_keep_the_tickers(fakes, monkeypatch):
    state, calls = fakes
    monkeypatch.setitem(settings.BRANCH_TIMEOUTS, "peers", 0)
    state["hooks"]["company_name"] = lambda symbol: state["release"].wait(5) if symbol == "MSFT" else None
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "warning"
    assert "The peer names took too long; the peers are listed by ticker only." in done.warnings
    assert [p["ticker"] for p in calls["context"]["peers"]] == ["MSFT", "GOOGL", "META", "AMZN", "NVDA"]


def test_a_rejected_sentence_is_withheld_and_noted(fakes):
    state, calls = fakes
    state["verdicts"] = {"overview": [
        {"sentence": "Revenue was {revenue.FY2024}.", "rejected": True, "why": "says rose; the listed direction is down"}]}
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    # a removed sentence is the checks working: the report is complete and lists the sentence
    assert done.status == "complete" and done.html_file
    assert calls["context"]["withheld"] == [
        "Removed by review (says rose; the listed direction is down): Revenue was {revenue.FY2024}."]
    assert "The self-check removed 1 sentence." in done.warnings
    assert calls["sections"]["overview"] == ""      # the fake writer has no fallback overview
    doc = json.loads((settings.reports_dir() / done.html_file.replace(".html", ".ledger.json")).read_text())
    assert doc["review"]["rejected"] == 1
    assert any(e["type"] == "review" and e["message"].endswith("1 removed") for e in done.events)


def test_thesis_withheld_sentences_reach_the_withheld_list(fakes):
    state, calls = fakes
    state["thesis"] = dict(state["thesis"], withheld=["Bull case: margins will expand."])
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "complete"                 # withheld wording is not a missing part
    assert calls["context"]["withheld"] == ["Bull case: margins will expand."]


def test_no_thesis_and_no_review_module_still_completes(fakes, monkeypatch):
    state, calls = fakes
    monkeypatch.setitem(sys.modules, "backend.draft.thesis", None)    # import fails
    monkeypatch.setitem(sys.modules, "backend.verify.review", None)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "complete", done.warnings
    assert calls["context"]["thesis"] is None and calls["context"]["review"] is None
    assert calls["sections"] == {"overview": "Revenue was {revenue.FY2024}."}


def test_company_facts_unavailable_ends_at_data_fetch(fakes, monkeypatch):
    def down(cik):
        raise SourceUnavailable("https://data.sec.gov/x", "SEC EDGAR company facts did not answer")
    monkeypatch.setattr(sys.modules["backend.sources.sec"], "company_facts", down)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "error" and done.step == "Data Fetch"
    assert done.error == "SEC EDGAR company facts did not answer" and done.html_file is None
    assert done.edinet_total == 2      # the filings index arrived and was recorded first


def test_two_share_classes_are_one_peer_and_the_company_is_not_its_own_peer():
    class Sec:
        @staticmethod
        def cik_for(ticker):
            if ticker == "BAD":
                raise RuntimeError("lookup failed")
            return {"GOOGL": "1652044", "GOOG": "1652044", "AAPL": "320193"}.get(ticker, f"c-{ticker}")

    related = ["MSFT", "GOOGL", "AAPL", "GOOG", "BAD", "NVDA", "AMZN", "META", "DELL"]
    assert pipeline._unique_peers(related, Sec, "320193") == ["MSFT", "GOOGL", "BAD", "NVDA", "AMZN"]
    assert len(pipeline._unique_peers(related, Sec)) == pipeline.PEER_LIMIT
    assert pipeline._unique_peers([], Sec, "320193") == []


def test_the_companys_own_risk_statements_fill_the_bear_case():
    themes = [{"title": "Supply", "quote": 'We depend on a "small" number of suppliers & 2 vendors.',
               "source": {"url": "https://www.sec.gov/x.htm", "title": "Form 10-K, Item 1A"}},
              {"title": "No link", "quote": "Unlinked.", "source": {"url": "javascript:alert(1)"}},
              {"title": "Cyber", "quote": "Attacks could stop order processing.",
               "source": {"url": "https://www.sec.gov/y.htm", "title": "Form 10-K, Item 1A"}},
              {"title": "FX", "quote": "Currency moves affect results.", "source": {"url": "https://www.sec.gov/z.htm"}}]
    view = {"bull": [], "bear": [{"html": "ROE fell.", "method": "code"}], "counts": {"bear": 1}}
    assert pipeline._filed_bear_points(view, themes) == 2            # at most two filed points
    assert [b["method"] for b in view["bear"]] == ["code", "filed", "filed"]
    first = view["bear"][1]["html"]
    assert "&quot;small&quot;" in first and "&amp; 2 vendors" in first      # the filing's words, escaped once
    assert 'href="https://www.sec.gov/x.htm"' in first and "javascript" not in str(view)
    assert view["counts"] == {"bear": 3, "filed": 2}
    # with a checked summary the bear point gives the risk in one sentence; the quote stays with the themes
    summed = [dict(themes[0], summary_html="Production depends on a few suppliers &amp; vendors.")]
    view2 = {"bear": []}
    assert pipeline._filed_bear_points(view2, summed) == 1
    html2 = view2["bear"][0]["html"]
    assert html2.startswith("A risk the company states in its annual filing: Production depends on a few suppliers &amp; vendors. <a ")
    assert "small" not in html2 and 'href="https://www.sec.gov/x.htm"' in html2
    full = {"bear": [{}] * 4}
    assert pipeline._filed_bear_points(full, themes) == 0 and len(full["bear"]) == 4     # no room: nothing added
    assert pipeline._filed_bear_points(None, themes) == 0 and pipeline._filed_bear_points({"bear": []}, []) == 0
    # a sentence of the risk section that states no harm is not a bear point
    upbeat = [{"title": "Rates", "quote": "The firm may generally be expected to earn higher net interest income when rates are high.",
               "source": {"url": "https://www.sec.gov/r.htm", "title": "Form 10-K, Item 1A"}}]
    view = {"bear": []}
    assert pipeline._filed_bear_points(view, upbeat) == 0 and view["bear"] == []


def test_a_bank_or_insurer_is_recognised_by_its_industry_code():
    assert pipeline._is_financial({"sic_code": "6021"}) and pipeline._is_financial({"sic_code": 6331})
    assert not pipeline._is_financial({"sic_code": "3571"}) and not pipeline._is_financial({"sic_code": "7389"})
    # a REIT (6798) or a real-estate company is read like any other company, not like a bank
    assert not pipeline._is_financial({"sic_code": "6798"}) and not pipeline._is_financial({"sic_code": 6512})
    assert pipeline._is_financial({"sic_code": "6211"}) and pipeline._is_financial({"sic_code": "6411"})
    assert not pipeline._is_financial({}) and not pipeline._is_financial({"sic_code": "n/a"})
    # only the keywords a function takes are passed on
    assert pipeline._accepts(lambda ledger, *, financial=False: None, financial=True, other=1) == {"financial": True}
    assert pipeline._accepts(lambda ledger: None, financial=True) == {}
    assert pipeline._accepts(lambda ledger, **kw: None, financial=True) == {"financial": True}


def test_house_peer_group_only_when_the_provider_lists_none():
    from backend.analysis import peer_groups
    assert peer_groups.fallback("DUOL") == ["DOCS", "UPST", "ETSY", "ADBE", "CRM", "NFLX"]
    assert peer_groups.fallback(" upst ")[:2] == ["DUOL", "DOCS"]          # ticker spelling is normalised
    assert peer_groups.fallback("BRK.B") == []                              # an insurer-conglomerate has no group here
    assert peer_groups.fallback("ZZZZ") == []                               # not on the coverage list
    assert "DUOL" not in peer_groups.fallback("DUOL")
    every = [m for _name, members in peer_groups.GROUPS for m in members]
    assert all(m == m.upper() for m in every)


def test_an_empty_related_list_uses_the_house_group_and_says_so(fakes, monkeypatch):
    state, calls = fakes
    _install(monkeypatch, "backend.sources.massive", daily_bars=lambda s, n: [], previous_close=lambda s: None,
             details=lambda s: {}, related=lambda s: [])
    state["peer_table"] = {"columns": [], "rows": [], "medians": {}, "note": "Each company's own filings."}
    job = _new_job("DUOL")
    pipeline.run(job.job_id)
    assert calls["peer_tickers"] == ["DOCS", "UPST", "ETSY", "ADBE", "CRM"]
    note = calls["context"]["peer_table"]["note"]
    assert note.startswith("Each company's own filings.") and "same sector within this coverage list" in note


def test_a_missing_part_finishes_as_a_warning_with_its_note_in_the_message(fakes):
    state, calls = fakes
    state["massive_down"] = True
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "warning"
    assert done.message.startswith("Report ready. Prices are not available:")


RICH = {
             "valuation": {"methods": [{"key": "dcf", "value": 150.0}], "priced": 1, "total": 6},
             "advice": {"weights": {"dcf": 70}, "rationale_html": "A cash-flow method fits.", "method": "model",
                        "withheld": ["Removed from the advisor: buy it."]},
             "news": {"articles": [{"id": "N1", "title": "Apple unveils a product", "publisher": "Newswire",
                                    "date": "2024-11-02", "url": "https://news.example.com/a", "summary": "Launch."},
                                   {"id": "N2", "title": "Bad link", "publisher": "X", "date": "2024-11-01",
                                    "url": "http://insecure.example.com/b", "summary": ""}],
                      "topics": [{"title": "Products", "summary_html": "Reports cover a launch.", "articles": ["N1"]}],
                      "method": "model", "withheld": []},
             "release": {"url": "https://www.sec.gov/Archives/edgar/data/320193/ex99.htm",
                         "source_title": "Form 8-K, filed 2024-10-31, Exhibit 99.1", "filed": "2024-10-31",
                         "statements": [{"topic": "Results", "quote": "Revenue was a September quarter record.",
                                         "summary_html": ""}], "method": "model", "withheld": []}
}


def _rich(state):
    import copy
    state.update(copy.deepcopy(RICH))


def test_valuation_methods_get_the_advisors_weights_and_reach_the_page(fakes):
    state, calls = fakes
    _rich(state)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert done.status == "complete", done.warnings
    assert calls["valuation_inputs"]["peer_table"] == state["peer_table"]      # priced after the peers are in
    assert calls["blend"] == {"weights": {"dcf": 70}, "advisor_method": "model"}
    shown = calls["context"]["valuation"]
    assert shown["blend"] == {"value_text": "$150.00"} and shown["advisor"]["rationale_html"] == "A cash-flow method fits."
    assert "Removed from the advisor: buy it." in calls["context"]["withheld"]
    doc = json.loads((settings.reports_dir() / pipeline.ledger_file_name(done.html_file)).read_text())
    assert doc["valuation"]["blend"] == {"value_text": "$150.00"}


def test_a_late_or_failed_advisor_means_default_weights_not_a_missing_part(fakes, monkeypatch):
    state, calls = fakes
    _rich(state)
    state["advice"] = "not a dict"
    job = _new_job()
    pipeline.run(job.job_id)
    assert calls["blend"] == {"weights": None, "advisor_method": "default"}
    assert jobs.registry().get(job.job_id).status == "complete"


def test_web_news_becomes_web_sources_and_the_release_an_sec_source(fakes):
    state, calls = fakes
    _rich(state)
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    web = [s for s in done.sources if s["type"] == "web"]
    assert [s["url"] for s in web] == ["https://news.example.com/a"]            # https only
    assert web[0]["title"] == "Apple unveils a product" and web[0]["snippet"].startswith("Newswire: ")
    assert any(s["title"] == "Form 8-K, filed 2024-10-31, Exhibit 99.1" for s in done.sources)
    assert calls["context"]["news"]["topics"][0]["title"] == "Products"
    assert calls["context"]["release"]["statements"][0]["topic"] == "Results"
    doc = json.loads((settings.reports_dir() / pipeline.ledger_file_name(done.html_file)).read_text())
    assert doc["news"]["articles"][0]["id"] == "N1" and doc["release"]["statements"]


def test_no_articles_and_no_statements_mean_no_news_and_no_release(fakes):
    state, calls = fakes
    _rich(state)
    state["news"] = {"articles": [], "topics": [], "method": "none"}
    state["release"] = {"statements": [], "method": "none"}
    job = _new_job()
    pipeline.run(job.job_id)
    done = jobs.registry().get(job.job_id)
    assert calls["context"]["news"] is None and calls["context"]["release"] is None
    assert not [s for s in done.sources if s["type"] == "web"] and done.status == "complete"


def test_a_section_never_vanishes(fakes, monkeypatch):
    """A section the checks emptied, or cut by half or more, is rebuilt in code from the figures."""
    from backend.verify import audit as real_audit

    class Writer:
        @staticmethod
        def fallback_section(key, ledger, company):
            return {"results": "Revenue was built in code.", "cash_flow": ""}.get(key, "")

    sections = {"results": "", "financial_position": "<p>Total assets rose.</p>", "cash_flow": "<p>Cash flow rose.</p>"}
    filled = pipeline._fill_sections(sections, ["cash_flow"], Writer, real_audit, None, {})
    assert filled == ["results"]                                  # empty -> rebuilt; a thin one with no fallback stays
    assert sections["results"] == "Revenue was built in code."
    assert sections["financial_position"] == "<p>Total assets rose.</p>" and sections["cash_flow"] == "<p>Cash flow rose.</p>"
    sections = {"results": "<p>One sentence left.</p>"}
    assert pipeline._fill_sections(sections, ["results"], Writer, real_audit, None, {}) == ["results"]
    assert pipeline._fill_sections({"results": ""}, [], object(), real_audit, None, {}) == []     # an older writer: nothing to call


def test_a_job_deleted_while_it_runs_stops_and_leaves_no_report(fakes, caplog):
    state, calls = fakes
    job = _new_job()
    state["hooks"]["write_sections"] = lambda *a: jobs.registry().delete(job.job_id)
    with caplog.at_level("ERROR"):
        pipeline.run(job.job_id)                      # must not raise
    assert jobs.registry().get(job.job_id) is None
    assert not list(settings.reports_dir().glob("report_AAPL_*")) if settings.reports_dir().is_dir() else True
    assert calls["context"] is None                   # the page was never built
    assert not [r for r in caplog.records if r.levelname == "ERROR"]     # a deletion is not a fault


def test_peers_are_kept_only_when_in_the_same_industry():
    sic = {"KO": "2086", "PEP": "2080", "KDP": "2080", "MNST": "2086", "BRK.B": "6331", "AXP": "6199", "CVX": "2911"}

    class Massive:
        @staticmethod
        def details(ticker):
            if ticker == "BAD":
                raise RuntimeError("down")
            return {"sic_code": sic.get(ticker)}

    listed = ["BRK.B", "PEP", "AXP", "KDP", "CVX", "MNST", "BAD", "KO"]
    assert pipeline._same_industry("KO", listed, Massive) == ["PEP", "KDP", "MNST"]      # drinks only, order kept
    assert pipeline._same_industry("ZZ", listed, Massive) is None                          # own industry unknown
    assert pipeline._same_industry("BRK.B", ["KO", "AXP"], Massive) == []
    assert pipeline._industry_group({"sic_code": "2086"}) == "20" and pipeline._industry_group({"sic_code": 6021}) == "60"
    assert pipeline._industry_group({}) is None and pipeline._industry_group(None) is None
