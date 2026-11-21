"""Pick reported facts out of the SEC's companyfacts document and put them in the ledger.

The trap this module exists to avoid: an entry's `fy` and `fp` describe the FILING, not the value.
One annual report for fiscal 2024 repeats the 2023 and 2022 figures, all labelled fy=2024. So a
value's period is decided only from its own `start` and `end` dates:

- a duration of 350 to 380 days IN AN ANNUAL REPORT is a fiscal year, named `FY{year of its end}`
  (the same length in a quarterly report is a trailing twelve months and is ignored);
- a duration of 80 to 100 days is a quarter, named `Q{n}-{fiscal year}`, where n counts from the
  company's fiscal year-end month and the fiscal year is the one the quarter falls in (a quarter
  ending December 2023 for a company whose year ends in September is `Q1-2024`);
- any other duration (the six- and nine-month year-to-date totals in a 10-Q) is ignored;
- an instant (a balance) is named by its ISO end date, e.g. `2024-09-28`.

52/53-week calendars: a year "ending in December" can end on 2 January. An end date in the first
seven days of a month is therefore read as the end of the previous month when naming the period
(otherwise the years ending 28 Dec 2019 and 2 Jan 2021 would skip FY2020 and two different years
could share one name). The ISO date of an instant is never shifted.

The company's own name for its year: most companies name a fiscal year by the calendar year it
ends in (NVIDIA's year to January 2026 is its fiscal 2026), some by the year it starts in (Target's
year to January 2026 is its fiscal 2025). The convention is read ONCE, from the company's newest
annual report (`fiscal_year_offset_of`: the `fy` of that report's latest fiscal year against the
year of its end), and that one offset names every fiscal year and quarter of the company. `fy` of
any other entry still describes the filing, not the value, and is never used.

Choosing among a metric's tags (`metrics.py` lists them in fallback order):
- one tag per metric, so all its periods share one definition: the first listed tag that is
  current. A tag whose data ends more than STALE_DAYS before another listed tag's is one the
  company stopped using and is passed over. Freshness is read from annual reports: the newest
  fiscal year for a flow, the newest balance reported in an annual report for a balance (any form
  only when no annual report carries the tag), so a tag a company uses only in its 10-K does not
  look stale next to one it also uses in its 10-Qs;
- history backfill: fiscal years (and year-end balances) EARLIER than the chosen tag's first
  annual one are taken from another listed tag of the same taxonomy and unit, in list order, when
  the two are the same quantity for this company: they agree within 0.5% on every annual period
  they share, or share none (a clean switch). Tags that overlap and differ are never mixed;
- a per-share dividend tag whose twelve-month value is the quarterly rate (the same value tagged
  for three, six, nine and twelve months) is not usable for that company (`_tags_a_quarterly_rate`);
- shares outstanding keeps the entries of both of its tags (the balance-sheet count at the year
  end and the cover-page count weeks later); the balance-sheet tag wins on a shared date.

Per period, the VALUE is the newest-filed one (a restatement wins); the SOURCE is the
earliest-filed annual report that carries that same value for that period, else the earliest
filing that does (a year-end balance cites the 10-K, not the next 10-Q that repeats it).
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from backend.facts.metrics import METRICS, Metric
from backend.ledger import Fact, Ledger, Source

ANNUAL_DAYS = (350, 380)
QUARTER_DAYS = (80, 100)
# six- and nine-month year-to-date totals in a 10-Q (read only to test a dividend tag)
YEAR_TO_DATE_DAYS = (150, 300)
# a tag whose data ends this much earlier than another listed tag's is one the company stopped using
STALE_DAYS = 60
# two tags agree on a period when they differ by at most this share (history backfill)
BACKFILL_TOLERANCE = 0.005
# per-share flows some companies tag with the quarterly rate in every context
RATE_CHECKED_METRICS = frozenset({"dividends_per_share"})
# metrics whose tags hold the same quantity on different dates: the entries of every current tag
MERGED_METRICS = frozenset({"shares_outstanding"})

# Periodic reports only. Registration statements and current reports can carry pro forma or
# partial figures under the same tags.
PERIODIC_FORMS = frozenset({
    "10-K", "10-K/A", "10-KT", "10-KT/A", "10-Q", "10-Q/A", "10-QT", "10-QT/A",
    "20-F", "20-F/A", "40-F", "40-F/A",
})

# Only an annual report states a fiscal year. A quarterly report can carry a twelve-month total
# too (some companies report the trailing twelve months to each quarter-end): that is not a
# fiscal year, and must never be named or shown as one.
ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"})

SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
SEC_PREFIX = "https://www.sec.gov/"

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PER_SHARE_RE = re.compile(r"^([A-Z]{3})/shares$")
_FY_RE = re.compile(r"^FY(\d{4})$")


# ---- periods -------------------------------------------------------------------------------
def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def nominal_end(end: date) -> date:
    """The month-end a 52/53-week period stands for: an end in the first seven days of a month
    belongs to the previous month (2 Jan 2021 -> 31 Dec 2020); any other date is itself."""
    if end.day <= 7:
        return end.replace(day=1) - timedelta(days=1)
    return end


def quarter_name(end: date, fiscal_year_end_month: int = 12, fiscal_year_offset: int = 0) -> str:
    """`Q{n}-{fiscal year}` for a three-month period ending on `end`."""
    month = nominal_end(end)
    m, fye = month.month, fiscal_year_end_month
    n = ((m - fye - 1) % 12) // 3 + 1
    fiscal_year = month.year if m <= fye else month.year + 1
    return f"Q{n}-{fiscal_year + fiscal_year_offset}"


def period_of(entry: Mapping, kind: str, fiscal_year_end_month: int = 12,
              fiscal_year_offset: int = 0) -> str | None:
    """The period an entry's value belongs to, from its own dates (never from fy/fp), or None
    when it is not a period the report uses (a six- or nine-month total, broken dates, a
    duration under an instant metric or the reverse). `fiscal_year_offset` is the company's
    naming convention (`fiscal_year_offset_of`): -1 names a year by the calendar year it starts in."""
    end = _date(entry.get("end"))
    if end is None:
        return None
    start_raw = entry.get("start")
    if kind == "instant":
        return None if start_raw else end.isoformat()
    if kind != "duration" or not start_raw:
        return None
    start = _date(start_raw)
    if start is None:
        return None
    days = (end - start).days
    if ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]:
        return f"FY{nominal_end(end).year + fiscal_year_offset}"
    if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
        return quarter_name(end, fiscal_year_end_month, fiscal_year_offset)
    return None


def year_end_instant(ledger: Ledger, fiscal_year: int) -> str | None:
    """The ISO date of fiscal year `fiscal_year`'s last day, i.e. the period name of its
    year-end balances (`2024-09-28` for Apple's FY2024), as recorded by `statement_facts`."""
    return ledger.period_end(f"FY{int(fiscal_year)}")


def fiscal_years(ledger: Ledger) -> list[int]:
    """Every fiscal year that has at least one annual fact, newest first."""
    years = set()
    for key in ledger.keys():
        for period in ledger.periods(key):
            m = _FY_RE.match(period)
            if m:
                years.add(int(m.group(1)))
    return sorted(years, reverse=True)


def fiscal_year_end_month_of(company_facts: Mapping) -> int | None:
    """The company's fiscal year-end month, read from its newest annual (350-380 day) entry in an
    ANNUAL report (a quarterly report's trailing twelve months end on a quarter-end, not on the
    fiscal year end); None when it has none."""
    latest: date | None = None
    for metric in METRICS.values():
        if metric.kind != "duration":
            continue
        for taxonomy, tag in metric.tags:
            for entries in _units(company_facts, taxonomy, tag).values():
                for e in entries if isinstance(entries, list) else ():
                    if not isinstance(e, Mapping) or str(e.get("form") or "") not in ANNUAL_FORMS:
                        continue
                    start, end = _date(e.get("start")), _date(e.get("end"))
                    if start and end and ANNUAL_DAYS[0] <= (end - start).days <= ANNUAL_DAYS[1]:
                        if latest is None or end > latest:
                            latest = end
    return nominal_end(latest).month if latest else None


def fiscal_year_offset_of(company_facts: Mapping) -> int:
    """How the company names its fiscal year, read from its NEWEST annual report: the `fy` that
    report gives its latest fiscal year (the annual-length entry with the latest end) minus the
    calendar year of that year's (nominal) end. 0 for most companies (NVIDIA, Walmart: the year to
    January 2026 is fiscal 2026); -1 for a company that names the year by the year it starts in
    (Target, Five Below: the year to January 2026 is fiscal 2025). -1 is accepted only for a year
    ending January to June (a December year labelled one lower is a filing error, not a
    convention); anything else, or no annual report, is 0."""
    newest: tuple | None = None
    for metric in METRICS.values():
        if metric.kind != "duration":
            continue
        for taxonomy, tag in metric.tags:
            for entries in _units(company_facts, taxonomy, tag).values():
                for e in entries if isinstance(entries, list) else ():
                    if not isinstance(e, Mapping) or str(e.get("form") or "") not in ANNUAL_FORMS:
                        continue
                    fy = e.get("fy")
                    start, end, filed = _date(e.get("start")), _date(e.get("end")), _date(e.get("filed"))
                    if isinstance(fy, bool) or not isinstance(fy, int) or not (start and end and filed):
                        continue
                    if not ANNUAL_DAYS[0] <= (end - start).days <= ANNUAL_DAYS[1]:
                        continue
                    rank = (filed, _accession_key(e.get("accn")), end)
                    if newest is None or rank > newest[0]:
                        newest = (rank, end, fy)
    if newest is None:
        return 0
    _rank, end, fy = newest
    named = nominal_end(end)
    offset = fy - named.year
    if offset == 0 or (offset == -1 and named.month <= 6):
        return offset
    return 0


# ---- selection -----------------------------------------------------------------------------
def _units(company_facts: Mapping, taxonomy: str, tag: str) -> Mapping:
    facts = company_facts.get("facts") if isinstance(company_facts, Mapping) else None
    concept = ((facts or {}).get(taxonomy) or {}).get(tag) or {}
    units = concept.get("units") if isinstance(concept, Mapping) else None
    return units if isinstance(units, Mapping) else {}


def _pick_unit(units: Mapping, metric_unit: str) -> tuple[str, str] | None:
    """(the SEC's unit key, the unit stored on the fact). Money prefers USD and otherwise takes
    the filer's own currency (a 20-F filer may report in EUR): never relabelled as dollars."""
    keys = [k for k, v in units.items() if isinstance(v, list) and v]
    if metric_unit == "shares":
        return ("shares", "shares") if "shares" in keys else None
    if metric_unit == "USD":
        if "USD" in keys:
            return "USD", "USD"
        found = sorted((k for k in keys if _CURRENCY_RE.match(k)), key=lambda k: (-len(units[k]), k))
        return (found[0], found[0]) if found else None
    if metric_unit == "USD/share":
        if "USD/shares" in keys:
            return "USD/shares", "USD/share"
        found = sorted((k for k in keys if _PER_SHARE_RE.match(k)), key=lambda k: (-len(units[k]), k))
        return (found[0], found[0].split("/")[0] + "/share") if found else None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _usable(entries: Iterable, metric: Metric, fye_month: int,
            offset: int = 0) -> list[tuple[str, dict]]:
    """(period, entry) for every entry the report can use: a periodic form, a number, a filing
    accession and date, and dates that name a period."""
    out = []
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        if str(e.get("form") or "") not in PERIODIC_FORMS:
            continue
        if _number(e.get("val")) is None or not e.get("accn") or _date(e.get("filed")) is None:
            continue
        period = period_of(e, metric.kind, fye_month, offset)
        if period and period.startswith("FY") and str(e.get("form") or "") not in ANNUAL_FORMS:
            continue      # twelve months in a quarterly report: a trailing total, not a fiscal year
        if period:
            out.append((period, dict(e)))
    return out


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _tags_a_quarterly_rate(entries: Iterable) -> bool:
    """True when the tag's twelve-month value is the quarterly rate, not the year's total: for
    some fiscal year (an annual report's 350-380 days), the annual value equals a three-month
    value of that year AND a six- or nine-month year-to-date value that cannot be a cumulative
    total, because the quarters reported inside it add up to more than it (Visa tags 0.67 for
    three, six, nine and twelve months). A company that really pays one dividend a year passes:
    its later quarters are zero, so its year to date is the sum of its quarters."""
    spans: dict[tuple[date, date], tuple[tuple, float]] = {}
    annual: list[tuple[date, date, float]] = []
    for e in entries:
        if not isinstance(e, Mapping) or str(e.get("form") or "") not in PERIODIC_FORMS:
            continue
        value, start, end = _number(e.get("val")), _date(e.get("start")), _date(e.get("end"))
        if value is None or start is None or end is None:
            continue
        rank = (str(e.get("filed") or ""), _accession_key(e.get("accn")))
        held = spans.get((start, end))
        if held is None or rank > held[0]:
            spans[(start, end)] = (rank, value)
        if str(e.get("form")) in ANNUAL_FORMS and ANNUAL_DAYS[0] <= (end - start).days <= ANNUAL_DAYS[1]:
            annual.append((start, end, value))
    values = {span: value for span, (_rank, value) in spans.items()}
    for fy_start, fy_end, _v in annual:
        total = values.get((fy_start, fy_end))
        if total is None or total <= 0:
            continue
        quarters = {(s, e): v for (s, e), v in values.items()
                    if QUARTER_DAYS[0] <= (e - s).days <= QUARTER_DAYS[1] and fy_start <= s and e <= fy_end}
        if not any(_close(v, total) for v in quarters.values()):
            continue
        for (s, e), y in values.items():
            if s != fy_start or e >= fy_end or not YEAR_TO_DATE_DAYS[0] <= (e - s).days <= YEAR_TO_DATE_DAYS[1]:
                continue
            inside = sum(v for (qs, qe), v in quarters.items() if qe <= e)
            if _close(y, total) and inside > y + 1e-9:
                return True
    return False


class _Tag:
    """One listed tag that has usable entries for a metric."""
    __slots__ = ("taxonomy", "tag", "unit", "pairs", "annual_reach", "any_reach")

    def __init__(self, taxonomy: str, tag: str, unit: str, pairs: list[tuple[str, dict]]) -> None:
        self.taxonomy, self.tag, self.unit, self.pairs = taxonomy, tag, unit, pairs
        # how far its data reaches: the newest end reported in an annual report (a fiscal year,
        # or a balance in a 10-K), and the newest end of any period in any periodic report
        ends = [_date(e["end"]) for _p, e in pairs]
        annual = [_date(e["end"]) for p, e in pairs
                  if p.startswith("FY") or (p[:1].isdigit() and str(e.get("form") or "") in ANNUAL_FORMS)]
        self.annual_reach = max(annual) if annual else None
        self.any_reach = max(ends)


def _candidates(company_facts: Mapping, metric: Metric, fye_month: int, offset: int = 0) -> list[_Tag]:
    """Every listed tag with usable entries, in list order (a dividend tag that states the
    quarterly rate is left out)."""
    out = []
    for taxonomy, tag in metric.tags:
        units = _units(company_facts, taxonomy, tag)
        picked = _pick_unit(units, metric.unit)
        if not picked:
            continue
        pairs = _usable(units[picked[0]], metric, fye_month, offset)
        if not pairs:
            continue
        if metric.key in RATE_CHECKED_METRICS and _tags_a_quarterly_rate(units[picked[0]]):
            continue
        out.append(_Tag(taxonomy, tag, picked[1], pairs))
    return out


def _fresh(candidates: list[_Tag]) -> list[_Tag]:
    """The candidates the company still uses, in list order: those whose annual reach is within
    STALE_DAYS of the best one; by the newest end of any form only when no annual report carries
    any of them."""
    annual = [c.annual_reach for c in candidates if c.annual_reach is not None]
    if annual:
        best = max(annual)
        return [c for c in candidates
                if c.annual_reach is not None and (best - c.annual_reach).days <= STALE_DAYS]
    best_any = max(c.any_reach for c in candidates)
    return [c for c in candidates if (best_any - c.any_reach).days <= STALE_DAYS]


def _choose_tag(company_facts: Mapping, metric: Metric, fye_month: int, offset: int = 0):
    """The tag this company's data for `metric` comes from: the first tag in fallback order that
    has usable entries, passing over a tag the company stopped using, i.e. one whose data ends
    more than STALE_DAYS before another listed tag's (compared on annual reports, see `_fresh`).
    Without that, a tag retired years ago (or the US GAAP tags of a company that moved to IFRS)
    would hide every recent year. One tag per metric, so all its periods share one definition.
    Returns (taxonomy, tag, fact unit, [(period, entry)]) or None."""
    candidates = _candidates(company_facts, metric, fye_month, offset)
    if not candidates:
        return None
    chosen = _fresh(candidates)[0]
    return chosen.taxonomy, chosen.tag, chosen.unit, chosen.pairs


def _winners(pairs: list[tuple[str, dict]]) -> dict[str, tuple[dict, dict]]:
    """Per period: (the entry whose value is used, the entry whose filing is cited). The value is
    the newest-filed one (a restatement wins); the citation is the earliest-filed annual report
    carrying that same value for that period, else the earliest-filed filing that does."""
    groups: dict[str, list[dict]] = {}
    for period, entry in pairs:
        groups.setdefault(period, []).append(entry)
    out = {}
    for period, entries in groups.items():
        def rank(e):
            return (str(e["filed"])[:10], _accession_key(e["accn"]), str(e["end"]))
        value = max(entries, key=rank)
        same = [e for e in entries if _close(_number(e["val"]), _number(value["val"]))]
        annual = [e for e in same if str(e.get("form") or "") in ANNUAL_FORMS]
        cited = min(annual or same, key=rank)
        out[period] = (value, cited)
    return out


def _annual_values(candidate: _Tag, kind: str) -> dict[str, float]:
    """The tag's values for its annual periods: fiscal years for a flow, the balances reported in
    an annual report for a balance."""
    winners = _winners(candidate.pairs)
    if kind == "duration":
        return {p: _number(v["val"]) for p, (v, _c) in winners.items() if p.startswith("FY")}
    dates = {p for p, e in candidate.pairs if str(e.get("form") or "") in ANNUAL_FORMS}
    return {p: _number(v["val"]) for p, (v, _c) in winners.items() if p in dates}


def _period_order(period: str):
    m = _FY_RE.match(period)
    return int(m.group(1)) if m else period


def _agree(a: float, b: float) -> bool:
    scale = max(abs(a), abs(b))
    return scale == 0 or abs(a - b) <= BACKFILL_TOLERANCE * scale


def _backfill(chosen: _Tag, candidates: list[_Tag], kind: str) -> dict[str, tuple[dict, dict]]:
    """Annual periods EARLIER than the chosen tag's first annual one, from the other listed tags of
    the same taxonomy and unit (list order), each only when it is the same quantity for this
    company: it agrees within BACKFILL_TOLERANCE on every annual period the two share, or they
    share none (a clean switch). Returns {period: (value entry, cited entry)}."""
    own = _annual_values(chosen, kind)
    if not own:
        return {}
    first = min(_period_order(p) for p in own)
    out: dict[str, tuple[dict, dict]] = {}
    for other in candidates:
        if other is chosen or other.taxonomy != chosen.taxonomy or other.unit != chosen.unit:
            continue
        theirs = _annual_values(other, kind)
        if any(not _agree(own[p], theirs[p]) for p in own.keys() & theirs.keys()):
            continue
        winners = _winners(other.pairs)
        for period in theirs:
            if _period_order(period) < first and period not in out:
                out[period] = winners[period]
    return out


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _accession_key(accn: Any) -> str:
    return str(accn or "").replace("-", "").strip()


def filing_index_url(cik: str | int, accession: str) -> str:
    """The EDGAR folder of one filing (unpadded CIK, accession without dashes)."""
    return f"{SEC_ARCHIVE}/{int(str(cik).strip())}/{_accession_key(accession)}/"


def _filing_source(entry: Mapping, filing: Any, cik: str) -> Source:
    form = str(_get(filing, "form") or entry.get("form") or "").strip()
    filed = str(_get(filing, "filed") or entry.get("filed") or "")[:10]
    url = ""
    for candidate in (_get(filing, "viewer_url"), _get(filing, "url")):
        if isinstance(candidate, str) and candidate.startswith(SEC_PREFIX):
            url = candidate
            break
    if not url:
        url = filing_index_url(cik, str(entry["accn"]))
    return Source(id="", type="edinet", url=url, title=f"Form {form}, filed {filed}", date=filed,
                  snippet=f"XBRL financial data, accession {entry['accn']}")


def statement_facts(company_facts: Mapping, filings: list, ledger: Ledger, *, cik: str,
                    fiscal_year_end_month: int | None = None,
                    fiscal_year_offset: int | None = None) -> dict:
    """Add one reported fact per metric and period, each linked to the filing it came from.

    For each metric: the tag is chosen by `_choose_tag` (shares outstanding keeps every current
    tag, see MERGED_METRICS); its entries are grouped by period (from their own dates); for one
    period the entry with the newest `filed` date gives the value (a restatement) and the
    earliest annual report with that same value is cited (`_winners`); earlier years come from
    another tag only by the history backfill (`_backfill`). One "edinet" source is added per
    filing used: its inline-viewer link when the accession is in `filings` (dicts or objects with
    accession, form, filed, url, viewer_url), otherwise the EDGAR filing folder. A metric with no
    usable tag is left out, never zero.

    `fiscal_year_end_month` names the quarters; by default it is read from the newest annual
    entry (December if there is none). `fiscal_year_offset` is the company's naming convention,
    by default read from its newest annual report (`fiscal_year_offset_of`). Returns a summary:
    facts, filings_used, metrics_missing, taxonomy ("us-gaap", "ifrs-full", "mixed", or None when
    nothing was found), tags (the tag chosen per metric), backfilled ({metric: [tags]} for the
    earlier years taken from another tag), fiscal_year_end_month and fiscal_year_offset."""
    if fiscal_year_end_month is not None and not 1 <= int(fiscal_year_end_month) <= 12:
        raise ValueError(f"fiscal_year_end_month must be 1 to 12, got {fiscal_year_end_month!r}")
    fye = fiscal_year_end_month or fiscal_year_end_month_of(company_facts) or 12
    offset = int(fiscal_year_offset) if fiscal_year_offset is not None else fiscal_year_offset_of(company_facts)
    by_accession = {_accession_key(_get(f, "accession")): f for f in filings or ()
                    if _get(f, "accession")}
    added = 0
    used: set[str] = set()
    missing: list[str] = []
    tags: dict[str, str] = {}
    backfilled: dict[str, list[str]] = {}
    taxonomies: set[str] = set()
    for metric in METRICS.values():
        candidates = _candidates(company_facts, metric, fye, offset)
        if not candidates:
            missing.append(metric.key)
            continue
        fresh = _fresh(candidates)
        chosen = fresh[0]
        tags[metric.key] = f"{chosen.taxonomy}:{chosen.tag}"
        if chosen.taxonomy in ("us-gaap", "ifrs-full"):
            taxonomies.add(chosen.taxonomy)
        winners = _winners(chosen.pairs)
        if metric.key in MERGED_METRICS:
            # the same quantity on different dates: every current tag's entries, the first-listed
            # tag winning a date both report
            for other in fresh[1:]:
                if other.unit == chosen.unit:
                    for period, pick in _winners(other.pairs).items():
                        winners.setdefault(period, pick)
        for period, pick in _backfill(chosen, candidates, metric.kind).items():
            if period not in winners:
                winners[period] = pick
                source_tag = next(f"{c.taxonomy}:{c.tag}" for c in candidates
                                  if any(e is pick[0] for _p, e in c.pairs))
                if source_tag not in backfilled.setdefault(metric.key, []):
                    backfilled[metric.key].append(source_tag)
        for period, (value_entry, cited_entry) in winners.items():
            accn = _accession_key(cited_entry["accn"])
            source = _filing_source(cited_entry, by_accession.get(accn), cik)
            sid = ledger.add_source(source)
            used.add(accn)
            ledger.replace_fact(Fact(key=metric.key, period=period, value=_number(value_entry["val"]),
                                     unit=chosen.unit, source_ids=(sid,)))
            if metric.kind == "duration":
                ledger.set_period_end(period, str(value_entry["end"])[:10])
            added += 1
    if not taxonomies:
        taxonomy_used = None
    elif len(taxonomies) == 1:
        taxonomy_used = next(iter(taxonomies))
    else:
        taxonomy_used = "mixed"
    return {"facts": added, "filings_used": len(used), "metrics_missing": missing,
            "taxonomy": taxonomy_used, "tags": tags, "backfilled": backfilled,
            "fiscal_year_end_month": fye, "fiscal_year_offset": offset}


# ---- the fourth quarter --------------------------------------------------------------------
def q4_keys() -> list[str]:
    """Flows that add up over quarters (money amounts). Per-share figures do not: Q4 earnings
    per share is not the year's EPS minus three quarters, because share counts change."""
    return [m.key for m in METRICS.values() if m.kind == "duration" and m.unit == "USD"]


def derive_q4(ledger: Ledger, fiscal_year: int, keys: Iterable[str] | None = None) -> list[Fact]:
    """No filing reports a fourth quarter on its own (the 10-K covers the year). For each flow
    with the full year and all three reported quarters in the same unit, add Q4 = FY - Q1 - Q2 -
    Q3 as a computed fact with those four inputs. Otherwise nothing; an existing Q4 is kept."""
    y = int(fiscal_year)
    fy_period = f"FY{y}"
    q4_period = f"Q4-{y}"
    out: list[Fact] = []
    for key in (list(keys) if keys is not None else q4_keys()):
        if ledger.get(key, q4_period) is not None:
            continue
        refs = [(key, fy_period)] + [(key, f"Q{n}-{y}") for n in (1, 2, 3)]
        parts = [ledger.get(k, p) for k, p in refs]
        if any(f is None or f.value is None for f in parts):
            continue
        if len({f.unit for f in parts}) != 1:
            continue
        full, q1, q2, q3 = (f.value for f in parts)
        fact = ledger.add_fact(Fact(
            key=key, period=q4_period, value=full - q1 - q2 - q3, unit=parts[0].unit,
            inputs=tuple(refs), formula="full year - (Q1 + Q2 + Q3)",
            note="No filing reports the fourth quarter on its own: this is the full year less "
                 "the three reported quarters."))
        end = ledger.period_end(fy_period)
        if end:
            ledger.set_period_end(q4_period, end)
        out.append(fact)
    return out
