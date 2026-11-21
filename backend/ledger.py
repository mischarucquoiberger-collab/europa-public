"""The evidence ledger: every number the report or the chat shows lives here, tied to a source.

Two kinds of fact:
- a REPORTED fact comes straight from a source (an SEC filing's XBRL data) and names at least one
  registered source id;
- a COMPUTED fact is arithmetic done in Python over other facts; it names its formula and its
  inputs as (key, period) pairs, and its sources are the sources of those inputs, followed down.

The ledger refuses anything else, so a figure without a source cannot enter it. A missing value is
simply absent (`get` returns None): never a zero, never a guess.
"""
from __future__ import annotations

import functools
import threading
import math
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable
from urllib.parse import urlsplit

from backend import contract


class LedgerError(ValueError):
    """A fact or source that would break the rule "every number is tied to a source"."""


@dataclass(frozen=True)
class Source:
    """Something the user can open. `type` is "edinet" for an SEC filing or XBRL fact (the
    interface's filings group) and "web" for anything else: see contract.SOURCE_TYPES."""
    id: str
    type: str
    url: str
    title: str
    date: str
    snippet: str = ""

    def as_dict(self) -> dict:
        """Exactly the fields the interface's Sources panel reads (contract.SOURCE_FIELDS)."""
        return {name: getattr(self, name) for name in contract.SOURCE_FIELDS}


@dataclass(frozen=True)
class Fact:
    """One value for one metric and one period.

    `period` is `FY2024`, `Q3-2024` or an ISO date (balance-sheet items), always derived from the
    fact's own dates. `value` None means "not available" and is only allowed for a computed fact
    (with a `note` saying why, e.g. a negative denominator)."""
    key: str
    period: str
    value: float | None
    unit: str
    source_ids: tuple[str, ...] = ()
    inputs: tuple[tuple[str, str], ...] = ()
    formula: str | None = None
    note: str | None = None

    @property
    def is_computed(self) -> bool:
        """True for arithmetic done in code (it has a formula); False for a reported value."""
        return self.formula is not None

    def as_dict(self) -> dict:
        return {"key": self.key, "period": self.period, "value": self.value, "unit": self.unit,
                "source_ids": list(self.source_ids), "inputs": [list(i) for i in self.inputs],
                "formula": self.formula, "note": self.note}


_SOURCE_ID_RE = re.compile(r"^S(\d+)$")
_PERIOD_FY_RE = re.compile(r"^FY(\d{4})$")
_PERIOD_Q_RE = re.compile(r"^Q([1-4])-(\d{4})$")
_PERIOD_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HTML_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _period_sort_key(period: str) -> tuple:
    """Chronological order for one key's periods: FY2024 sorts just after Q4-2024 (same end),
    quarters by fiscal year then number, ISO dates by date."""
    m = _PERIOD_FY_RE.match(period)
    if m:
        return (2, int(m.group(1)), 5, "")
    m = _PERIOD_Q_RE.match(period)
    if m:
        return (2, int(m.group(2)), int(m.group(1)), "")
    if _PERIOD_DATE_RE.match(period):
        return (1, 0, 0, period)
    return (0, 0, 0, period)


