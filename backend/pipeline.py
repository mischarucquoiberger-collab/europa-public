"""One report job, stage by stage (contract.STAGES), with the slow work running at the same time.

- Data Fetch: the SEC filings index and reported facts (required) and the market data (daily bars,
  previous close, company details, related tickers, the market proxy's bars) are fetched at once
  on a pool of settings.FETCH_WORKERS.
- Extraction, Analysis and the Valuation arithmetic run on this thread (they are instant, and every
  ledger CHANGE stays on this thread so source and fact numbering is the same on every run).
- Then the branches start together and overlap: peers (names), risk themes (annual filing text +
  model), the bull and bear cases (thesis), and drafting, which is followed at once by the
  self-check (independent model readers, backend.verify.review) and the audit. The visible steps
  then advance in order, each waiting for its branches within settings.BRANCH_TIMEOUTS; a late
  branch is left out with a plain note and the report completes without it.

Never leaves a job running: every failure ends in status "error" with a plain message, and
html_file is set only once the file exists."""
import dataclasses
import re
import html as _html
import inspect
import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from backend import contract, jobs, settings
from backend.jobs import now_iso

log = logging.getLogger(__name__)

PROGRESS = {"Starting": 2, "Company Info": 8, "Data Fetch": 15, "Extraction": 35, "Analysis": 50,
            "Valuation": 62, "Peers": 70, "Drafting": 80, "Rendering": 92, "Complete": 100}
MESSAGES = {
    "Starting": "Starting the report",
    "Company Info": "Looking up the company at the SEC",
    "Data Fetch": "Fetching filings, reported figures and prices",
    "Extraction": "Selecting the reported figures",
    "Analysis": "Computing ratios from the reported figures",
    "Valuation": "Working out the scenario arithmetic",
    "Peers": "Finding comparable companies",
    "Drafting": "Writing the sections",
    "Rendering": "Building the report",
    "Complete": "Report ready",
}
assert tuple(PROGRESS) == contract.STAGES

PRICE_DAYS = 730
PEER_LIMIT = 5
MARKET_PROXY = "SPY"      # the market series a stock's beta is measured against

_semaphore = threading.Semaphore(settings.MAX_RUNNING_JOBS)

LATE = {   # the plain note for a branch that did not finish in time
    "market": "The market index prices took too long; the scenario arithmetic is shown without a measured beta.",
    "peers": "The comparable companies took too long and are not in this report.",
    "peer_names": "The peer names took too long; the peers are listed by ticker only.",
    "peer_table": "The peers' own figures took too long; the peers are listed by name only.",
    "drafting": "The written sections took too long and are not in this report.",
    "review": "The self-check took too long; the written sections were checked by the code audit only.",
    "risk": "The risk themes took too long and are not in this report.",
    "thesis": "The bull and bear cases took too long and are not in this report.",
    "news": "The web research took too long and is not in this report.",
    "release": "The latest results release took too long and is not in this report.",
}


class JobGone(Exception):
    """The job was deleted while it ran. The run stops at its next step and leaves no report:
    there is nobody left to report to, and the slot is free for the next job."""


class JobFailed(Exception):
    """Ends the job with this plain message."""


def _filing_dict(f) -> dict:
    if isinstance(f, dict):
        d = dict(f)
    else:
        d = {k: getattr(f, k, None) for k in ("accession", "form", "filed", "period", "primary_doc", "cik")}
        d["url"] = getattr(f, "url", None)
        d["viewer_url"] = getattr(f, "viewer_url", None)
    return d


def _timeout(name: str) -> float:
    try:
        return max(0.0, float(settings.BRANCH_TIMEOUTS.get(name, 60)))
    except Exception:
        return 60.0


def _spawn(name: str, fn, *args, **kwargs) -> Future:
    """Run fn in its own daemon thread; its result (or exception) lands in the returned future.
    A daemon thread: a branch the report stopped waiting for never holds the process open."""
    future: Future = Future()

    def target():
        if not future.set_running_or_notify_cancel():
            return
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:   # handed to whoever waits for the branch
            future.set_exception(exc)
        else:
            future.set_result(result)

    threading.Thread(target=target, name=name, daemon=True).start()
    return future


class _Late(Exception):
    """A branch that did not finish within its time."""


def _wait(future: Future, deadline: float):
    """The branch's result; _Late when the deadline (time.monotonic) passes first; the branch's
    own exception when it failed."""
    try:
        return future.result(timeout=max(0.0, deadline - time.monotonic()))
    except FutureTimeout:
        raise _Late() from None


