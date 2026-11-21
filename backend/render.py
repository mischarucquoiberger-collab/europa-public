"""The report page: a port of the original product's research dashboard (one A4 sheet: header,
narrative beside a metrics sidebar, mini charts, income statement, a two-column bottom grid,
scenario arithmetic, risk themes, then Sources, Calculations and the footer), filled from the
evidence ledger for a US company.

The template reads one variable, `dashboard`, and every key it reads is always present (None or
an empty list when there is nothing to show). Every ledger figure reaches the template already
as `fmt.cited(...)` HTML or the not-available text: the template formats no ledger number.
Market data is not in the ledger: prices are computed here from the end-of-day bars, and the
price, market cap, 52-week range and the company's own multiples (backend.analysis.multiples) are
shown with the market-data mark and the date. Jinja2 autoescape is on; only `fmt.cited` output,
`audit.apply` HTML and the callers' already-linked HTML (thesis points, peer cells, `*_html`
fields) are marked safe, once.
"""
from __future__ import annotations

import html as _html
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from backend import format as fmt
from backend.draft.writer import annual_fact, fiscal_years
from backend.facts import metrics
from backend.ledger import Fact

YEARS = 5
NARRATIVE = (("overview", "Company Profile"), ("results", "Business Performance"),
             ("financial_position", "Financial Position"), ("cash_flow", "Cash Flow"))
NOT_FOR_REPORT = "Not available for this report"
NOT_CONFIRMED = "Not included: {what} could not be confirmed against the sources"
NO_PRICES = "Prices are not available in this report."
MARKET_MARK = "Market data: Massive, end of day"
SCENARIO_SUBLINE = "Arithmetic under stated assumptions, not an opinion of value."
NO_SCENARIOS = "Not part of this report."
NO_RISK_THEMES = "Risk themes are not available for this report."
NO_PEERS = "No named peer table for this company."
WITHHELD_NOTE = "These drafted sentences were removed because they did not meet the report's rules."
FOOTER = ("Figures come from SEC filings and are linked to their source. Calculated figures show "
          "their formula and inputs. This report informs; it does not advise.")
DISCLAIMER = "For information only. Not investment advice."
FIRM = "Europa"

CHARTS = (("revenue", "Revenue ({cur}) 5yr", "(FY, as filed)", ""),
          ("operating_income", "Operating income ({cur}) 5yr", "(FY, as filed)", ""),
          ("net_income", "Net income ({cur}) 5yr", "(FY, as filed)", ""),
          ("free_cash_flow", "Free cash flow ({cur}) 5yr", "(FY · operating cash flow − capex)", "alt"))
STATEMENT_COLUMNS = (("revenue", "Revenue"), ("gross_profit", "Gross profit"),
                     ("operating_income", "Operating income"), ("net_income", "Net income"),
                     ("eps_diluted", "EPS (diluted)"), ("dividends_per_share", "DPS"))
SIDEBAR = (("Margins", (("Gross margin", "gross_margin"), ("Operating margin", "operating_margin"),
                        ("Net margin", "net_margin"), ("FCF margin", "fcf_margin"))),
           ("Returns", (("ROE", "return_on_equity"), ("ROA", "return_on_assets"))),
           ("Growth", (("Revenue growth", "revenue_growth"), ("Net income growth", "net_income_growth"))),
           ("Per Share", (("EPS (diluted)", "eps_diluted"), ("EPS (basic)", "eps_basic"),
                          ("DPS", "dividends_per_share"))),
           ("Structure", (("LT debt / equity", "debt_to_equity"), ("Equity", "shareholders_equity"),
                          ("Cash", "cash"))))
ALLOCATION_ROWS = (("Operating cash flow", "operating_cash_flow"), ("Capital expenditure", "capex"),
                   ("Free cash flow", "free_cash_flow"), ("FCF margin", "fcf_margin"),
                   ("Dividends per share", "dividends_per_share"))
TREND_ROWS = (("Total assets", "total_assets", ""), ("Shareholders' equity", "shareholders_equity", ""),
              ("Cash", "cash", "cash-highlight"), ("Long-term debt", "long_term_debt", ""),
              ("LT debt / equity", "debt_to_equity", ""))
EXCHANGES = {"XNAS": "Nasdaq", "XNYS": "NYSE", "ARCX": "NYSE Arca", "XASE": "NYSE American",
             "BATS": "Cboe BZX", "XCHI": "NYSE Chicago"}
NO_RULE_FIRED = "No rule fired on this side for the filed figures."
BULLBEAR_NOTE = ("Bull and bear points are chosen by fixed rules on the filed figures and are not a "
                 "recommendation.")
ANALYSIS_TITLE = "Model analysis: an interpretation, not a fact established by source checks"
VALUATION_SUBLINE = ("Scenario arithmetic under stated assumptions · enterprise value · "
                     "not an opinion of value")
DESCRIPTION_MARK = "(Company description: Massive)"
REFERENCE_MARK = "Massive"
VALUATION_CLOSING = "Model arithmetic under stated assumptions. It informs; it is not a recommendation."
NEWS_CLOSING = ("News is third-party web coverage found through {provider}; it is not checked against "
                "the filings.")
RELEASE_CLOSING = ("Quotes are the company's own words from the release; they are not checked against "
                   "later filings.")
NOT_FOR_FINANCIALS = {"gross_profit", "gross_margin", "operating_income", "operating_margin",
                      "free_cash_flow", "fcf_margin"}
FINANCIAL_CHARTS = (("revenue", "Revenue ({cur}) 5yr", "(FY, as filed)", ""),
                    ("net_income", "Net income ({cur}) 5yr", "(FY, as filed)", ""),
                    ("eps_diluted", "Diluted EPS ({cur}) 5yr", "(FY, as filed)", "alt"),
                    ("shareholders_equity", "Shareholders' equity ({cur}) 5yr", "(at FY end)", ""))
NM_NOTE = "n/m = not meaningful (the base is very small)."
NOTHING_PRICED = "No method could be priced"
NOT_FOR_BANKS = "n/a — not used for a bank or insurer"
FUNDING_NOTE = ("For a bank or insurer, debt is part of how the business is funded, not only leverage; "
                "long-term debt as tagged in the filing's XBRL data.")
PUFFERY = re.compile(r"\b(titan|formidable|world-class|unparalleled|leading|premier|best-in-class|dominant|"
                     r"powerhouse|giant)\b", re.IGNORECASE)
CALC_WINDOW_NOTE = "Calculations for the fiscal years shown on this page; older years are in the report data."
SOURCES_NOTE = "{n} older filings in the report data are not cited on this page."
MULTIPLE_LABELS = {"price_to_book": "P/B", "price_to_earnings": "P/E (FY diluted)", "market_cap_to_revenue": "Mkt cap / revenue",
                   "market_cap_to_fcf": "Mkt cap / FCF", "ev_to_operating_income": "EV / operating income"}

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                   autoescape=select_autoescape(["html"], default=True))

_TOKEN = re.compile(r"[a-z][a-z0-9_]*[a-z0-9]")
_SCALE_WORD = re.compile(r" (trillion|billion|million)\b")
_PARAGRAPHS = re.compile(r"\s*(?:<p>.*?</p>\s*)+", re.S)
_FORM = re.compile(r"Form\s+([0-9A-Za-z/-]+)")


# ---- figures --------------------------------------------------------------------------------
def _na(short: bool = False) -> Markup:
    if short:
        return Markup('<span class="na" title="%s">n/a</span>') % fmt.NOT_AVAILABLE
    return Markup('<span class="na">%s</span>') % fmt.NOT_AVAILABLE


def _cite(ledger, f: Fact | None, *, short: bool = False) -> Markup:
    """A ledger figure as its cited link; no figure gives the not-available text (a computed
    figure without a value links to its Calculations entry, where its note says why)."""
    if f is None:
        return _na(short)
    if f.value is None:
        if f.is_computed:
            return Markup('<a class="calc na" href="#%s" title="%s">%s</a>') % (
                ledger.calc_id(f), f.note or fmt.NOT_AVAILABLE, "n/a" if short else fmt.NOT_AVAILABLE)
        return _na(short)
    return Markup(fmt.cited(f, ledger))


