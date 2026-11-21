"""SEC EDGAR, the source of record: the ticker list, a company's filings index, its XBRL
company facts and the text of a filing.

The SEC asks every automated client to identify itself with a name and a contact address in the
User-Agent (its fair-access policy). That value comes from `SEC_USER_AGENT` in .env, is checked
before any request, and is never stored, logged or put into an error message.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from backend import settings
from backend.sources import tickers
from backend.sources.http import Client, SourceUnavailable, default_client

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{doc}"
VIEWER_URL = "https://www.sec.gov/ix?doc=/Archives/edgar/data/{cik}/{folder}/{doc}"
DEFAULT_FORMS = ("10-K", "10-Q", "20-F", "8-K")

HOUR = 3600
DAY = 24 * HOUR

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_OVERFLOW_NAME = re.compile(r"^[A-Za-z0-9._-]+\.json$")


# --- identity ------------------------------------------------------------------------------

def _agent(url: str = TICKERS_URL) -> str:
    """The User-Agent value. Raises SourceUnavailable before any request when it is empty or
    lacks a name plus an email-shaped address. The value itself never appears in the error."""
    value = settings.secret("SEC_USER_AGENT")
    if not value:
        raise SourceUnavailable(url, "SEC_USER_AGENT is not set: put a name and a contact "
                                     "address in .env (the SEC requires both)")
    words = value.split()
    emails = [w for w in words if _EMAIL.fullmatch(w.strip("<>()[],;"))]
    names = [w for w in words if w not in emails and re.search(r"[A-Za-z]", w)]
    if not emails or not names:
        raise SourceUnavailable(url, "SEC_USER_AGENT is not set correctly: it needs a name and "
                                     "an email-shaped contact address")
    return value


def _headers(url: str, client: Client) -> dict[str, str]:
    """The request headers. In replay mode nothing is sent, so the identity is not needed and a
    demo from recordings runs on a machine without SEC_USER_AGENT."""
    if client.mode == "replay":
        return {}
    # no Host header: urllib derives it from the URL (www.sec.gov and data.sec.gov differ)
    return {"User-Agent": _agent(url), "Accept-Encoding": "gzip, deflate"}


def _get_json(url: str, client: Client | None, ttl: float):
    client = client or default_client()
    return client.get_json(url, headers=_headers(url, client), ttl=ttl)


# --- CIK helpers ---------------------------------------------------------------------------

def _cik_digits(cik: str | int) -> str:
    """`"0000320193"`, `320193` or `"CIK0000320193"` -> `"320193"`."""
    text = str(cik).strip().upper().removeprefix("CIK")
    if not text.isdigit():
        raise ValueError(f"not a CIK: {cik!r}")
    return str(int(text))


def _cik_padded(cik: str | int) -> str:
    return f"{int(_cik_digits(cik)):010d}"


# --- the ticker list -----------------------------------------------------------------------

def _row_order(key) -> tuple:
    text = str(key)
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def ticker_table(client: Client | None = None) -> dict[str, dict]:
    """Every symbol the SEC knows, keyed by the normalised symbol (`BRK.B`; the SEC writes
    `BRK-B`). Each row: `{"cik": "1067983", "ticker": "BRK.B", "title": "..."}`. Cached a day.
    Rows whose symbol is outside contract.TICKER_RE (warrants, preferreds) are left out; when a
    symbol appears twice the first row (the SEC's own order) wins."""
    data = _get_json(TICKERS_URL, client, ttl=DAY)
    if isinstance(data, dict):                     # {"0": row, "1": row, ...}: keep the SEC's order
        rows = [data[k] for k in sorted(data, key=_row_order)]
    else:
        rows = data if isinstance(data, list) else []
    table: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            symbol = tickers.normalise(str(row.get("ticker", "")))
            cik = _cik_digits(row.get("cik_str", ""))
        except ValueError:
            continue
        table.setdefault(symbol, {"cik": cik, "ticker": symbol, "title": str(row.get("title") or "")})
    return table


def cik_for(symbol: str, client: Client | None = None) -> str | None:
    """The company's CIK as digits without padding (`"320193"`), or None when the SEC's list
    does not hold the symbol. Raises ValueError for a string that is not a ticker symbol."""
    row = ticker_table(client).get(tickers.normalise(symbol))
    return row["cik"] if row else None


def company_name(symbol: str, client: Client | None = None) -> str | None:
    """The registrant name from the SEC's list (`"Apple Inc."`), or None."""
    row = ticker_table(client).get(tickers.normalise(symbol))
    return (row["title"] or None) if row else None


# --- filings -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Filing:
    """One filing from the submissions index. `cik` is unpadded digits."""
    accession: str          # 0000320193-24-000123
    form: str               # 10-K, 10-Q, 20-F, 8-K ...
    filed: str              # ISO filing date
    period: str             # ISO report date ("" when the SEC gives none)
    primary_doc: str        # aapl-20240928.htm
    cik: str
    items: str = ""         # an 8-K's item codes as the index gives them ("2.02,9.01"); "" when none

    @property
    def _folder(self) -> str:
        return self.accession.replace("-", "")

    @property
    def url(self) -> str:
        """The primary document in the SEC archive (unpadded CIK, accession without dashes)."""
        return ARCHIVE_URL.format(cik=_cik_digits(self.cik), folder=self._folder, doc=self.primary_doc)

    @property
    def viewer_url(self) -> str:
        """The same document in the SEC's inline XBRL viewer: the link a reader should open."""
        return VIEWER_URL.format(cik=_cik_digits(self.cik), folder=self._folder, doc=self.primary_doc)


def _rows(block: dict, cik: str) -> list[Filing]:
    """Filings from the SEC's parallel arrays (accessionNumber, form, filingDate, ...)."""
    columns = {name: block.get(name) or [] for name in
               ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")}

    def cell(name: str, i: int) -> str:
        values = columns[name]
        return str(values[i] or "").strip() if i < len(values) and values[i] is not None else ""

    found = []
    for i in range(len(columns["accessionNumber"])):
        accession, doc = cell("accessionNumber", i), cell("primaryDocument", i)
        if not accession or not doc:          # without a document there is no link to open
            continue
        found.append(Filing(accession=accession, form=cell("form", i), filed=cell("filingDate", i),
                            period=cell("reportDate", i), primary_doc=doc, cik=cik,
                            items=cell("items", i)))
    return found


def filings(cik: str | int, forms: tuple[str, ...] | None = DEFAULT_FORMS,
            client: Client | None = None) -> list[Filing]:
    """The company's filings of the given forms (exact form names; None = every form), newest
    first. Reads `filings.recent` and every overflow file listed in `filings.files`."""
    digits = _cik_digits(cik)
    data = _get_json(SUBMISSIONS_URL.format(cik=_cik_padded(digits)), client, ttl=HOUR)
    history = (data.get("filings") or {}) if isinstance(data, dict) else {}
    found = _rows(history.get("recent") or {}, digits)
    for extra in history.get("files") or []:
        name = str((extra or {}).get("name") or "")
        if not _OVERFLOW_NAME.fullmatch(name):
            continue
        older = _get_json(SUBMISSIONS_FILE_URL.format(name=name), client, ttl=DAY)
        if isinstance(older, dict):
            found.extend(_rows(older, digits))
    for older_cik in predecessors(digits):
        # the history before a reorganisation is filed under the old registrant (its own links)
        found.extend(filings(older_cik, None, client))
    wanted = set(forms) if forms else None
    unique = {f.accession: f for f in reversed(found) if wanted is None or f.form in wanted}
    return sorted(unique.values(), key=lambda f: (f.filed, f.accession), reverse=True)


def company_facts(cik: str | int, client: Client | None = None) -> dict:
    """The XBRL company facts (every reported figure with its dates, form and accession).
    Cached six hours: it only changes when the company files."""
    data = _get_json(COMPANY_FACTS_URL.format(cik=_cik_padded(cik)), client, ttl=6 * HOUR)
    data = data if isinstance(data, dict) else {}
    for older_cik in predecessors(cik):
        try:
            older = _get_json(COMPANY_FACTS_URL.format(cik=_cik_padded(older_cik)), client, ttl=6 * HOUR)
        except SourceUnavailable:
            continue                      # the new registrant's own figures still stand
        data = _merge_facts(data, older if isinstance(older, dict) else {})
    return data


# A registrant that replaced an older one (a holding-company reorganisation) starts with an empty
# history: the annual reports and their figures stay filed under the old registrant. Known cases,
# new SEC number -> the old one(s). Without this the ticker resolves to a company with no
# annual report at all.
PREDECESSORS: dict[str, tuple[str, ...]] = {
    "2115436": ("34088",),          # ExxonMobil Holdings Corp <- Exxon Mobil Corp
}


def predecessors(cik: str | int) -> tuple[str, ...]:
    try:
        return PREDECESSORS.get(_cik_digits(cik), ())
    except Exception:
        return ()


def _merge_facts(newer: dict, older: dict) -> dict:
    """One company-facts document from a registrant and its predecessor: every tag's entries of
    both, the newer registrant's first (an entry carries its own accession, so each figure still
    cites the filing it came from)."""
    if not older.get("facts"):
        return newer
    merged = dict(newer)
    facts: dict = {}
    for doc in (newer, older):
        for taxonomy, tags in (doc.get("facts") or {}).items():
            if not isinstance(tags, dict):
                continue
            into = facts.setdefault(taxonomy, {})
            for tag, body in tags.items():
                if not isinstance(body, dict):
                    continue
                slot = into.setdefault(tag, {k: v for k, v in body.items() if k != "units"})
                units = slot.setdefault("units", {})
                for unit, entries in (body.get("units") or {}).items():
                    if isinstance(entries, list):
                        units.setdefault(unit, []).extend(entries)
    merged["facts"] = facts
    return merged


# --- filing text ---------------------------------------------------------------------------

class _TextParser(HTMLParser):
    """HTML to plain text. Block elements become paragraph breaks; scripts, styles, the head and
    hidden blocks (the inline-XBRL header is `display:none`) are dropped."""

    BLOCK = frozenset({"address", "article", "aside", "blockquote", "caption", "center", "dd",
                       "div", "dl", "dt", "figcaption", "figure", "footer", "form", "h1", "h2",
                       "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
                       "pre", "section", "table", "ul"})
    CELL = frozenset({"td", "th"})
    SKIP = frozenset({"script", "style", "head", "noscript", "template", "ix:header"})
    VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                      "param", "source", "track", "wbr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_tag: str | None = None
        self._skip_depth = 0

    @staticmethod
    def _hidden(attrs) -> bool:
        style = next((v for k, v in attrs if k == "style" and v), "")
        return "display:none" in re.sub(r"\s+", "", style.lower())

    def _break(self, tag: str, end: bool) -> None:
        """Blocks open and close a paragraph; a `br` (start) and a table row (end) break a
        line; table cells are separated by a space."""
        if tag in self.BLOCK:
            self.parts.append("\n\n")
        elif (tag == "br" and not end) or (tag == "tr" and end):
            self.parts.append("\n")
        elif tag in self.CELL:
            self.parts.append(" ")

    def handle_starttag(self, tag, attrs):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag not in self.VOID and (tag in self.SKIP or self._hidden(attrs)):
            self._skip_tag, self._skip_depth = tag, 1
            return
        self._break(tag, end=False)

    def handle_startendtag(self, tag, attrs):
        if not self._skip_tag:
            self._break(tag, end=False)

    def handle_endtag(self, tag):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        self._break(tag, end=True)

    def handle_data(self, data):
        if not self._skip_tag:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        raw = "".join(self.parts).replace("\xa0", " ")
        lines = [re.sub(r"[ \t\f\v\r]+", " ", line).strip() for line in raw.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    """Plain text with paragraph breaks (blank lines) kept."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return parser.text()


def filing_text(filing: Filing, client: Client | None = None) -> str:
    """The primary document as plain text. Filed documents never change: cached 30 days."""
    client = client or default_client()
    url = filing.url
    html = client.get_text(url, headers=_headers(url, client), ttl=30 * DAY)
    return html_to_text(html)


# --- a filing's documents (additions for backend.research.releases) --------------------------

INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.htm"
ARCHIVE_PREFIX = "https://www.sec.gov/Archives/edgar/data/"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_DOC_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_INDEX_COLUMNS = ("seq", "description", "document", "type", "size")   # the SEC's column order


class _IndexParser(HTMLParser):
    """The rows of the document tables (`<table class="tableFile">`) on a filing's -index.htm
    page: each row's cell texts (named by the table's own header row) and the first link in it.
    The JSON directory listing (index.json) names the files but not their document type, so the
    -index.htm table is the source that says which file is EX-99.1."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._depth = 0                     # nesting inside a tableFile table
        self._columns: tuple[str, ...] = _INDEX_COLUMNS
        self._row: dict | None = None
        self._cell: list[str] | None = None
        self._header = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "table":
            classes = str(values.get("class") or "").lower().split()
            if self._depth or "tablefile" in classes:
                self._depth += 1
            return
        if not self._depth:
            return
        if tag == "tr":
            self._row, self._header = {"cells": [], "href": None}, True
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._header = self._header and tag == "th"
        elif tag == "a" and self._row is not None and self._row["href"] is None and values.get("href"):
            self._row["href"] = str(values["href"])

    def handle_endtag(self, tag):
        if tag == "table" and self._depth:
            self._depth -= 1
            return
        if not self._depth:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            cells = self._row["cells"]
            if self._header and cells:
                self._columns = tuple(c.strip().lower() for c in cells)
            else:
                self.rows.append({"href": self._row["href"],
                                  "cells": dict(zip(self._columns, cells))})
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _filing_parts(filing) -> tuple[str, str]:
    """(unpadded CIK, accession) of a Filing or a dict with `cik` and `accession`."""
    get = filing.get if isinstance(filing, dict) else (lambda name: getattr(filing, name, None))
    accession = str(get("accession") or "").strip()
    if not _ACCESSION.fullmatch(accession):
        raise ValueError(f"not an accession number: {accession!r}")
    return _cik_digits(get("cik") or ""), accession


def _document_name(href: str | None, cik: str, folder: str) -> str | None:
    """The file name of an index link, only when the link points into this filing's own folder
    (`/Archives/edgar/data/{cik}/{folder}/{name}`, or the same behind `/ix?doc=`)."""
    path = str(href or "").strip()
    path = path.removeprefix("https://www.sec.gov").removeprefix("/ix?doc=")
    prefix = f"/Archives/edgar/data/{cik}/{folder}/"
    if not path.startswith(prefix):
        return None
    name = path[len(prefix):]
    return name if _DOC_NAME.fullmatch(name) else None


def filing_documents(filing, client: Client | None = None) -> list[dict]:
    """The documents of one filing from its EDGAR index page (`{accession}-index.htm`), in the
    index's order: `[{"name": "a8-kex991.htm", "type": "EX-99.1", "description": "PRESS
    RELEASE", "url": "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"}]`. The url
    is built from the filing's own folder and a checked file name, never copied from the page.
    Raises SourceUnavailable when the index cannot be fetched (as every function here does);
    ValueError for a filing without a CIK or accession number. Cached 30 days: filed documents
    never change."""
    cik, accession = _filing_parts(filing)
    folder = accession.replace("-", "")
    client = client or default_client()
    url = INDEX_URL.format(cik=cik, folder=folder, accession=accession)
    page = client.get_text(url, headers=_headers(url, client), ttl=30 * DAY)
    parser = _IndexParser()
    try:
        parser.feed(page or "")
        parser.close()
    except Exception:                                  # a damaged page: what was read is kept
        pass
    found: list[dict] = []
    seen: set[str] = set()
    for row in parser.rows:
        name = _document_name(row["href"], cik, folder)
        if name is None or name in seen:
            continue
        seen.add(name)
        cells = row["cells"]
        found.append({"name": name, "type": cells.get("type", "").strip().upper(),
                      "description": cells.get("description", "").strip(),
                      "url": ARCHIVE_URL.format(cik=cik, folder=folder, doc=name)})
    return found


def document_text(url: str, client: Client | None = None) -> str:
    """One filed document (a `filing_documents` url: an https link into the SEC archive) as plain
    text: `html_to_text` for HTML, the text itself for a .txt document. Raises ValueError for a
    link outside the archive and SourceUnavailable when it cannot be fetched. Cached 30 days."""
    if not isinstance(url, str) or not url.startswith(ARCHIVE_PREFIX) or any(ch.isspace() for ch in url):
        raise ValueError(f"not a document in the SEC archive: {url!r}")
    client = client or default_client()
    body = client.get_text(url, headers=_headers(url, client), ttl=30 * DAY)
    if url.lower().endswith(".txt"):
        lines = [line.strip() for line in (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return html_to_text(body or "")