def _accepts(fn, **kwargs) -> dict:
    """Only the keywords `fn` takes: another part of the system may be a version behind."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in params}


def _is_financial(details: dict) -> bool:
    """A bank, broker or insurer, by its SIC code (6000 to 6499). For such a company debt and
    cash are the business itself: free cash flow, enterprise value, gross profit and debt ratios
    do not describe it, so those parts are left out rather than shown as if they were missing
    data. Real estate (6500s) and holding or investment companies such as REITs (6700s) are
    NOT in it: they are read like any other company."""
    try:
        code = int(str((details or {}).get("sic_code") or "").strip())
    except ValueError:
        return False
    return 6000 <= code <= 6499


def _has_fiscal_year(ledger) -> bool:
    return any(re.fullmatch(r"FY\d{4}", period) for key in ledger.keys() for period in ledger.periods(key))


_ADVERSE = re.compile(r"\b(?:advers\w*|harm\w*|risks?|loss(?:es)?|declin\w*|decreas\w*|reduc\w*|unable|fail\w*|"
                      r"disrupt\w*|negativ\w*|materially|uncertain\w*|volatil\w*|compet\w*|depend\w*|"
                      r"shortage\w*|breach\w*|litigation|penalt\w*|no assurances?|could|might|cannot|"
                      r"attack\w*|threat\w*|damag\w*|interrupt\w*|delay\w*|impair\w*|weak\w*|downturn\w*|"
                      r"recession\w*|tariffs?|sanctions?)\b", re.I)


def _optional(dotted: str):
    """An optional module, or None when it is missing or does not import (another part of the
    system may be mid-change: the report goes on without it)."""
    try:
        import importlib
        return importlib.import_module(dotted)
    except Exception as exc:
        log.info("optional module %s unavailable: %s", dotted, exc)
        return None


# ---- branches (they only READ the ledger; changes are made on the job's own thread) ----------
def _industry_group(details) -> str | None:
    """The first two digits of a company's SIC code: its industry group (20 food and drink,
    60 banks, 73 software and services ...)."""
    code = str((details or {}).get("sic_code") or "").strip() if isinstance(details, dict) else ""
    return code[:2] if len(code) >= 3 and code[:2].isdigit() else None


def _same_industry(symbol: str, listed: list, massive, limit: int = 12) -> list[str] | None:
    """Those of the listed tickers whose industry group is the company's own, in their order.
    None when the company's own group is unknown: then nothing can be compared and the
    provider's list stands."""
    try:
        own = _industry_group(massive.details(symbol))
    except Exception:
        own = None
    if own is None:
        return None

    def group(ticker):
        try:
            return _industry_group(massive.details(ticker))
        except Exception:       # an unknown peer is simply not counted as the same industry
            return None
    candidates = [t for t in listed[:limit] if str(t).upper() != str(symbol).upper()]
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(candidates)), thread_name_prefix="peer-sic") as pool:
        groups = list(pool.map(group, candidates))
    return [t for t, g in zip(candidates, groups) if g == own]


def _unique_peers(tickers: list, sec, own_cik: str | None = None) -> list[str]:
    """The first PEER_LIMIT different companies: two share classes of one company (same SEC
    registrant) count once, and the report's own company is never its own peer."""
    seen = {str(own_cik)} if own_cik else set()
    out: list[str] = []
    for ticker in tickers:
        try:
            key = str(sec.cik_for(ticker) or ticker)
        except Exception:      # unknown to the SEC list: keep it under its own name
            key = str(ticker)
        if key in seen:
            continue
        seen.add(key)
        out.append(ticker)
        if len(out) >= PEER_LIMIT:
            break
    return out


def _peer_names(related: Future, sec, session_tag: str, own_cik: str | None = None) -> list[dict]:
    tickers = _unique_peers(list(related.result() or []), sec, own_cik)

    def name(ticker):
        try:
            return sec.company_name(ticker) or ""
        except Exception:  # the name is a nicety; the ticker stands on its own
            return ""
    if not tickers:
        return []
    with ThreadPoolExecutor(max_workers=len(tickers), thread_name_prefix=f"peers-{session_tag}") as pool:
        names = list(pool.map(name, tickers))
    return [{"ticker": t, "name": n} for t, n in zip(tickers, names)]


def _annual(filings: list):
    return next((f for f in filings if getattr(f, "form", "") in ("10-K", "20-F")), None)


def _risk_passages(annual, sec, passages_mod) -> list:
    """The newest annual filing's risk passages (the filing text is fetched here)."""
    if annual is None or passages_mod is None:
        return []
    return list(passages_mod.risk_passages(sec.filing_text(annual)) or [])


def _risk_themes(found: Future, annual, risk_mod, session_id: str) -> list:
    passages = found.result()
    if not passages or risk_mod is None:
        return []
    return list(risk_mod.themes(passages, annual, session_id=session_id) or [])


def _thesis(thesis_mod, ledger, company: dict, signals: list, session_id: str, financial: bool = False):
    """Word the bull and bear points. Which facts they are was decided by rules on the job's own
    thread (`thesis.signals`); this branch only reads the ledger."""
    return thesis_mod.build(ledger, company, session_id=session_id, found=signals,
                            **_accepts(thesis_mod.build, financial=financial))