def _locked(method):
    """Run a Ledger method under the ledger's lock (the report's branches read it at the same time)."""
    @functools.wraps(method)
    def inner(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return inner


class Ledger:
    """Sources and facts for one report. One job builds one ledger; its branches (valuation,
    drafting, the self-check, risk themes) read it at the same time, so every method that reads or
    changes the stored sources and facts runs under one re-entrant lock. Ids are given in arrival
    order: add sources and facts from one thread when their numbering has to be the same every run."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sources: dict[str, Source] = {}
        self._source_index: dict[tuple[str, str], str] = {}
        self._facts: dict[tuple[str, str], Fact] = {}
        self._period_ends: dict[str, str] = {}
        self._next_source = 1

    # ---- sources -------------------------------------------------------------------------
    @_locked
    def add_source(self, source: Source) -> str:
        """Register a source and return its ledger id ("S1", "S2", ...). The incoming `id` is
        ignored: the ledger numbers sources in the order they arrive, and the same url + title
        returns the id it already has. Only http(s) links are accepted (the url becomes an href)."""
        if source.type not in contract.SOURCE_TYPES:
            raise LedgerError(f"source type must be one of {contract.SOURCE_TYPES}, got {source.type!r}")
        _check_url(source.url)
        index_key = (source.url, source.title)
        existing = self._source_index.get(index_key)
        if existing:
            return existing
        while f"S{self._next_source}" in self._sources:
            self._next_source += 1
        sid = f"S{self._next_source}"
        self._next_source += 1
        self._sources[sid] = replace(source, id=sid)
        self._source_index[index_key] = sid
        return sid

    @_locked
    def source(self, source_id: str) -> Source:
        try:
            return self._sources[source_id]
        except KeyError:
            raise LedgerError(f"unknown source id {source_id!r}") from None

    @_locked
    def sources(self) -> list[Source]:
        """Every registered source, in id order."""
        return list(self._sources.values())

    # ---- facts ---------------------------------------------------------------------------
    @_locked
    def add_fact(self, fact: Fact) -> Fact:
        """Add a new fact and return it as stored (tuples normalised, ints made floats).

        Raises LedgerError for: a reported fact without a known source or without a value, a
        reported fact with inputs, a computed fact without inputs or with an input the ledger does
        not hold, an unknown source id, a non-finite value, or a key+period already present
        (use `replace_fact` to change one)."""
        fact = self._validate(fact)
        if (fact.key, fact.period) in self._facts:
            raise LedgerError(f"{fact.key} {fact.period} is already in the ledger; use replace_fact")
        self._facts[(fact.key, fact.period)] = fact
        return fact

    @_locked
    def replace_fact(self, fact: Fact) -> Fact:
        """Add a fact or replace the one with the same key+period (same checks as `add_fact`,
        plus: a computed fact may not depend on itself through its inputs). Facts computed from
        the replaced one are not recomputed: call the producer again if that matters."""
        fact = self._validate(fact)
        if fact.is_computed and self._depends_on(fact.inputs, (fact.key, fact.period)):
            raise LedgerError(f"{fact.key} {fact.period} would depend on itself")
        self._facts[(fact.key, fact.period)] = fact
        return fact

    @_locked
    def get(self, key: str, period: str) -> Fact | None:
        return self._facts.get((key, period))

    @_locked
    def periods(self, key: str) -> list[str]:
        """The periods held for one key, newest first."""
        found = [p for (k, p) in self._facts if k == key]
        return sorted(found, key=_period_sort_key, reverse=True)

    @_locked
    def keys(self) -> list[str]:
        """Every key held, in the order first added."""
        return list(dict.fromkeys(k for (k, _p) in self._facts))

    @_locked
    def facts(self) -> list[Fact]:
        """Every fact, in the order added."""
        return list(self._facts.values())

    # ---- period end dates ----------------------------------------------------------------
    @_locked
    def set_period_end(self, period: str, end: str) -> None:
        """Record the end date of a duration period (`FY2024` -> `2024-09-28`), so balance-sheet
        items (named by their ISO date) can be matched to a fiscal year end exactly. The first
        date recorded for a period is kept."""
        if not _PERIOD_DATE_RE.match(end or ""):
            raise LedgerError(f"period end must be an ISO date, got {end!r}")
        self._period_ends.setdefault(period, end)

    @_locked
    def period_end(self, period: str) -> str | None:
        return self._period_ends.get(period)

    # ---- citations -----------------------------------------------------------------------
    @_locked
    def cite(self, fact: Fact) -> list[Source]:
        """The sources behind a fact. A reported fact: its own sources. A computed fact: its own
        (if any), then the sources of every input, followed recursively; each source once, in
        first-seen order."""
        out: dict[str, Source] = {}
        self._collect(fact, out, set())
        return list(out.values())

    def calc_id(self, fact: Fact) -> str:
        """The HTML id of a fact's Calculations entry, e.g. "calc-gross_margin-FY2024"."""
        return _HTML_ID_UNSAFE.sub("-", f"calc-{fact.key}-{fact.period}")

    # ---- serialisation -------------------------------------------------------------------
    @_locked
    def to_json(self) -> dict:
        return {
            "version": 1,
            "sources": [s.as_dict() for s in self._sources.values()],
            "facts": [f.as_dict() for f in self._facts.values()],
            "period_ends": dict(self._period_ends),
        }

    @classmethod
    def from_json(cls, data: dict) -> "Ledger":
        """Rebuild a ledger from `to_json()`; source ids are kept and every fact is re-checked."""
        ledger = cls()
        for raw in data.get("sources") or []:
            src = Source(**{name: str(raw.get(name) or "") for name in contract.SOURCE_FIELDS})
            if not _SOURCE_ID_RE.match(src.id) or src.id in ledger._sources:
                raise LedgerError(f"bad or repeated source id {src.id!r}")
            if src.type not in contract.SOURCE_TYPES:
                raise LedgerError(f"source type must be one of {contract.SOURCE_TYPES}, got {src.type!r}")
            _check_url(src.url)
            ledger._sources[src.id] = src
            ledger._source_index.setdefault((src.url, src.title), src.id)
            ledger._next_source = max(ledger._next_source, int(src.id[1:]) + 1)
        pending = [_fact_from_dict(raw) for raw in data.get("facts") or []]
        # inputs first: add whatever is ready until nothing is left (or nothing moves)
        while pending:
            ready = [f for f in pending if not f.is_computed
                     or all(tuple(i) in ledger._facts for i in f.inputs)]
            if not ready:
                missing = sorted({tuple(i) for f in pending for i in f.inputs} - set(ledger._facts))
                raise LedgerError(f"computed facts refer to inputs that are not in the data: {missing}")
            for f in ready:
                ledger.add_fact(f)
            pending = [f for f in pending if f not in ready]
        for period, end in (data.get("period_ends") or {}).items():
            ledger.set_period_end(period, end)
        return ledger

    # ---- internals -----------------------------------------------------------------------
    def _validate(self, fact: Fact) -> Fact:
        if not isinstance(fact, Fact):
            raise LedgerError("not a Fact")
        if not fact.key or not fact.period or not fact.unit:
            raise LedgerError(f"a fact needs a key, a period and a unit: {fact!r}")
        value = fact.value
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LedgerError(f"{fact.key} {fact.period}: value must be a number or None")
            value = float(value)
            if not math.isfinite(value):
                raise LedgerError(f"{fact.key} {fact.period}: value is not finite")
        source_ids = tuple(str(s) for s in fact.source_ids)
        inputs = tuple((str(k), str(p)) for k, p in fact.inputs)
        for sid in source_ids:
            if sid not in self._sources:
                raise LedgerError(f"{fact.key} {fact.period}: unknown source id {sid!r}")
        if fact.is_computed:
            if not inputs:
                raise LedgerError(f"computed fact {fact.key} {fact.period} has no inputs")
            for inp in inputs:
                if inp not in self._facts:
                    raise LedgerError(f"computed fact {fact.key} {fact.period}: input {inp} is not in the ledger")
        else:
            if not source_ids:
                raise LedgerError(f"reported fact {fact.key} {fact.period} has no source")
            if inputs:
                raise LedgerError(f"reported fact {fact.key} {fact.period} has inputs but no formula")
            if value is None:
                raise LedgerError(f"reported fact {fact.key} {fact.period} has no value; leave it out instead")
        return replace(fact, value=value, source_ids=source_ids, inputs=inputs)

    def _depends_on(self, inputs: Iterable[tuple[str, str]], target: tuple[str, str]) -> bool:
        seen: set[tuple[str, str]] = set()
        stack = list(inputs)
        while stack:
            ref = stack.pop()
            if ref == target:
                return True
            if ref in seen:
                continue
            seen.add(ref)
            dep = self._facts.get(ref)
            if dep is not None:
                stack.extend(dep.inputs)
        return False

    def _collect(self, fact: Fact, out: dict[str, Source], seen: set[tuple[str, str]]) -> None:
        ref = (fact.key, fact.period)
        if ref in seen:
            return
        seen.add(ref)
        for sid in fact.source_ids:
            if sid not in out:
                out[sid] = self.source(sid)
        for inp in fact.inputs:
            dep = self._facts.get(tuple(inp))
            if dep is None:
                raise LedgerError(f"{fact.key} {fact.period}: input {tuple(inp)} is not in the ledger")
            self._collect(dep, out, seen)


def _check_url(url: str) -> None:
    """Only absolute http(s) links: the url is written into an href, so `javascript:` and
    relative paths are refused here rather than escaped later."""
    parts = urlsplit(url or "")
    if parts.scheme.lower() not in ("https", "http") or not parts.netloc:
        raise LedgerError(f"a source needs an absolute http(s) url, got {url!r}")


def _fact_from_dict(raw: dict[str, Any]) -> Fact:
    return Fact(
        key=raw["key"], period=raw["period"], value=raw.get("value"), unit=raw["unit"],
        source_ids=tuple(raw.get("source_ids") or ()),
        inputs=tuple(tuple(i) for i in raw.get("inputs") or ()),
        formula=raw.get("formula"), note=raw.get("note"),
    )