def _cite_tight(ledger, f: Fact | None) -> Markup:
    """The cited link with a compact text ("$391.0B") for chart labels and narrow cells: the
    anchor is `fmt.cited`'s own, only the words of the scale are shortened."""
    if f is None or f.value is None:
        return _cite(ledger, f, short=True)
    full = fmt.cited(f, ledger)
    text = fmt.fact(f)
    tail = f">{_html.escape(text)}</a>"
    compact = _SCALE_WORD.sub(lambda m: m.group(1)[0].upper(), text)
    compact = re.sub(r"^(-?)[A-Z]{3} ", r"\1", compact)     # "EUR 18.6B" -> "18.6B": the title says EUR
    if full.endswith(tail):
        return Markup(full[:-len(tail)] + f">{_html.escape(compact)}</a>")
    return Markup(full)


def _value(f: Fact | None) -> float | None:
    return None if f is None or f.value is None else float(f.value)


def _formula_words(formula: str | None) -> str:
    """`net_income / shareholders_equity at year end` -> `Net income ÷ shareholders' equity at
    year end`."""
    if not formula:
        return ""

    def word(m: re.Match) -> str:
        key = m.group(0)
        if key in metrics.METRICS or key in metrics.COMPUTED_LABELS:
            label = metrics.label(key)
            return label[:1].lower() + label[1:]
        return key.replace("_", " ")

    text = _TOKEN.sub(word, formula).replace(" / ", " ÷ ").replace(" - ", " − ").replace(" x ", " × ")
    return text[:1].upper() + text[1:]


def _safe(value) -> Markup | None:
    """Caller HTML that is already escaped and linked (thesis points, peer cells): marked safe
    once, never escaped again. Anything that is not a string is dropped."""
    return Markup(value) if isinstance(value, str) and value.strip() else None


def _money_text(value) -> str | None:
    """A market-data amount in dollars (market cap, enterprise value), through fmt; None if not a number."""
    v = _num(value)
    return None if v is None else fmt.fact(Fact(key="market_data", period="-", value=v, unit="USD"))


def _count_text(value) -> str | None:
    v = _num(value)
    if v is None or v < 0:
        return None
    text = fmt.fact(Fact(key="count", period="-", value=v, unit="shares"))
    return text[:-len(" shares")] if text.endswith(" shares") else text


def _date_words(iso: str | None) -> str | None:
    """`2024-09-28` -> `28 Sep 2024` (through fmt.period_label); None if not an ISO date."""
    if not iso:
        return None
    shown = fmt.period_label(str(iso)[:10])
    return shown[len("as of "):] if shown.startswith("as of ") else None


def _fy(year: int, short: bool = False) -> str:
    return f"FY{str(year)[2:]}" if short else f"FY{year}"


# ---- geometry (numbers for drawing, never printed) ------------------------------------------
def _plot(values: list[float | None]) -> tuple[float | None, list[dict | None]]:
    """The original's bar_plot scale: heights to one scale, positives stand on the zero line and
    negatives hang below it, in a 0-100 box (y grows downwards, SVG style)."""
    pos = max([v for v in values if v is not None and v > 0] or [0.0])
    neg = max([-v for v in values if v is not None and v < 0] or [0.0])
    total = pos + neg
    base = neg / total * 100 if total else 0.0
    zero = round(100 - base, 2) if neg else None
    rects: list[dict | None] = []
    for v in values:
        if v is None or not total or v == 0:
            rects.append(None)
            continue
        h = abs(v) / total * 100
        y = (100 - base) if v < 0 else (100 - base - h)
        rects.append({"y": round(y, 2), "h": round(max(h, 0.8), 2), "neg": v < 0})
    return zero, rects


# ---- market data (not in the ledger) --------------------------------------------------------
def _field(bar, *names):
    for name in names:
        value = bar.get(name) if isinstance(bar, dict) else getattr(bar, name, None)
        if value is not None:
            return value
    return None


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _clean_bars(bars) -> list[dict]:
    rows = []
    for bar in bars or []:
        day, close = _iso(_field(bar, "date")), _num(_field(bar, "close", "c"))
        if day is None or close is None:
            continue
        rows.append({"day": day, "close": close, "high": _num(_field(bar, "high", "h")),
                     "low": _num(_field(bar, "low", "l")), "volume": _num(_field(bar, "volume", "v"))})
    rows.sort(key=lambda r: r["day"])
    return rows


def _price(value: float, day: date | str) -> str:
    return fmt.fact(Fact(key="close", period=str(day), value=float(value), unit="USD/share"))


def _chart(rows: list[dict]) -> Markup | None:
    """An inline SVG line of the daily closes, oldest first; no figures drawn on it."""
    closes = [r["close"] for r in rows]
    if len(closes) < 2:
        return None
    w, h, pad = 300.0, 64.0, 3.0
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    step = (w - 2 * pad) / (len(closes) - 1)
    pts = " ".join(f"{pad + i * step:.1f},{h - pad - (c - lo) / span * (h - 2 * pad):.1f}"
                   for i, c in enumerate(closes))
    return Markup(
        f'<svg class="price-chart" viewBox="0 0 {w:.0f} {h:.0f}" role="img" '
        f'aria-label="Daily closing price line" preserveAspectRatio="none">'
        f'<line x1="0" y1="{h - 0.5:.1f}" x2="{w:.0f}" y2="{h - 0.5:.1f}" stroke="#d6d9de" stroke-width="1"/>'
        f'<polyline fill="none" stroke="#1a1a2e" stroke-width="1.4" '
        f'vector-effect="non-scaling-stroke" points="{pts}"/></svg>')


def _stock_info(bars, previous_close: dict | None) -> dict:
    rows = _clean_bars(bars)
    latest_day, latest_close = (rows[-1]["day"], rows[-1]["close"]) if rows else (None, None)
    if isinstance(previous_close, dict):
        pc_close, pc_day = _num(previous_close.get("close")), _iso(previous_close.get("date"))
        if pc_close is not None and (latest_day is None or (pc_day is not None and pc_day >= latest_day)):
            latest_day, latest_close = pc_day, pc_close
    info = {"available": latest_close is not None, "no_prices": None if latest_close is not None else NO_PRICES,
            "latest_iso": latest_day.isoformat() if latest_day else None,
            "latest_close": None, "latest_date": None, "week_52_high": None, "week_52_low": None,
            "range_basis": None, "range_since": None, "range_pos": None, "avg_volume": None,
            "chart": _chart(rows), "chart_from": None, "chart_to": None, "mark": MARKET_MARK}
    if latest_close is not None:
        info["latest_close"] = _price(latest_close, latest_day or "")
        info["latest_date"] = _date_words(latest_day.isoformat()) if latest_day else None
    if rows:
        end = rows[-1]["day"]
        window = [r for r in rows if r["day"] > end - timedelta(days=365)]
        intraday = all(r["high"] is not None and r["low"] is not None for r in window)
        hi = max(r["high"] if intraday else r["close"] for r in window)
        lo = min(r["low"] if intraday else r["close"] for r in window)
        info.update(week_52_high=_price(hi, end), week_52_low=_price(lo, end),
                    range_basis="intraday" if intraday else "daily closes",
                    range_since=_date_words(window[0]["day"].isoformat()))
        if latest_close is not None and hi > lo:
            info["range_pos"] = round(min(100.0, max(0.0, (latest_close - lo) / (hi - lo) * 100)), 1)
        vols = [r["volume"] for r in rows if r["volume"] is not None and r["day"] > end - timedelta(days=90)]
        if vols:
            info["avg_volume"] = fmt.fact(Fact(key="avg_volume", period="90d",
                                               value=sum(vols) / len(vols), unit="shares"))
        if info["chart"] is not None:
            info["chart_from"] = _date_words(rows[0]["day"].isoformat())
            info["chart_to"] = _date_words(end.isoformat())
    return info


# ---- sections -------------------------------------------------------------------------------
def _paragraphs(text: str) -> list[Markup] | None:
    """`<p>a</p><p>b</p>` (audit.apply's form) -> [a, b], so the first one can carry the inline
    title the way the original prints it; None when the HTML is not plain paragraphs."""
    if not _PARAGRAPHS.fullmatch(text):
        return None
    return [Markup(p) for p in re.findall(r"<p>(.*?)</p>", text, re.S)]


