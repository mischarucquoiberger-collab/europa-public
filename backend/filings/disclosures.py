"""Key disclosures: the company's own filings of the last twelve months, newest first, each with
its date, its form, a short plain title and a link to the filing at the SEC.

    rows = recent(filings)          # the pipeline's list of sec.Filing (or equivalent dicts)

The description is built from the filings index only (the form and, for an 8-K, its item codes),
never from a model: `Current report · Results of operations and financial condition; Financial
statements and exhibits`. A filing without a usable date or an https link is left out.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from backend import format as fmt

log = logging.getLogger(__name__)

FORM_TITLES = {
    "10-K": "Annual report",
    "10-K/A": "Annual report (amended)",
    "10-Q": "Quarterly report",
    "10-Q/A": "Quarterly report (amended)",
    "8-K": "Current report",
    "8-K/A": "Current report (amended)",
    "20-F": "Annual report (foreign issuer)",
    "6-K": "Report of foreign issuer",
    "40-F": "Annual report (Canadian issuer)",
    "DEF 14A": "Proxy statement",
    "S-1": "Registration statement",
}

ITEM_TITLES = {
    "1.01": "Entry into a material agreement",
    "1.02": "Termination of a material agreement",
    "1.03": "Bankruptcy or receivership",
    "1.05": "Material cybersecurity incident",
    "2.01": "Completion of an acquisition or disposal",
    "2.02": "Results of operations and financial condition",
    "2.03": "Creation of a direct financial obligation",
    "2.04": "Triggering events on an obligation",
    "2.05": "Costs of exit or disposal activities",
    "2.06": "Material impairments",
    "3.01": "Notice of delisting or listing-rule failure",
    "3.02": "Unregistered sales of equity securities",
    "3.03": "Material modification to holders' rights",
    "4.01": "Change of certifying accountant",
    "4.02": "Non-reliance on earlier financial statements",
    "5.01": "Change in control",
    "5.02": "Departure or appointment of directors or officers",
    "5.03": "Amendments to articles or bylaws",
    "5.07": "Results of a shareholder vote",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
    "9.01": "Financial statements and exhibits",
}

CURRENT_REPORTS = frozenset({"8-K", "8-K/A"})
# forms whose report date is the end of the period they cover
PERIODIC_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A", "10-QT", "10-QT/A",
                            "20-F", "20-F/A", "40-F", "40-F/A"})

_ITEM_SPLIT = re.compile(r"[,;\s]+")


def _get(f, name: str):
    if isinstance(f, dict):
        return f.get(name)
    try:
        return getattr(f, name, None)
    except Exception:      # a property that cannot build its link (a malformed CIK)
        return None


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except (TypeError, ValueError):
        return None


def _words(d: date) -> str:
    """`2026-10-30` -> `30 Oct 2026`, in the report's own date wording."""
    return fmt.period_label(d.isoformat()).removeprefix("as of ")


def _link(f) -> str | None:
    for candidate in (_get(f, "viewer_url"), _get(f, "url")):
        if isinstance(candidate, str) and candidate.strip().startswith("https://"):
            return candidate.strip()
    return None


def item_titles(items) -> list[str]:
    """`"2.02,9.01"` -> the item titles in order, each once; an unknown code is `Item <code>`."""
    out: list[str] = []
    for code in _ITEM_SPLIT.split(str(items or "").strip()):
        code = code.strip().removeprefix("Item").strip()
        if not code:
            continue
        title = ITEM_TITLES.get(code, f"Item {code}")
        if title not in out:
            out.append(title)
    return out


def _detail(form: str, f) -> str:
    if form in CURRENT_REPORTS:
        return "; ".join(item_titles(_get(f, "items")))
    if form in PERIODIC_FORMS:
        period = _date(_get(f, "period"))
        return f"Period ended {_words(period)}" if period else ""
    return ""


def _entry(f, start: date, today: date) -> dict | None:
    filed = _date(_get(f, "filed"))
    if filed is None or not start <= filed <= today:
        return None
    url = _link(f)
    if url is None:
        return None
    form = str(_get(f, "form") or "").strip()
    if not form:
        return None
    return {"date": filed.isoformat(), "date_text": _words(filed), "form": form,
            "title": FORM_TITLES.get(form, form), "detail": _detail(form, f), "url": url}


def recent(filings, *, today: date | None = None, days: int = 365, limit: int = 30) -> list[dict]:
    """The filings filed within `days` before `today` (default: today), newest first, at most
    `limit`: {"date", "date_text", "form", "title", "detail", "url"}. Never raises."""
    try:
        if isinstance(today, datetime):
            today = today.date()
        today = today if isinstance(today, date) else date.today()
        start = today - timedelta(days=max(0, int(days)))
        found: list[dict] = []
        seen: set[str] = set()
        for f in list(filings or []):
            try:
                entry = _entry(f, start, today)
            except Exception as exc:     # one odd row never costs the others
                log.info("filing left out of the disclosures: %s", exc)
                entry = None
            if entry is None or entry["url"] in seen:
                continue
            seen.add(entry["url"])
            found.append(entry)
        # newest first; filings of one day keep the order they came in (the index's own)
        found.sort(key=lambda e: e["date"], reverse=True)
        return found[:max(0, int(limit))]
    except Exception as exc:
        log.warning("disclosures not available: %s", exc)
        return []