def _peer_table(related: Future, peers_mod, sec, own_cik: str | None = None) -> dict | None:
    """Each peer's own latest filed figures, loaded at the same time (its own ledger per peer)."""
    tickers = _unique_peers(list(related.result() or []), sec, own_cik)
    if not tickers or peers_mod is None:
        return None
    return peers_mod.benchmark(tickers, timeout=max(1.0, _timeout("peers") - 5.0))


def _drafting(writer, audit, review, ledger, company: dict, session_id: str, drafted: Future) -> dict:
    """Write every section, then (at once) the self-check, then per section review.keep and
    audit.apply. `drafted` gets (time written, raw sections) as soon as the writing is done, so
    the job can give the self-check its own time and fall back to the audit alone."""
    try:
        packet = writer.build_packet(ledger, company)
        raw = writer.write_sections(packet, session_id=session_id) or {}
    except BaseException as exc:
        drafted.set_exception(exc)
        raise
    drafted.set_result((time.monotonic(), raw))
    verdicts: dict = {}
    if review is not None and raw:
        try:
            verdicts = review.review_sections(raw, packet, session_id=session_id) or {}
        except Exception as exc:
            log.warning("the self-check could not run: %s", exc)
            verdicts = {}
    sections, withheld, removed_count, thin = {}, [], 0, []
    for key, text in raw.items():
        removed: list[str] = []
        written = _sentence_count(audit, text)
        if review is not None and verdicts.get(key):
            try:
                kept = review.keep(text, verdicts[key])
                text, removed = kept[0], list(kept[1])
            except Exception as exc:
                log.warning("the self-check result for %s could not be applied: %s", key, exc)
                removed = []
        safe, dropped = audit.apply(text, ledger)
        sections[key] = safe
        withheld.extend(removed)
        withheld.extend(dropped)
        removed_count += len(removed)
        if written and (len(removed) + len(dropped)) * 2 >= written:
            thin.append(key)        # half or more was removed: what is left does not stand as a section
    counts = None
    if review is not None:
        try:
            counts = review.summary(verdicts)
        except Exception as exc:
            log.warning("the self-check summary failed: %s", exc)
    return {"sections": sections, "withheld": withheld, "removed": removed_count, "review": counts,
            "thin": thin}


def _sentence_count(audit, text: str) -> int:
    try:
        return sum(len(audit.sentences(p)) for p in str(text or "").split("\n\n") if p.strip())
    except Exception:
        return 0


FALLBACK_SECTIONS = ("results", "financial_position", "cash_flow")


def _fill_sections(sections: dict, thin: list, writer_mod, audit, ledger, company: dict) -> list[str]:
    """A written section never vanishes: one that came back empty, or lost half or more of its
    sentences to the checks, is replaced by sentences built in code from the same figures (and
    passed through the same audit). Returns the keys that were filled."""
    build = getattr(writer_mod, "fallback_section", None)
    if build is None:
        return []
    filled = []
    for key in FALLBACK_SECTIONS:
        if sections.get(key) and key not in (thin or []):
            continue
        try:
            built = build(key, ledger, company) or ""
            if "[[F:" in built and audit is not None:
                built, _dropped = audit.apply(built, ledger)
        except Exception as exc:
            log.warning("code-built %s section failed: %s", key, exc)
            continue
        if built:
            sections[key] = built
            filled.append(key)
    return filled


SELF_CHECK_NOTE = "The self-check removed"      # an informative note, not a missing part
BEAR_LIMIT = 4
FILED_BEAR_POINTS = 2


def _filed_bear_points(thesis_view: dict | None, risk_themes: list) -> int:
    """Add up to FILED_BEAR_POINTS of the company's own risk statements to the bear case, as the
    original report does ("The company states that ..."): the exact quote from the annual filing
    with its link, never a paraphrase. Only while the bear case has room. Returns how many."""
    if not isinstance(thesis_view, dict) or not risk_themes:
        return 0
    bear = thesis_view.get("bear")
    if not isinstance(bear, list):
        return 0
    added = 0
    for theme in risk_themes:
        if len(bear) >= BEAR_LIMIT or added >= FILED_BEAR_POINTS:
            break
        if not isinstance(theme, dict):
            continue
        # the filing's words; a list bullet glyph in front of them is layout, not wording
        quote = str(theme.get("quote") or "").strip().lstrip("\u2022\u00b7\u25e6\u25aa*\u2013\u2014- \t").strip()
        source = theme.get("source") if isinstance(theme.get("source"), dict) else {}
        url = str(source.get("url") or "")
        if not quote or not url.startswith("https://"):
            continue
        if not _ADVERSE.search(quote):
            continue          # a sentence of the risk section that states no harm is not a bear point
        where = _html.escape(str(source.get("title") or "annual filing"))
        link = (f'<a class="src" href="{_html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">({where})</a>')
        summary = str(theme.get("summary_html") or "").strip()
        if summary:
            # the risk in one checked sentence, attributed to the filing; the exact quote is shown
            # once, with the risk themes, instead of word for word in two places
            body = f"A risk the company states in its annual filing: {summary} {link}"
            rule = "A risk the company itself states in its annual filing (its exact words are under Risk themes)"
        else:
            body = f"The company states in its annual filing: \u201c{_html.escape(quote)}\u201d {link}"
            rule = "A risk the company itself states in its annual filing (exact quote)"
        bear.append({"html": body, "method": "filed", "signal": "risk_theme", "rule": rule})
        added += 1
    if added and isinstance(thesis_view.get("counts"), dict):
        thesis_view["counts"]["bear"] = len(bear)
        thesis_view["counts"]["filed"] = added
    return added