def _description(text) -> Markup | None:
    """The provider's company description, first two sentences, escaped, with its source mark."""
    if not isinstance(text, str) or not text.strip():
        return None
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", " ".join(text.split()))
    # a third party's text: only sentences with no figure and no puffery, the first two of them
    kept = [x for x in sentences if x.strip() and not re.search(r"\d", x) and not PUFFERY.search(x)]
    if not kept:
        return None
    shown = " ".join(kept[:2])
    if len(shown) > 600:
        shown = shown[:600].rsplit(" ", 1)[0] + "…"
    return Markup("%s <span class=\"desc-mark\">%s</span>") % (shown, DESCRIPTION_MARK)


def _narrative(sections: dict[str, str], description=None) -> dict:
    blocks, held, absent = [], [], []
    opening = _description(description)
    for key, title in NARRATIVE:
        raw = (sections or {}).get(key)
        if key == "overview" and opening is not None:
            paras = _paragraphs(str(raw).strip()) if raw and str(raw).strip() else []
            if paras is None:                       # not plain paragraphs: keep it whole after the opening
                paras = [Markup(str(raw).strip())]
            blocks.append({"key": key, "title": title, "paragraphs": [opening] + paras, "html": None})
        elif raw and str(raw).strip():
            raw = str(raw).strip()
            paras = _paragraphs(raw)
            blocks.append({"key": key, "title": title, "paragraphs": paras,
                           "html": None if paras else Markup(raw)})
        elif key in (sections or {}):
            held.append(title.lower())      # written, then every sentence withheld by the checks
        else:
            absent.append(title.lower())    # never produced
    all_missing = not blocks
    gaps = []
    for names, text, cls in ((held, NOT_CONFIRMED.format(what="this part" if len(held) == 1 else "these parts"),
                              "narr-withheld"), (absent, NOT_FOR_REPORT, "narr-absent")):
        if names:
            gaps.append({"text": f"{text} ({', '.join(names)}).",
                         "cls": cls + ("" if all_missing else " narr-omitted")})
    return {"blocks": blocks, "gaps": gaps, "all_missing": all_missing}


def _header(company: dict, details: dict, ledger, latest: int | None) -> dict:
    name = str(company.get("name") or details.get("name") or company.get("ticker") or "").strip()
    alt = str(details.get("name") or "").strip()
    if alt and _squash(_SHARE_CLASS.sub(" ", alt)) == _squash(name):
        alt = ""                                   # "Celsius Holdings, Inc. Common Stock" repeats the name
    exchange = str(details.get("primary_exchange") or "").strip()
    annual = [s for s in ledger.sources() if re.search(r"Form\s+(10-K|20-F|40-F)", s.title or "")]
    newest = max(annual, key=lambda s: s.date or "") if annual else None
    form = _FORM.search(newest.title).group(1) if newest else None
    fye = None
    if latest is not None:
        end = _iso(ledger.period_end(f"FY{latest}"))
        if end:
            fye = "FY ends " + end.strftime("%b")
    return {"ticker": str(company.get("ticker") or ""), "name": name[:80],
            "name_sub": alt[:100] if alt and alt.lower() != name.lower() else None,
            "sector": _nice_name(details.get("sic_description"), 60),
            "sector_code": str(details.get("sic_code") or "").strip() or None,
            "exchange": EXCHANGES.get(exchange, exchange) or None,
            "accounting_standard": f"Form {form} filer" if form else "SEC filer",
            "fiscal_year_end": fye,
            "tags": [f"{newest.title}"] if newest else []}


def _corporate_info(company: dict, details: dict) -> list[dict]:
    rows = []
    exchange = str(details.get("primary_exchange") or "").strip()
    if exchange:
        rows.append({"label": "Exchange", "text": EXCHANGES.get(exchange, exchange), "href": None})
    if details.get("sic_description"):
        code = str(details.get("sic_code") or "").strip()
        rows.append({"label": "Industry", "href": None,
                     "text": (_nice_name(details["sic_description"]) or "") + (f" (SIC {code})" if code else "")})
    listed = _date_words(details.get("list_date"))
    if listed:
        rows.append({"label": "Listed since", "text": listed, "href": None})
    address = details.get("address")
    if isinstance(address, dict):
        parts = [str(address.get(k) or "").strip() for k in ("address1", "city")]
        region = " ".join(x for x in (str(address.get("state") or "").strip(),
                                      str(address.get("postal_code") or "").strip()) if x)
        text = ", ".join(x for x in parts + [region] if x)
        if text:
            rows.append({"label": "Head Office", "text": text, "href": None})
    employees = _count_text(details.get("total_employees"))
    if employees:
        rows.append({"label": "Employees", "text": employees, "href": None, "mark": REFERENCE_MARK})
    cap = _money_text(details.get("market_cap"))
    if cap:
        rows.append({"label": "Market cap", "text": cap, "href": None, "mark": REFERENCE_MARK})
    site = str(details.get("homepage_url") or "").strip()
    if site.startswith("https://"):
        rows.append({"label": "Website", "text": site[len("https://"):].rstrip("/"), "href": site})
    cik = str(company.get("cik") or "").strip()
    if cik.isdigit():
        rows.append({"label": "SEC registrant", "text": f"CIK {cik}",
                     "href": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"})
    return rows


_SMALL_WORDS = {"OF": "of", "AND": "and", "THE": "the", "FOR": "for", "IN": "in", "ON": "on"}
_SUFFIXES = {"INC": "Inc", "LTD": "Ltd", "CO": "Co", "CORP": "Corp", "CORPORATION": "Corporation",
             "LLC": "LLC", "PLC": "plc", "HLDGS": "Holdings", "HOLDINGS": "Holdings", "GRP": "Group"}


_SHARE_CLASS = re.compile(r"\b(class [a-z] common stock|common stock|ordinary shares)\b", re.IGNORECASE)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _nice_name(name, cap: int = 80) -> str | None:
    """An all-capitals SEC name or SIC description in readable case ("CHIPOTLE MEXICAN GRILL INC"
    -> "Chipotle Mexican Grill Inc"); a name already in mixed case is kept as given."""
    text = " ".join(str(name or "").split())[:cap]
    if not text:
        return None
    if text != text.upper() or not re.search(r"[A-Z]", text):
        return text
    words = []
    for i, w in enumerate(text.split(" ")):
        core = w.strip(",.")
        if core in _SUFFIXES:
            words.append(w.replace(core, _SUFFIXES[core]))
        elif i and core in _SMALL_WORDS:
            words.append(w.replace(core, _SMALL_WORDS[core]))
        elif len(core) <= 3 and core.isalpha() and i == 0 or core in ("III", "II", "IV", "USA", "US", "AT&T"):
            words.append(w)
        else:
            words.append("-".join(part[:1] + part[1:].lower() for part in w.split("-")))
    return " ".join(words)


_PLACEHOLDER_DEBRIS = re.compile(r"\[\[F:[^\]\s]*(?:\]\])?")


def _dedupe_reasons(text: str) -> str:
    """`Removed by review (r1; r1'): sentence` with r1' saying the same as r1 (same quoted phrase,
    or the same words) keeps one reason."""
    m = re.match(r"^([^()]*\()(.+?)(\):\s.*)$", text, re.S)
    if not m:
        return text
    kept, seen = [], set()
    for reason in m.group(2).split("; "):
        quoted = re.search(r"['‘“\"]([^'’”\"]+)['’”\"]", reason)
        key = (quoted.group(1) if quoted else reason).strip().lower().rstrip(".")
        if key and key not in seen:
            seen.add(key)
            kept.append(reason.strip())
    return m.group(1) + "; ".join(kept) + m.group(3)


def _withheld_lines(withheld) -> list[str]:
    """Each withheld sentence once, readable: `audit.readable` when the audit has it, then no raw
    placeholder (a cut-off `[[F:...` too) and no reason given twice."""
    try:
        from backend.verify import audit as _audit
        readable = getattr(_audit, "readable", None)
    except Exception:
        readable = None
    out, seen = [], set()
    for w in withheld or []:
        text = str(w or "").strip()
        if not text:
            continue
        if callable(readable):
            try:
                text = str(readable(text) or "").strip() or text
            except Exception:
                pass
        text = _dedupe_reasons(_PLACEHOLDER_DEBRIS.sub("[figure]", text))
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _share_count(ledger, stock: dict, multiple_rows: list[dict], valuation: dict | None = None) -> dict:
    """ONE share count for the page: the newest reported count in the ledger with its own date
    when it is recent (400 days, the multiples' rule); else the count the multiples used (market
    data, from the first row whose price note names it); else the newest reported count. Never "not available" when a count exists."""
    held = None
    for period in ledger.periods("shares_outstanding"):
        f = ledger.get("shares_outstanding", period)
        if f is not None and f.value is not None and f.value > 0:
            held = f
            break
    reference = _iso(stock.get("latest_iso")) or date.today()
    counted = _iso(held.period) if held is not None else None
    if held is not None and counted is not None and (reference - counted).days <= 400:
        return {"value": _cite(ledger, held), "period": fmt.period_label(held.period), "mark": None}
    for m in multiple_rows:                         # the first row that names its share count
        found = re.search(r"shares: (.+?) \((market data|supplied with the price)", str(m.get("price_note") or ""))
        if found:
            return {"value": Markup("%s") % found.group(1), "period": None, "mark": "market data, Massive"}
    if isinstance(valuation, dict) and valuation.get("shares_text"):     # the count the valuation used
        return {"value": Markup("%s") % valuation["shares_text"], "period": None,
                "mark": str(valuation.get("shares_note") or "") or None}
    if held is not None:
        return {"value": _cite(ledger, held), "period": fmt.period_label(held.period), "mark": None}
    return {"value": _na(), "period": None, "mark": None}


def _reporting_currency(ledger, latest: int | None) -> str:
    """The unit of the company's own reported revenue (else net income, else total assets)."""
    for key in ("revenue", "net_income", "total_assets"):
        f = annual_fact(ledger, key, latest) if latest is not None else None
        if f is None:
            for period in ledger.periods(key):
                f = ledger.get(key, period)
                break
        if f is not None and re.fullmatch(r"[A-Z]{3}", f.unit or ""):
            return f.unit
    return "USD"


def _annual_form(ledger) -> str:
    """The form of the newest annual filing among the sources ("10-K", "20-F", "40-F")."""
    annual = [s for s in ledger.sources() if re.search(r"Form\s+(10-K|20-F|40-F)\b", s.title or "")]
    if not annual:
        return "10-K"
    newest = max(annual, key=lambda s: s.date or "")
    return re.search(r"Form\s+(10-K|20-F|40-F)", newest.title).group(1)


def _risk_label(themes: list[dict], form: str) -> str:
    """"Form 20-F, Item 3.D" from the themes' own source title; just the form when it names no item."""
    for t in themes or []:
        title = str((t.get("source") or {}).get("title") or "")
        m = re.search(r"filed \d{4}-\d{2}-\d{2},\s*(.+)$", title)
        if m and m.group(1).strip():
            return f"Form {form}, {m.group(1).strip()}"
    return f"Form {form}"


def _fact_year(ledger, f: Fact) -> int | None:
    m = re.match(r"^(?:FY|Q[1-4]-)(\d{4})$", f.period or "")
    if m:
        return int(m.group(1))
    day = _iso(f.period)
    return day.year if day else None


def _peers(peers: list) -> dict:
    rows, labels = [], []
    for p in peers or []:
        if isinstance(p, dict):
            ticker, name, cells = str(p.get("ticker") or "").strip(), p.get("name"), p.get("cells") or {}
        else:
            ticker, name, cells = str(p or "").strip(), None, {}
        if not ticker:
            continue
        given = {}
        for label, value in (cells.items() if isinstance(cells, dict) else []):
            label = str(label)
            if label not in labels:
                labels.append(label)
            given[label] = Markup(value) if isinstance(value, str) else None
        rows.append({"ticker": ticker, "name": str(name).strip() if name else None, "given": given})
    for r in rows:
        r["cells"] = [r.pop("given").get(label) or _na(short=True) for label in labels]
    return {"rows": rows, "labels": labels, "empty_text": NO_PEERS,
            "basis": "Related companies as listed by Massive." if rows else None}


def _football_field(cases: list[dict], market: dict) -> dict | None:
    """The original's football field geometry: every case's low-high band and base dot, and the
    market line, on one scale padded 5% each side (not below zero when nothing is negative)."""
    values = [v for c in cases for v in (c["low"], c["base"], c["high"]) if v is not None]
    ev = _num(market.get("enterprise_value"))
    if ev is not None:
        values.append(ev)
    if not values:
        return None
    lo, hi = min(values), max(values)
    span = (hi - lo) or abs(hi) or 1.0
    ax_lo, ax_hi = lo - span * 0.05, hi + span * 0.05
    if lo >= 0:
        ax_lo = max(ax_lo, 0.0)
    width = ax_hi - ax_lo

    def pct(v: float) -> float:
        return round((v - ax_lo) / width * 100, 2)

    rows = []
    for c in cases:
        band = None
        if c["low"] is not None and c["high"] is not None:
            a, b = sorted((c["low"], c["high"]))
            band = {"left": pct(a), "width": round(max(pct(b) - pct(a), 0.6), 2)}
        rows.append({"label": c["label"], "primary": c["key"] == "base", "band": band,
                     "dot": pct(c["base"]) if c["base"] is not None else None})
    line = None
    if ev is not None:
        p = pct(ev)
        line = {"pct": p, "text": str(market.get("text") or "") or _money_text(ev),
                "anchor": "end" if p > 70 else ("start" if p < 30 else "middle")}
    return {"rows": rows, "line": line,
            "axis": [_money_text(ax_lo), _money_text((ax_lo + ax_hi) / 2), _money_text(ax_hi)]}


def _scenarios(scenarios: dict | None) -> dict | None:
    if not scenarios:
        return None

    def safe(value) -> Markup:
        return Markup(value) if isinstance(value, str) and value.strip() else _na(short=True)

    def plain(value) -> str | Markup:
        return str(value) if value not in (None, "") else _na(short=True)

    rows = [{"label": str(r.get("label") or ""), "cells": [safe(c) for c in r.get("cells") or []]}
            for r in scenarios.get("rows") or [] if isinstance(r, dict)]
    columns = [str(c) for c in scenarios.get("columns") or []]
    width = max([len(r["cells"]) for r in rows] or [0])
    header = columns if len(columns) == width + 1 else [""] + columns[:width] + [""] * max(0, width - len(columns))
    cases = []
    for c in scenarios.get("cases") or []:
        if not isinstance(c, dict):
            continue
        cases.append({"key": str(c.get("key") or ""), "label": str(c.get("label") or c.get("key") or ""),
                      "growth": plain(c.get("growth_text")), "assumption": plain(c.get("assumption")),
                      "low": _num(c.get("low")), "base": _num(c.get("base")), "high": _num(c.get("high")),
                      "low_text": plain(c.get("low_text")), "base_text": plain(c.get("base_text")),
                      "high_text": plain(c.get("high_text"))})
    market = scenarios.get("market") if isinstance(scenarios.get("market"), dict) else {}
    return {"title": str(scenarios.get("title") or "") or None,
            "period": str(scenarios.get("period") or "") or None,
            "assumptions": [{"label": str(a.get("label") or ""), "value": safe(a.get("value_html"))}
                            for a in scenarios.get("assumptions") or [] if isinstance(a, dict)],
            "header": header if rows else [], "rows": rows,
            "note": str(scenarios.get("note") or "") or None,
            "cases": cases,
            "field": _football_field(cases, market) if cases else None,
            "market_note": ((str(market.get("note") or "") or None)
                            if _num(market.get("enterprise_value")) is not None
                            else (str(market.get("reason") or "") or None)) if cases else None,
            "subline": VALUATION_SUBLINE}


def _thesis(thesis: dict | None) -> dict | None:
    """Investment thesis and the bull and bear points: html already checked and linked."""
    if not isinstance(thesis, dict):
        return None

    def points(items) -> list[dict]:
        out = []
        for x in items or []:
            if not isinstance(x, dict) or _safe(x.get("html")) is None:
                continue
            out.append({"title": str(x.get("title") or "") or None, "html": _safe(x.get("html")),
                        "analysis": x.get("method") == "model", "rule": str(x.get("rule") or "") or None,
                        "signal": str(x.get("signal") or "") or None})
        return out

    return {"points": points(thesis.get("thesis")), "bull": points(thesis.get("bull")),
            "bear": points(thesis.get("bear")), "empty_side": NO_RULE_FIRED, "note": BULLBEAR_NOTE,
            "analysis_title": ANALYSIS_TITLE}


def _risk_dashboard(thesis_view: dict | None, themes: list[dict]) -> list[dict]:
    rows = [{"chip": "WATCH", "cls": "chip-watch", "name": p["rule"] or p["signal"] or "Bear point",
             "html": p["html"]} for p in (thesis_view or {}).get("bear") or []
            # a bear point quoted from the filing is one of the FILED themes below: not twice
            if p.get("method") != "filed" and p.get("signal") != "risk_theme"]
    rows += [{"chip": "FILED", "cls": "chip-filed", "name": t["title"], "html": None} for t in themes]
    return rows


def _peer_table(peer_table: dict | None, own: dict) -> dict | None:
    """The peer table: the report's own company first (from the main ledger), then each peer's
    already-linked cells; a peer with an error shows it across its row."""
    if not isinstance(peer_table, dict):
        return None
    columns = [(str(c[0]), str(c[1])) for c in peer_table.get("columns") or []
               if isinstance(c, (list, tuple)) and len(c) >= 2]
    rows = [{"ticker": own["ticker"], "name": _nice_name(own["name"]), "period": own["period"], "own": True,
             "cells": [own["cell"](key) for key, _ in columns], "error": None}]
    for r in peer_table.get("rows") or []:
        if not isinstance(r, dict) or not str(r.get("ticker") or "").strip():
            continue
        cells = r.get("cells") if isinstance(r.get("cells"), dict) else {}
        rows.append({"ticker": str(r["ticker"]).strip(), "name": _nice_name(r.get("name")),
                     "period": str(r.get("period_label") or "") or None, "own": False,
                     "cells": [_safe(cells.get(key)) or _na(short=True) for key, _ in columns],
                     "error": str(r["error"]) if r.get("error") else None})
    medians = peer_table.get("medians") if isinstance(peer_table.get("medians"), dict) else {}
    shown = []
    for key, label in columns:
        m = medians.get(key)
        if isinstance(m, dict) and m.get("text"):
            shown.append({"label": label, "text": str(m["text"]), "n": m.get("n")})
    note = str(peer_table.get("note") or "").strip()
    slow = [str(t).strip() for t in peer_table.get("slow") or [] if str(t).strip()]
    if slow:
        note = (note + " " if note else "") + f"(not loaded in time: {', '.join(slow)})"
    return {"columns": [label for _, label in columns], "rows": rows, "medians": shown, "note": note or None}


def _disclosures(items) -> list[dict] | None:
    if items is None:
        return None
    out = []
    for d in items or []:
        if not isinstance(d, dict):
            continue
        url = str(d.get("url") or "")
        out.append({"date": str(d.get("date_text") or d.get("date") or "") or None,
                    "kind": str(d.get("form") or "") or None,
                    "title": str(d.get("title") or d.get("form") or "Filing"),
                    "url": url if url.startswith("https://") else None,
                    "detail": str(d.get("detail") or "") or None})
    return out


def _per_share_text(value: float) -> str:
    return fmt.fact(Fact(key="model_value", period="-", value=float(value), unit="USD/share"))


def _scale(values: list[float]) -> tuple[float, float]:
    """The original's football-field axis: the data's range padded 5% each side, not below zero
    when nothing is negative. Every position is then a percentage on this one scale."""
    lo, hi = min(values), max(values)
    span = (hi - lo) or abs(hi) or 1.0
    ax_lo, ax_hi = lo - span * 0.05, hi + span * 0.05
    if lo >= 0:
        ax_lo = max(ax_lo, 0.0)
    return ax_lo, ax_hi


def _valuation(valuation: dict | None) -> dict | None:
    """The original's valuation panel from backend.analysis.valuation's output: football field
    of the priced methods + BLENDED, the last-close line, the methods table, advisor and
    methodology. All geometry here; every text is the module's own."""
    if not isinstance(valuation, dict):
        return None
    methods = [m for m in valuation.get("methods") or [] if isinstance(m, dict) and m.get("label")]
    priced = [m for m in methods if _num(m.get("value")) is not None]
    unpriced = [m for m in methods if _num(m.get("value")) is None]
    blend = valuation.get("blend") if isinstance(valuation.get("blend"), dict) else {}
    price = _num(valuation.get("price"))
    b_value, b_low, b_high = _num(blend.get("value")), _num(blend.get("low")), _num(blend.get("high"))

    values = [v for m in priced for v in (_num(m.get("value")), _num(m.get("low")), _num(m.get("high")))
              if v is not None]
    values += [v for v in (b_value, b_low, b_high, price) if v is not None]
    field = None
    if priced or b_value is not None:
        ax_lo, ax_hi = _scale(values)
        width = ax_hi - ax_lo

        def pct(v: float) -> float:
            return round((v - ax_lo) / width * 100, 2)

        def band(lo, hi):
            if lo is None or hi is None:
                return None
            a, b = sorted((lo, hi))
            return {"left": pct(a), "width": round(max(pct(b) - pct(a), 0.6), 2)}

        shares = [_num(m.get("share")) for m in priced]
        top = max((s for s in shares if s is not None), default=None)
        rows = []
        for m, share in zip(priced, shares):
            label = str(m["label"]) + (f" {m['share_text']}" if m.get("share_text") else "")
            rows.append({"label": label, "primary": top is not None and top > 0 and share == top,
                         "band": band(_num(m.get("low")), _num(m.get("high"))), "dot": pct(_num(m["value"]))})
        line = None
        if price is not None:
            p = pct(price)
            line = {"pct": p, "text": f"Last close {valuation.get('price_text') or _per_share_text(price)}",
                    "anchor": "end" if p > 70 else ("start" if p < 30 else "middle")}
        field = {"rows": rows, "line": line,
                 "blended": ({"band": band(b_low, b_high), "dot": pct(b_value) if b_value is not None else None}
                             if (b_value is not None or (b_low is not None and b_high is not None)) else None),
                 "axis": [_per_share_text(ax_lo), _per_share_text((ax_lo + ax_hi) / 2), _per_share_text(ax_hi)]}

    def basis(m) -> str:
        text = str(m.get("basis") or "—")
        n = _num(m.get("n_peers"))
        return text + (f" (n={int(n)} peers)" if n else "")

    table = [{"label": str(m["label"]), "basis": basis(m), "inputs": _safe(m.get("inputs_html")) or _na(short=True),
              "value": str(m.get("value_text") or "—"), "range": str(m.get("range_text") or "—"),
              "share": str(m.get("share_text") or "—"), "note": str(m.get("note") or "") or None,
              "weight": m.get("weight"), "primary": bool(field and r["primary"])}
             for m, r in zip(priced, (field or {}).get("rows") or [{"primary": False}] * len(priced))]
    na_rows = [{"label": str(m["label"]), "basis": basis(m),
                "reason": str(m.get("reason") or "the method did not price on this data")} for m in unpriced]
    nothing_priced = not priced or _num(valuation.get("priced")) == 0
    pill = None
    if blend.get("value_text") and b_value is not None and not nothing_priced:
        pill = f"MODEL VALUE: {blend['value_text']}" + (
            f" ({blend['vs_price_text']} vs last close)" if blend.get("vs_price_text") else "")
    quality = valuation.get("quality") if isinstance(valuation.get("quality"), dict) else {}
    score = _num(quality.get("score"))
    if nothing_priced or b_value is None:
        score = None                               # a score for nothing priced would mean nothing
    advisor = valuation.get("advisor") if isinstance(valuation.get("advisor"), dict) else {}
    price_note = None
    if valuation.get("price_text"):
        price_note = (f"Last close {valuation['price_text']}"
                      + (f", {valuation['price_date_text']}" if valuation.get("price_date_text") else "")
                      + f" ({MARKET_MARK.split(': ', 1)[1]})")
        if valuation.get("shares_text"):
            price_note += f"; shares: {valuation['shares_text']}"
        if valuation.get("shares_note"):
            price_note += f" ({valuation['shares_note']})"
        price_note += "."
    return {
        "period": str(valuation.get("period_label") or "") or None,
        "pill": pill,
        "quality": {"score": int(score), "text": str(quality.get("text") or int(score)),
                    "color": "#cc2222" if score < 40 else ("#cc8800" if score < 70 else "#0a7a0a"),
                    "parts": [{"label": str(p.get("label") or ""), "text": str(p.get("text") or "")}
                              for p in quality.get("parts") or [] if isinstance(p, dict)]} if score is not None else None,
        "priced": valuation.get("priced", len(priced)), "total": valuation.get("total", len(methods)),
        "count_text": NOTHING_PRICED if nothing_priced else
                      f"{valuation.get('priced', len(priced))} priced of {valuation.get('total', len(methods))} models",
        "price_note": price_note,
        "field": field,
        "methods": table, "unpriced": na_rows,
        "blend": {"value": str(blend.get("value_text") or "—"), "range": str(blend.get("range_text") or "—"),
                  "basis": str(blend.get("basis") or "weighted average of the priced methods")} if (blend and priced) else None,
        "advisor": {"label": "AI advisor" if advisor.get("method") == "model" else "Default weights",
                    "html": _safe(advisor.get("rationale_html"))} if _safe(advisor.get("rationale_html")) else None,
        "methodology": str(valuation.get("methodology") or "") or None,
        "closing": VALUATION_CLOSING,
    }


def _anchor(raw) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(raw or ""))


def _news(news: dict | None) -> dict | None:
    """Recent web coverage: topics (model summaries, already safe) over a dated article list."""
    if not isinstance(news, dict):
        return None
    provider = str(news.get("provider") or "Massive")
    articles = []
    for a in news.get("articles") or []:
        if not isinstance(a, dict) or not a.get("title"):
            continue
        url = str(a.get("url") or "")
        sentiment = str(a.get("sentiment") or "") or None
        articles.append({"id": str(a.get("id") or ""), "anchor": f"news-{_anchor(a.get('id'))}" if a.get("id") else None,
                         "title": str(a["title"]), "publisher": str(a.get("publisher") or "") or None,
                         "date": str(a.get("date_text") or a.get("date") or "") or None,
                         "url": url if url.startswith("https://") else None,
                         "summary": str(a.get("summary") or "") or None,
                         "sentiment": f"{provider}: {sentiment}" if sentiment else None})
    if not articles:
        return None
    known = {a["id"]: a["anchor"] for a in articles if a["id"] and a["anchor"]}
    topics = []
    for t in news.get("topics") or []:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        refs = [{"id": str(i), "anchor": known[str(i)]} for i in t.get("articles") or [] if str(i) in known]
        topics.append({"title": str(t["title"]), "summary": _safe(t.get("summary_html")), "refs": refs})
    return {"articles": articles, "topics": topics, "provider": provider,
            "window": str(news.get("window_text") or "recent coverage"),
            "closing": NEWS_CLOSING.format(provider=provider)}


def _release(release: dict | None) -> dict | None:
    """Management commentary: the latest results release's own words, each with its topic."""
    if not isinstance(release, dict):
        return None
    statements = []
    for s in release.get("statements") or []:
        if not isinstance(s, dict) or not (s.get("quote") or s.get("summary_html")):
            continue
        quote = str(s.get("quote") or "").strip().lstrip("•·◦▪*–—- \t").strip()
        statements.append({"topic": str(s.get("topic") or "Other"), "summary": _safe(s.get("summary_html")),
                           "quote": quote or None})
    if not statements:
        return None
    url = str(release.get("url") or "")
    return {"title": str(release.get("title") or "Results release"), "filed": str(release.get("filed_text") or "") or None,
            "form": str(release.get("form") or "") or None, "statements": statements,
            "source_title": str(release.get("source_title") or release.get("title") or "the release"),
            "url": url if url.startswith("https://") else None, "closing": RELEASE_CLOSING}


def _review_line(review) -> str:
    if not isinstance(review, dict) or not _num(review.get("reviewers_answered")):
        return "Self-check did not run."
    n, removed = int(_num(review.get("sentences")) or 0), int(_num(review.get("rejected")) or 0)
    return (f"Self-check: {n} sentence{'' if n == 1 else 's'} read by two independent reviewers, "
            f"{removed} removed.")


def _risk_themes(themes: list | None) -> list[dict]:
    out = []
    for t in themes or []:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        src = t.get("source") if isinstance(t.get("source"), dict) else {}
        url = str(src.get("url") or "")
        out.append({"title": str(t["title"]),
                    "summary": Markup(t["summary_html"]) if isinstance(t.get("summary_html"), str) else None,
                    # a list bullet glyph in front of the filing's words is layout, not wording
                    "quote": str(t.get("quote") or "").strip().lstrip("\u2022\u00b7\u25e6\u25aa*\u2013\u2014- \t").strip() or None,
                    "source": {"title": str(src.get("title") or "the filing"),
                               "url": url if url.startswith("https://") else None,
                               "date": str(src.get("date") or "") or None} if src else None})
    return out


# ---- the context ----------------------------------------------------------------------------
def build_context(*, job: dict, company: dict, ledger, sections: dict[str, str],
                  withheld: list[str], bars: list, previous_close: dict | None,
                  peers: list, notes: list[str], scenarios: dict | None = None,
                  risk_themes: list | None = None, thesis: dict | None = None,
                  multiples: list | None = None, peer_table: dict | None = None,
                  disclosures: list | None = None, review: dict | None = None,
                  valuation: dict | None = None, news: dict | None = None,
                  release: dict | None = None, financial: bool = False) -> dict:
    company = company or {}
    details = company.get("details") if isinstance(company.get("details"), dict) else {}
    years = fiscal_years(ledger)[:YEARS]           # newest first
    chrono = list(reversed(years))                 # oldest first, as the original's tables
    latest = years[0] if years else None
    latest_label = fmt.period_label(f"FY{latest}") if latest is not None else None
    stock = _stock_info(bars, previous_close)
    currency = _reporting_currency(ledger, latest)
    cur_short = "$" if currency == "USD" else currency
    form = _annual_form(ledger)

    def at(key: str, year: int | None) -> Fact | None:
        return annual_fact(ledger, key, year) if year is not None else None

    # sidebar: the original's PRICE / MKT CAP top when there is a close, else the latest year's
    # revenue and net income; then VALUATION (the company's own multiples), then the ledger groups
    market_cap = _money_text(details.get("market_cap"))
    top_mark = None
    if stock["latest_close"]:
        headline = [{"label": "Price", "period": stock["latest_date"], "value": stock["latest_close"], "big": True},
                    {"label": "Mkt Cap", "period": None, "value": market_cap or _na(), "big": False}]
        top_mark = f"{MARKET_MARK}" + (f", {stock['latest_date']}" if stock["latest_date"] else "") + (
            "; market cap: Massive reference data" if market_cap else "") + "."
    else:
        headline = [{"label": label, "period": latest_label, "value": _cite(ledger, at(key, latest)),
                     "big": key == "revenue"} for label, key in (("Revenue", "revenue"), ("Net income", "net_income"))]
    groups, definitions = [], []
    financial = bool(financial)
    sidebar_spec = [(title, tuple((label, key) for label, key in items
                                  if not (financial and key in NOT_FOR_FINANCIALS)))
                    for title, items in SIDEBAR]
    multiple_rows = [m for m in multiples or [] if isinstance(m, dict) and m.get("label")]
    if multiple_rows:
        rows = []
        for m in multiple_rows:
            text = str(m.get("text") or fmt.NOT_AVAILABLE)
            ok = _num(m.get("value")) is not None
            reason = None if ok else (str(m.get("reason") or "").strip()
                                      or (text.split(": ", 1)[1] if ": " in text else None))
            label = MULTIPLE_LABELS.get(str(m.get("key")), str(m["label"]))
            not_for_banks = text.lower().startswith("not used for a bank") or (
                text.startswith("Not available") and reason and re.search(r"\bnot used for (a )?banks?\b", reason, re.I))
            if not ok and not_for_banks:
                rows.append({"label": label, "value": Markup('<span class="na">%s</span>') % NOT_FOR_BANKS,
                             "note": None})
                continue                     # does not apply: no definition either
            rows.append({"label": label, "value": text if ok else _na(), "note": reason})
            inputs = [Markup("%s, %s: ") % (i.get("label", ""), i.get("period", "")) + (_safe(i.get("value_html")) or _na())
                      for i in m.get("inputs") or [] if isinstance(i, dict)]
            footnote = Markup("%s") % _formula_words(m.get("formula"))
            if m.get("price_note"):
                footnote += Markup("; %s") % m["price_note"]
            if inputs:
                footnote += Markup("; ") + Markup("; ").join(inputs)
            definitions.append({"field": str(m["label"]), "footnote": footnote})
        groups.append({"label": "Valuation", "rows": rows})
    for title, items in sidebar_spec:
        rows = []
        for label, key in items:
            f = at(key, latest)
            rows.append({"label": label, "value": _cite(ledger, f),
                         "note": f.note if f is not None and f.value is None else None})
        if title == "Structure" and stock["week_52_high"]:
            rows.append({"label": f"52w Range ({stock['range_basis']})",
                         "value": f"{stock['week_52_low']}–{stock['week_52_high']}",
                         "note": f"{MARKET_MARK}" + (f", since {stock['range_since']}" if stock["range_since"] else "") + "."})
        groups.append({"label": title, "rows": rows})
    for title, items in sidebar_spec:
        for label, key in items:
            f = at(key, latest)
            if f is not None and f.is_computed:
                definitions.append({"field": label, "footnote": f"{_formula_words(f.formula)}, "
                                                                f"{fmt.period_label(f.period)}"})

    # mini charts -----------------------------------------------------------------------------
    charts = []
    for key, title, note, cls in (FINANCIAL_CHARTS if financial else CHARTS):
        facts = [at(key, y) for y in chrono]
        zero, rects = _plot([_value(f) for f in facts])
        charts.append({"title": title.format(cur=cur_short), "note": note, "cls": cls, "zero": zero,
                       "empty": all(_value(f) is None for f in facts),
                       "bars": [{"label": _fy(y, short=True), "value": _cite_tight(ledger, f), "rect": r}
                                 for y, f, r in zip(chrono, facts, rects)]})

    # income statement ------------------------------------------------------------------------
    columns = list(STATEMENT_COLUMNS)
    if not any(at("eps_diluted", y) for y in chrono) and any(at("eps_basic", y) for y in chrono):
        columns[4] = ("eps_basic", "EPS (basic)")
    if financial:
        columns = [c for c in columns if c[0] not in NOT_FOR_FINANCIALS]
    hide, missing_cell = [], False
    statement_rows = []
    for y in chrono:
        cells = []
        for key, _ in columns:
            f = at(key, y)
            missing_cell = missing_cell or _value(f) is None
            cells.append(_cite(ledger, f, short=True) if _value(f) is None else _cite(ledger, f))
        end = _date_words(ledger.period_end(f"FY{y}"))
        statement_rows.append({"period": _fy(y), "period_span": f"ended {end}" if end else None,
                               "cells": cells})
    for i, (key, _) in enumerate(columns):
        if not any(_value(at(key, y)) is not None for y in chrono):
            hide.append(f"is-hide-c{i + 2}")
    if len(hide) >= len(columns):
        hide = []
    statement_notes = []
    if statement_rows:
        statement_notes.append(f"Annual figures as filed with the SEC (Form {form} XBRL data); "
                               "each figure links to its filing.")
        if missing_cell:
            statement_notes.append(f"n/a = {fmt.NOT_AVAILABLE}.")

    # capital structure -----------------------------------------------------------------------
    ye = ledger.period_end(f"FY{latest}") if latest is not None else None
    ye_label = fmt.period_label(ye) if ye else latest_label
    equity, liabilities = at("shareholders_equity", latest), at("total_liabilities", latest)
    eq_bar = None
    assets = at("total_assets", latest)
    if _value(equity) is not None and _value(liabilities) is not None and equity.value > 0 and liabilities.value >= 0:
        whole, other = equity.value + liabilities.value, 0.0
        if _value(assets) is not None and assets.value > 0:
            rest = assets.value - liabilities.value - equity.value
            if rest > assets.value * 0.01:          # e.g. preferred stock outside equity: shown, not hidden
                whole, other = assets.value, rest
        eq_bar = {"equity_pct": round(equity.value / whole * 100, 2),
                  "liab_pct": round(liabilities.value / whole * 100, 2),
                  "other_pct": round(other / whole * 100, 2) if other else 0}
    ocf, capex, fcf = at("operating_cash_flow", latest), at("capex", latest), at("free_cash_flow", latest)
    flows = [("cfo", "OCF", ocf), ("capex", "CAPEX", capex), ("fcf", "FCF", fcf)]
    if financial:
        flows = [x for x in flows if x[0] != "fcf" and _value(x[2]) is not None]
    flows = [x for x in flows if _value(x[2]) is not None]
    zero, rects = _plot([_value(f) for _, _, f in flows])
    cf_bars = []
    for (key, name, f), rect in zip(flows, rects):
        if rect is None:
            continue
        v = _value(f)
        color = "#cc4444" if (v < 0 or key == "capex") else ("#0a7a0a" if key == "cfo" else "#2E59A7")
        cf_bars.append({"key": key, "name": name, "y": rect["y"], "h": rect["h"], "neg": v < 0,
                        "color": color, "outflow": key == "capex", "display": _cite_tight(ledger, f)})
    trend_years = [y for y in chrono if any(_value(at(k, y)) is not None for _, k, _ in TREND_ROWS[:4])]
    trend = None
    if len(trend_years) >= 2:
        trend_rows = []
        for label, key, cls in TREND_ROWS:
            cells, prior = [], None
            for y in trend_years:
                f = at(key, y)
                v = _value(f)
                arrow = None
                if v is not None and prior is not None and v != prior:
                    arrow = "up" if v > prior else "down"
                cells.append({"value": _cite_tight(ledger, f), "dir": arrow})
                prior = v if v is not None else prior
            if any(_value(at(key, y)) is not None for y in trend_years):
                trend_rows.append({"label": label, "cls": cls, "cells": cells})
        trend = {"periods": [_fy(y) for y in trend_years], "rows": trend_rows} if trend_rows else None
    capital = {
        "period": ye_label,
        "assets": [{"label": label, "value": _cite(ledger, at(key, latest))} for label, key in
                   (("Total assets", "total_assets"), ("Cash & equivalents", "cash"),
                    ("Total liabilities", "total_liabilities"), ("Shareholders' equity", "shareholders_equity"))],
        "eq_bar": eq_bar,
        "leverage": [{"label": "Long-term debt", "value": _cite(ledger, at("long_term_debt", latest))},
                     {"label": "LT debt / equity", "value": _cite(ledger, at("debt_to_equity", latest))}],
        "leverage_title": "Funding" if financial else "Leverage",
        "leverage_note": FUNDING_NOTE if financial else "Debt is long-term debt as tagged in the filing's XBRL data.",
        "cash_flow_note": None if (financial and _value(at("capex", latest)) is None) else ("Capital expenditure is the company's reported cash purchases of property and "
                           "equipment (for some companies one line together with intangible assets)."),
        "cash_flow_period": latest_label,
        "cf_bars": cf_bars,
        "cf_zero": zero,
        "cash_flow": [{"label": label, "value": _cite(ledger, at(key, latest))} for label, key in
                      (("Operating cash flow", "operating_cash_flow"), ("Capital expenditure", "capex"),
                       ("Free cash flow", "free_cash_flow"), ("FCF margin", "fcf_margin"))
                      if not (financial and (key in NOT_FOR_FINANCIALS
                                             or (key == "capex" and _value(at(key, latest)) is None)))],
        "per_share": [{"label": label, "period": latest_label, "value": _cite(ledger, at(key, latest))}
                      for label, key in (("EPS (basic)", "eps_basic"), ("EPS (diluted)", "eps_diluted"),
                                         ("DPS", "dividends_per_share"))],
        "trend": trend,
    } if latest is not None else None

    allocation = None
    alloc_rows = [(label, key) for label, key in ALLOCATION_ROWS
                  if not (financial and key in NOT_FOR_FINANCIALS)
                  and any(_value(at(key, y)) is not None for y in chrono)]
    alloc_years = [y for y in chrono if any(_value(at(key, y)) is not None for _, key in alloc_rows)]
    if alloc_rows and alloc_years:
        allocation = {"periods": [_fy(y) for y in alloc_years],
                      "rows": [{"label": label, "cells": [_cite(ledger, at(key, y), short=_value(at(key, y)) is None)
                                                          for y in alloc_years]}
                               for label, key in alloc_rows]}

    # calculations and sources ----------------------------------------------------------------
    calculations, window = [], set(chrono)
    for f in ledger.facts():
        if not f.is_computed:
            continue
        inputs = [{"label": metrics.label(k), "period": fmt.period_label(p), "value": _cite(ledger, ledger.get(k, p))}
                  for k, p in f.inputs]
        calculations.append({"id": ledger.calc_id(f), "label": metrics.label(f.key),
                             "period": fmt.period_label(f.period), "formula": _formula_words(f.formula),
                             "value": _cite(ledger, f), "note": f.note if f.value is None else None,
                             "inputs": inputs, "in_window": _fact_year(ledger, f) in window or not window})
    sources = [{"id": s.id, "title": s.title, "date": s.date, "url": s.url} for s in ledger.sources()]

    now = datetime.now(timezone.utc)
    cutoff = (now.date() - timedelta(days=365)).isoformat()
    filed = _disclosures(disclosures)
    if filed is None:                              # no disclosure list given: the ledger's own filings
        filed = []
        for s in sorted(ledger.sources(), key=lambda s: s.date or "", reverse=True):
            if (s.date or "") >= cutoff:
                m = _FORM.search(s.title or "")
                filed.append({"date": s.date, "kind": m.group(1) if m else None, "title": s.title,
                              "url": s.url, "detail": None})
        coverage = ("filings listed are the SEC EDGAR filings that supply this report's figures; "
                    "end-of-day prices from Massive")
    else:
        coverage = "SEC EDGAR filings of the last 12 months, newest first; end-of-day prices from Massive"
    news_view = _news(news)
    if news_view is not None:
        coverage += f"; web coverage through {news_view['provider']}"

    multiple_text = {str(m.get("key")): (str(m.get("text")) if _num(m.get("value")) is not None else None)
                     for m in multiple_rows}

    def own_cell(key: str) -> Markup:
        if key in multiple_text:
            return Markup("%s") % multiple_text[key] if multiple_text[key] else _na(short=True)
        if key == "market_cap":
            return Markup("%s") % market_cap if market_cap else _na(short=True)
        f = at(key, latest)
        return _cite(ledger, f) if _value(f) is not None else _cite(ledger, f, short=True)

    thesis_view = _thesis(thesis)
    themes_view = _risk_themes(risk_themes)
    intro = [str(n) for n in notes or [] if str(n).strip()
             and not str(n).startswith("The self-check removed")]
    shares = _share_count(ledger, stock, multiple_rows, valuation)
    dashboard = {
        "is_etf": False,
        "job_id": str((job or {}).get("job_id") or ""),
        "company_header": dict(_header(company, details, ledger, latest), financial=financial),
        "report_intro": intro,
        "statements_unavailable_note": None if years else (
            "Statements not available: no annual figures were found in the SEC data for this company."),
        "narrative_outlook": _narrative(sections, details.get("description")),
        "thesis": thesis_view,
        "kpi_ribbon": {"headline": headline, "top_mark": top_mark, "groups": groups, "definitions": definitions,
                       "definitions_note": "Reported figures link to their SEC filing; calculated "
                                           "figures link to their calculation below."},
        "charts_data": charts,
        "income_statement": {"columns": ["Period"] + [label for _, label in columns],
                             "rows": statement_rows, "hide": hide,
                             "empty_text": fmt.NOT_AVAILABLE},
        "income_statement_notes": statement_notes,
        "currency": currency,
        "currency_sub": "" if currency == "USD" else f", {currency}",
        "annual_form": form,
        "risk_source_label": _risk_label(themes_view, form),
        "nm_note": None,
        "capital_structure_section": capital,
        "column_3_market": {"stock_info": stock,
                            "shares_out": shares["value"],
                            "shares_period": shares["period"],
                            "shares_mark": shares["mark"],
                            "peers": _peers(peers),
                            "peer_table": _peer_table(peer_table, {
                                "ticker": str(company.get("ticker") or ""),
                                "name": str(company.get("name") or "").strip() or None,
                                "period": latest_label, "cell": own_cell}),
                            "corporate_info": _corporate_info(company, details)},
        "scenarios": _scenarios(scenarios),
        "valuation": _valuation(valuation),
        "news": news_view,
        "release": _release(release),
        "scenario_subline": SCENARIO_SUBLINE,
        "scenario_fallback": NO_SCENARIOS,
        "capital_allocation": allocation,
        "risk_dashboard": _risk_dashboard(thesis_view, themes_view),
        "risk_themes": themes_view,
        "risk_fallback": NO_RISK_THEMES,
        "sources": sources,
        "calculations": calculations,
        "withheld": _withheld_lines(withheld),
        "withheld_note": WITHHELD_NOTE,
        "footer_disclosures": filed,
        "disclosure_coverage_note": coverage,
        "report_metadata": {"generated_at": now.strftime("%d %b %Y %H:%M UTC"),
                            "source": "SEC EDGAR · Massive (end-of-day prices)", "analyst_firm": FIRM},
        "review_line": _review_line(review),
        "footer": FOOTER,
        "disclaimer": DISCLAIMER,
        "not_available": fmt.NOT_AVAILABLE,
        "calc_window_note": CALC_WINDOW_NOTE,
        "sources_note_text": SOURCES_NOTE,
        "sources_omitted": 0,
        "calculations_omitted": 0,
    }
    return {"request": None, "dashboard": dashboard}


_INNER_HREF = re.compile(r'href="#([^"]+)"')
_OUTER_HREF = re.compile(r'href="(https://[^"]+)"')


def html(context: dict) -> str:
    """The page. Calculations list the fiscal years shown plus any older row a figure on the page
    links to (followed until nothing is missing); Sources list the filings the page cites."""
    template = _env.get_template("report.html")
    dashboard = context.get("dashboard") if isinstance(context, dict) else None
    if not isinstance(dashboard, dict) or "calculations" not in dashboard or "sources" not in dashboard:
        return template.render(**context)
    every_calc, every_source = list(dashboard["calculations"]), list(dashboard["sources"])
    known = {c["id"] for c in every_calc}
    shown = {c["id"] for c in every_calc if c.get("in_window", True)}
    page = ""
    for _ in range(6):
        trial = dict(dashboard, calculations=[c for c in every_calc if c["id"] in shown], sources=[],
                     sources_omitted=0, calculations_omitted=0)
        page = template.render(**dict(context, dashboard=trial))
        wanted = {h for h in _INNER_HREF.findall(page) if h in known} - shown
        if not wanted:
            break
        shown |= wanted
    linked = set(_OUTER_HREF.findall(page))
    cited = [s for s in every_source if _html.escape(str(s.get("url") or ""), quote=True) in linked]
    final = dict(dashboard, calculations=[c for c in every_calc if c["id"] in shown], sources=cited,
                 sources_omitted=len(every_source) - len(cited),
                 calculations_omitted=len(every_calc) - len(shown),
                 nm_note=NM_NOTE if re.search(r">n/m<", page) else None)
    return template.render(**dict(context, dashboard=final))