def _audit_only(raw: dict, audit, ledger) -> tuple[dict, list]:
    sections, withheld = {}, []
    for key, text in raw.items():
        safe, dropped = audit.apply(text, ledger)
        sections[key] = safe
        withheld.extend(dropped)
    return sections, withheld


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def run(job_id: str) -> None:
    from backend.sources.http import SourceUnavailable

    reg = jobs.registry()
    job = reg.get(job_id)
    if job is None:
        return

    def stage(name: str, message: str | None = None, **extra) -> None:
        if reg.update(job_id, step=name, progress=PROGRESS[name], message=message or MESSAGES[name],
                      **extra) is None:
            raise JobGone()          # deleted while it ran: stop at the next step, write nothing

    def fail(message: str) -> None:
        reg.update(job_id, status="error", error=message, message=message, finished_at=now_iso())

    def event(kind: str, message: str, meta: dict | None = None) -> None:
        if hasattr(reg, "append_event"):
            try:
                reg.append_event(job_id, kind, message, meta)
            except Exception as exc:  # the event log is a nicety
                log.info("event not recorded for %s: %s", job_id, exc)

    notes: list[str] = []
    fetch_pool = None
    try:
        stage("Starting", status="running", started_at=now_iso())

        from backend.sources import massive, sec, tickers

        # Company Info -------------------------------------------------------------------------
        stage("Company Info")
        symbol = tickers.normalise(job.stock_code)
        cik = sec.cik_for(symbol)
        if not cik:
            raise JobFailed(f"No SEC registrant found for {symbol}.")
        name = sec.company_name(symbol) or job.company_name or symbol
        try:
            from backend.naming import display_name
            name = display_name(name) or name          # the SEC lists many names in capitals
        except Exception:
            pass
        reg.update(job_id, company_name=name)

        # Data Fetch: every source at once ----------------------------------------------------
        stage("Data Fetch")
        fetch_started = time.monotonic()
        fetch_pool = ThreadPoolExecutor(max_workers=max(1, int(settings.FETCH_WORKERS)),
                                        thread_name_prefix=f"fetch-{job_id[:8]}")
        peer_origin = {"house": False, "industry": False}

        def related_tickers() -> list:
            """Peers in the same line of business. The provider's related companies are kept when
            at least three share the company's industry group (it also lists companies that are
            merely held together in portfolios: a drinks company gets an insurer and an oil
            company). Otherwise the house sector group for a company on the coverage list;
            otherwise the provider's list as it is. A provider failure still raises."""
            listed = list(massive.related(symbol) or [])
            same = _same_industry(symbol, listed, massive) if listed else []
            if same is None:
                return listed                  # the company's own industry is unknown: no way to judge
            if len(same) >= 3:
                peer_origin["industry"] = True
                return same
            groups = _optional("backend.analysis.peer_groups")
            house = list(groups.fallback(symbol)) if groups is not None else []
            if house:
                peer_origin["house"] = True
                return house
            return listed

        fetch = {
            "filings": fetch_pool.submit(lambda: list(sec.filings(cik) or [])),
            "facts": fetch_pool.submit(sec.company_facts, cik),
            "bars": fetch_pool.submit(lambda: list(massive.daily_bars(symbol, PRICE_DAYS) or [])),
            "previous_close": fetch_pool.submit(massive.previous_close, symbol),
            "details": fetch_pool.submit(massive.details, symbol),
            "market_bars": fetch_pool.submit(lambda: list(massive.daily_bars(MARKET_PROXY, PRICE_DAYS) or [])),
            "related": fetch_pool.submit(related_tickers),
        }
        # resolved in the order the steps used to run, so the same failure wins as before
        filings = fetch["filings"].result()
        reg.update(job_id, edinet_total=len(filings))
        company_facts = fetch["facts"].result()
        bars: list = []
        previous_close = None
        try:
            bars = fetch["bars"].result()
            previous_close = fetch["previous_close"].result()
        except SourceUnavailable as exc:
            bars, previous_close = [], None
            notes.append(f"Prices are not available: {exc.reason}")
        reg.update(job_id, price_rows=len(bars))

        details: dict = {}
        try:
            details = fetch["details"].result() or {}
        except Exception as exc:  # optional
            log.info("details unavailable for %s: %s", symbol, exc)
        company = {"ticker": symbol, "name": name, "cik": cik,
                   "details": details if isinstance(details, dict) else {}}

        # Extraction ---------------------------------------------------------------------------
        stage("Extraction")
        from backend.facts import select
        from backend.ledger import Ledger
        ledger = Ledger()
        summary = select.statement_facts(company_facts, [_filing_dict(f) for f in filings], ledger, cik=cik)
        reg.update(job_id, edinet_scanned=len(filings), edinet_count=int(summary.get("filings_used", 0)),
                   financial_rows=int(summary.get("facts", 0)), financials_source="SEC EDGAR")
        if not summary.get("facts"):
            raise JobFailed(f"No reported figures were found in the SEC data for {symbol}.")
        if not _has_fiscal_year(ledger):
            raise JobFailed(f"No annual report figures were found in the SEC data for {symbol}: "
                            "the registrant has not filed an annual report yet.")
        financial = _is_financial(company["details"])

        # Analysis -----------------------------------------------------------------------------
        stage("Analysis")
        from backend.analysis import ratios
        ratios.compute(ledger, **_accepts(ratios.compute, derive_gross_profit=not financial))
        thesis_mod = _optional("backend.draft.thesis")
        signals: list = []
        if thesis_mod is not None:
            try:
                # which facts count as favourable or unfavourable is decided here, by rules in
                # code (it may add computed facts); the branch below only words them
                signals = list(thesis_mod.signals(ledger, **_accepts(thesis_mod.signals, financial=financial)) or [])
            except Exception as exc:
                log.warning("thesis signals unavailable for %s: %s", job_id, exc)
        disclosures_view = None
        disclosures_mod = _optional("backend.filings.disclosures")
        if disclosures_mod is not None:
            try:
                disclosures_view = list(disclosures_mod.recent(filings) or [])
            except Exception as exc:
                log.info("key disclosures unavailable for %s: %s", job_id, exc)

        # Valuation: scenario arithmetic and the company's own multiples (optional) --------------
        # Arithmetic under stated assumptions; never a value per share set against the price.
        # It changes the ledger, so it runs here, before the branches start reading it.
        stage("Valuation")
        scenarios_view = None
        multiples_view: list = []
        try:
            from backend.analysis import scenarios
            beta = None
            try:
                market_bars = _wait(fetch["market_bars"], fetch_started + _timeout("valuation"))
                beta = scenarios.beta_from_bars(bars, market_bars)
            except _Late:
                notes.append(LATE["market"])
            except Exception as exc:
                log.info("beta unavailable for %s: %s", symbol, exc)
            market_cap = company["details"].get("market_cap")
            if not financial:      # a cash-flow model does not describe a bank or insurer
                scenarios_view = scenarios.compute(
                    ledger, beta=beta, market_cap=market_cap if isinstance(market_cap, (int, float)) else None)
        except Exception as exc:
            log.warning("scenario arithmetic unavailable for %s: %s", job_id, exc)
        # the share count comes from the filings; market data's count is used only when the
        # filings' newest one is too old to multiply by today's price
        market_shares = (company["details"].get("weighted_shares_outstanding")
                         or company["details"].get("share_class_shares_outstanding"))
        if not isinstance(market_shares, (int, float)) or isinstance(market_shares, bool):
            market_shares = None
        close = None
        try:
            from backend.analysis import multiples
            close = (previous_close or {}).get("close")
            if close:
                multiples_view = list(multiples.compute(
                    ledger, price=float(close), price_date=(previous_close or {}).get("date"),
                    **_accepts(multiples.compute, fallback_shares=market_shares, financial=financial)) or [])
        except Exception as exc:
            log.info("multiples unavailable for %s: %s", job_id, exc)

        # The branches: all at once --------------------------------------------------------------
        session_id = f"report-{job_id}"
        tag = job_id[:8]
        started = time.monotonic()
        annual = _annual(filings)
        drafted: Future = Future()
        drafting = writer = audit = review = None
        try:
            from backend.draft import writer
            from backend.verify import audit
            review = _optional("backend.verify.review")
            drafting = _spawn(f"drafting-{tag}", _drafting, writer, audit, review, ledger, company,
                              session_id, drafted)
        except Exception as exc:
            log.warning("drafting could not start for %s: %s", job_id, exc)
        peers_branch = _spawn(f"peers-{tag}", _peer_names, fetch["related"], sec, tag, cik)
        found = _spawn(f"passages-{tag}", _risk_passages, annual, sec, _optional("backend.filings.passages"))
        risk_branch = _spawn(f"risk-{tag}", _risk_themes, found, annual,
                             _optional("backend.analysis.risk"), session_id)
        thesis_branch = (_spawn(f"thesis-{tag}", _thesis, thesis_mod, ledger, company, signals, session_id,
                                financial)
                         if thesis_mod is not None else None)
        peer_table_branch = _spawn(f"peer-table-{tag}", _peer_table, fetch["related"],
                                   _optional("backend.analysis.peers"), sec, cik)
        news_mod = _optional("backend.research.news")
        news_branch = (_spawn(f"news-{tag}", news_mod.digest, symbol, name, session_id=session_id)
                       if news_mod is not None else None)
        releases_mod = _optional("backend.research.releases")
        release_branch = (_spawn(f"release-{tag}", releases_mod.latest, filings, session_id=session_id)
                          if releases_mod is not None else None)
        event("branches", "Started at the same time: peers and their filed figures, risk themes, "
              + ("web news, " if news_branch is not None else "")
              + ("the latest results release, " if release_branch is not None else "")
              + ("bull and bear cases, " if thesis_branch is not None else "")
              + "drafting with the self-check")

        # Peers --------------------------------------------------------------------------------
        stage("Peers")
        peers: list[dict] = []
        try:
            peers = _wait(peers_branch, started + _timeout("peers"))
        except _Late:
            related = fetch["related"]
            if related.done() and related.exception() is None:
                peers = [{"ticker": t, "name": ""} for t in _unique_peers(list(related.result() or []), sec, cik)]
                notes.append(LATE["peer_names"])
            else:
                peers = []
                notes.append(LATE["peers"])
        except Exception as exc:
            peers = []
            reason = getattr(exc, "reason", None) or "the peer list could not be fetched"
            notes.append(f"Peers are not available: {reason}")

        peer_table = None
        try:
            peer_table = _wait(peer_table_branch, started + _timeout("peers"))
        except _Late:
            notes.append(LATE["peer_table"])
        except Exception as exc:
            log.info("peer figures unavailable for %s: %s", job_id, exc)
        if not isinstance(peer_table, dict):
            peer_table = None
        if peer_table is not None and peer_origin["house"]:
            groups = _optional("backend.analysis.peer_groups")
            if groups is not None:
                peer_table["note"] = (str(peer_table.get("note") or "") + " " + groups.NOTE).strip()
        elif peer_table is not None and peer_origin["industry"]:
            peer_table["note"] = (str(peer_table.get("note") or "") + " Peers: the market data provider's "
                                  "related companies that are in the same industry group.").strip()

        # Valuation methods (per share): they need the peers' own multiples, so they are priced
        # here, on the job's own thread; the advisor (a model call) weighs them in a branch.
        valuation_view = None
        advisor_branch = None
        advisor_started = time.monotonic()
        valuation_mod = _optional("backend.analysis.valuation")
        if valuation_mod is not None:
            try:
                valuation_view = valuation_mod.compute(
                    ledger, price=float(close) if close else None,
                    price_date=(previous_close or {}).get("date"), shares=market_shares,
                    shares_note="market data's share count" if market_shares else None,
                    scenarios=scenarios_view, peer_table=peer_table,
                    **_accepts(valuation_mod.compute, financial=financial))
            except Exception as exc:
                log.warning("valuation methods unavailable for %s: %s", job_id, exc)
            if not isinstance(valuation_view, dict):
                valuation_view = None
            advisor_mod = _optional("backend.analysis.advisor")
            if valuation_view is not None and advisor_mod is not None and valuation_view.get("priced"):
                advisor_branch = _spawn(f"advisor-{tag}", advisor_mod.weigh, valuation_view, company, ledger,
                                        session_id=session_id,
                                        **_accepts(advisor_mod.weigh, financial=financial))

        # Drafting: the sections and their self-check, the risk themes, the bull and bear cases --
        stage("Drafting")
        sections: dict[str, str] = {}
        withheld: list[str] = []
        thin_sections: list[str] = []
        review_counts = None
        if drafting is None:
            notes.append("The written sections could not be produced.")
        else:
            try:
                drafted_at, raw = _wait(drafted, started + _timeout("drafting"))
                try:
                    done = _wait(drafting, drafted_at + _timeout("review"))
                    sections, withheld = dict(done["sections"]), list(done["withheld"])
                    thin_sections = list(done.get("thin") or [])
                    review_counts = done.get("review")
                    if done.get("removed"):
                        notes.append(f"{SELF_CHECK_NOTE} {_plural(done['removed'], 'sentence')}.")
                except _Late:
                    notes.append(LATE["review"])
                    sections, withheld = _audit_only(raw, audit, ledger)
            except _Late:
                sections, withheld = {}, []
                notes.append(LATE["drafting"])
            except Exception as exc:
                log.warning("drafting failed for %s: %s", job_id, exc)
                sections, withheld = {}, []
                notes.append("The written sections could not be produced.")
        if review_counts is not None:
            try:
                event("review", review.describe(review_counts) if hasattr(review, "describe")
                      else f"Self-check: {review_counts}", {"review": review_counts})
            except Exception as exc:
                log.info("review event not recorded for %s: %s", job_id, exc)

        thesis_view = None
        if thesis_branch is not None:
            try:
                thesis_view = _wait(thesis_branch, started + _timeout("thesis"))
            except _Late:
                notes.append(LATE["thesis"])
            except Exception as exc:
                log.warning("bull and bear cases failed for %s: %s", job_id, exc)
                notes.append(LATE["thesis"])
            if thesis_view is not None and not isinstance(thesis_view, dict):
                thesis_view = None
            if thesis_view is not None:
                withheld.extend(str(w) for w in thesis_view.get("withheld") or [])
                counts = thesis_view.get("counts") if isinstance(thesis_view.get("counts"), dict) else {}
                bull = counts.get("favourable", len(thesis_view.get("bull") or []))
                bear = counts.get("unfavourable", len(thesis_view.get("bear") or []))
                event("thesis", f"Bull and bear cases: {bull} favourable, {bear} unfavourable signals")

        if valuation_view is not None:
            advice = None
            if advisor_branch is not None:
                try:
                    advice = _wait(advisor_branch, advisor_started + _timeout("advisor"))
                except _Late:
                    advice = None          # the default weights are used and the panel says so
                except Exception as exc:
                    log.warning("valuation advisor failed for %s: %s", job_id, exc)
            try:
                if isinstance(advice, dict):
                    withheld.extend(str(w) for w in advice.get("withheld") or [])
                    valuation_view = valuation_mod.blend(
                        valuation_view, advice.get("weights") or None,
                        rationale_html=advice.get("rationale_html"),
                        advisor_method=str(advice.get("method") or "default"))
                else:
                    valuation_view = valuation_mod.blend(valuation_view, None)
                method = ((valuation_view or {}).get("advisor") or {}).get("method") or "default"
                event("valuation", f"Valuation: {valuation_view.get('priced')} of {valuation_view.get('total')} "
                      f"methods priced; weights by {'the AI advisor' if method == 'model' else 'default'}")
            except Exception as exc:
                log.warning("valuation blend failed for %s: %s", job_id, exc)
                valuation_view = None

        # Risk themes from the newest annual filing's own risk section (optional): each theme
        # carries an exact quote from the filing, checked in code, and a link to it.
        risk_themes: list = []
        try:
            risk_themes = list(_wait(risk_branch, started + _timeout("risk")) or [])
        except _Late:
            notes.append(LATE["risk"])
        except Exception as exc:
            log.warning("risk themes unavailable for %s: %s", job_id, exc)
        try:
            from backend.ledger import Source
            for theme in risk_themes:
                src = theme.get("source") or {}
                if str(src.get("url", "")).startswith("https://"):
                    ledger.add_source(Source(id="", type="edinet", url=src["url"],
                                             title=str(src.get("title") or "SEC filing"),
                                             date=str(src.get("date") or ""),
                                             snippet=str(theme.get("quote") or "")[:240]))
        except Exception as exc:
            log.warning("risk theme sources not added for %s: %s", job_id, exc)

        news_view = None
        if news_branch is not None:
            try:
                news_view = _wait(news_branch, started + _timeout("news"))
            except _Late:
                notes.append(LATE["news"])
            except Exception as exc:
                log.warning("web news unavailable for %s: %s", job_id, exc)
            if not isinstance(news_view, dict) or not news_view.get("articles"):
                news_view = None
        release_view = None
        if release_branch is not None:
            try:
                release_view = _wait(release_branch, started + _timeout("release"))
            except _Late:
                notes.append(LATE["release"])
            except Exception as exc:
                log.warning("results release unavailable for %s: %s", job_id, exc)
            if not isinstance(release_view, dict) or not release_view.get("statements"):
                release_view = None
        try:
            from backend.ledger import Source
            for article in (news_view or {}).get("articles") or []:
                url = str(article.get("url") or "")
                if url.startswith("https://") and article.get("title"):
                    ledger.add_source(Source(
                        id="", type="web", url=url, title=str(article["title"])[:200],
                        date=str(article.get("date") or ""),
                        snippet=(f"{article.get('publisher') or 'News'}: {article.get('summary') or ''}")[:240]))
            if release_view is not None and str(release_view.get("url") or "").startswith("https://"):
                ledger.add_source(Source(
                    id="", type="edinet", url=str(release_view["url"]),
                    title=str(release_view.get("source_title") or "Results release"),
                    date=str(release_view.get("filed") or ""),
                    snippet=str((release_view["statements"][0] or {}).get("quote") or "")[:240]))
        except Exception as exc:
            log.warning("research sources not added for %s: %s", job_id, exc)
        for view in (news_view, release_view):
            withheld.extend(str(w) for w in (view or {}).get("withheld") or [])
        if news_view is not None:
            event("news", f"Web research: {len(news_view['articles'])} articles, "
                  f"{len(news_view.get('topics') or [])} topics")
        if release_view is not None:
            event("release", f"Results release: {len(release_view['statements'])} statements quoted")

        try:
            _filed_bear_points(thesis_view, risk_themes)
        except Exception as exc:
            log.info("filed bear points not added for %s: %s", job_id, exc)

        try:
            from backend.draft import writer as _writer_mod
            filled = _fill_sections(sections, thin_sections, _writer_mod, audit, ledger, company)
            if filled:
                event("sections", "Built in code after the checks: " + ", ".join(filled))
        except Exception as exc:
            log.warning("section fallbacks failed for %s: %s", job_id, exc)

        if not sections.get("overview"):
            # the model wrote no overview (or all of it was withheld): build it from the ledger
            try:
                from backend.draft import writer as _writer
                built = _writer.fallback_overview(ledger, company)
                if built:
                    sections["overview"] = built
            except Exception as exc:  # the report still renders without it
                log.warning("overview fallback failed for %s: %s", job_id, exc)

        # what the Withheld list shows is read by people: no placeholder syntax, nothing twice
        readable = getattr(audit, "readable", None) if audit is not None else None
        seen_withheld: set[str] = set()
        tidy: list[str] = []
        for line in withheld:
            text = str(line)
            if readable is not None:
                try:
                    text = readable(text)
                except Exception:
                    pass
            if text.strip() and text not in seen_withheld:
                seen_withheld.add(text)
                tidy.append(text)
        withheld = tidy

        # Rendering ----------------------------------------------------------------------------
        stage("Rendering")
        from backend import render
        current = reg.get(job_id)
        if current is None:
            raise JobGone()
        # the deeper parts are passed only to a renderer that takes them
        accepted = inspect.signature(render.build_context).parameters
        extra = {name: value for name, value in (("scenarios", scenarios_view), ("risk_themes", risk_themes),
                                                 ("multiples", multiples_view), ("review", review_counts),
                                                 ("thesis", thesis_view), ("peer_table", peer_table),
                                                 ("disclosures", disclosures_view),
                                                 ("valuation", valuation_view), ("news", news_view),
                                                 ("release", release_view), ("financial", financial))
                 if name in accepted}
        context = render.build_context(job=current.as_dict(), company=company, ledger=ledger,
                                       sections=sections, withheld=withheld, bars=bars,
                                       previous_close=previous_close, peers=peers, notes=notes, **extra)
        html = render.html(context)
        out_dir = settings.reports_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        file_name = contract.report_file_name(symbol, job_id[:8])
        path = out_dir / file_name
        path.write_text(html, encoding="utf-8")
        ledger_doc = dict(ledger.to_json())
        ledger_doc["company"] = company
        ledger_doc["risk_themes"] = risk_themes
        ledger_doc["multiples"] = multiples_view
        ledger_doc["review"] = review_counts
        ledger_doc["thesis"] = thesis_view
        ledger_doc["peer_table"] = peer_table
        ledger_doc["valuation"] = valuation_view
        ledger_doc["news"] = news_view
        ledger_doc["release"] = release_view
        (out_dir / ledger_file_name(file_name)).write_text(
            json.dumps(ledger_doc, ensure_ascii=False, default=_json_default), encoding="utf-8")
        sources = [s.as_dict() for s in ledger.sources()]
        reg.update(job_id, sources=sources, source_count=len(sources), warnings=list(notes))
        reg.update(job_id, html_file=file_name)

        # "warning" means a part of the report is missing (prices, a late branch). A sentence the
        # checks removed is the system working, not a fault: the report lists it and is complete.
        missing = [n for n in notes if not n.startswith(SELF_CHECK_NOTE)]
        if missing:
            stage("Complete", "Report ready. " + " ".join(missing)[:300], status="warning",
                  finished_at=now_iso(), error=None)
        else:
            stage("Complete", status="complete", finished_at=now_iso(), error=None)
    except JobGone:
        log.info("job %s was deleted while it ran; stopped", job_id)
    except JobFailed as exc:
        fail(str(exc))
    except SourceUnavailable as exc:
        fail(exc.reason or "A data source is unavailable.")
    except ValueError as exc:
        # tickers.normalise rejects a symbol with ValueError
        log.warning("job %s failed: %s", job_id, exc)
        fail("The report could not be generated.")
    except Exception:
        log.exception("job %s failed", job_id)
        fail("The report could not be generated.")
    finally:
        if fetch_pool is not None:
            # never wait here for a slow optional fetch; drop what has not started
            fetch_pool.shutdown(wait=False, cancel_futures=True)
        final = reg.get(job_id)
        if final is not None and final.status not in contract.TERMINAL:
            fail("The report could not be generated.")


def ledger_file_name(report_file: str) -> str:
    """`report_X_1a2b3c4d.html` -> `report_X_1a2b3c4d.ledger.json`."""
    stem = report_file[:-5] if report_file.endswith(".html") else report_file.rsplit(".", 1)[0]
    return f"{stem}.ledger.json"


def _json_default(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return str(value)


def _guarded(job_id: str) -> None:
    with _semaphore:
        run(job_id)


def start(job_id: str) -> threading.Thread:
    thread = threading.Thread(target=_guarded, args=(job_id,), name=f"report-{job_id[:8]}", daemon=True)
    thread.start()
    return thread
