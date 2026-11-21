"""Verified SEC facts the chatbot may use. Public data only.

Source: SEC EDGAR XBRL company facts (data.sec.gov), Apple 10-K accession 0000320193-26-000026
(filed 2026-11-03), fetched 2026-11-21; every figure also appears in the 10-K text.
Copied from prism-tests/kb/aapl_key_facts_FY2026_vs_FY2025.md.
Fiscal 2026 = 2025-09-28 to 2026-09-26. Fiscal 2025 = 2024-09-29 to 2025-09-27.
"""
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

DATA = Path(__file__).parent / "data"
SRC26 = "Apple 10-K FY2026 (SEC XBRL)"
SRC25 = "Apple 10-K FY2025 (SEC XBRL)"
CALC = "Calculated from the SEC values"

# kind: usd (dollars), usd_per_share, pct (percent), pts (percentage points)
_ROWS = [
    # id prefix,            label,                               FY2026,      FY2025,      change %, kind
    ("revenue",            "Net sales (revenue)",                478_834e6,   416_161e6,   15.06,  "usd"),
    ("gross_margin",       "Gross margin (gross profit)",        233_602e6,   195_201e6,   19.67,  "usd"),
    ("rnd",                "Research and development expense",   45_765e6,    34_550e6,    32.46,  "usd"),
    ("operating_income",   "Operating income",                   158_063e6,   133_050e6,   18.80,  "usd"),
    ("net_income",         "Net income",                         132_175e6,   112_010e6,   18.00,  "usd"),
    ("eps_diluted",        "Diluted earnings per share",         8.98,        7.46,        20.38,  "usd_per_share"),
    ("cash",               "Cash and cash equivalents (year end)", 36_305e6,  35_934e6,    1.03,   "usd"),
    ("buybacks",           "Share repurchases (cash paid)",      86_390e6,    90_711e6,    -4.76,  "usd"),
]


def _build():
    facts = {}
    for key, label, v26, v25, chg, kind in _ROWS:
        facts[f"{key}_fy2026"] = dict(label=f"{label}, fiscal 2026", value=v26, kind=kind, source=SRC26)
        facts[f"{key}_fy2025"] = dict(label=f"{label}, fiscal 2025", value=v25, kind=kind, source=SRC25)
        facts[f"{key}_change_pct"] = dict(label=f"{label}, change fiscal 2025 to 2026 (%)", value=chg,
                                          kind="pct", source=CALC)
        facts[f"{key}_change_amount"] = dict(label=f"{label}, change fiscal 2025 to 2026 (amount)",
                                             value=round(v26 - v25, 2), kind=kind, source=CALC)
    facts["gross_margin_pct_fy2026"] = dict(label="Gross margin as % of net sales, fiscal 2026", value=48.79,
                                            kind="pct", source=CALC)
    facts["gross_margin_pct_fy2025"] = dict(label="Gross margin as % of net sales, fiscal 2025", value=46.91,
                                            kind="pct", source=CALC)
    facts["gross_margin_pct_change_pts"] = dict(label="Gross margin %, change fiscal 2025 to 2026 (points)",
                                                value=1.88, kind="pts", source=CALC)
    return facts


FACTS = {"AAPL": _build()}
COMPANY = {"AAPL": "Apple Inc."}

# Exact wording from Item 1A (risk factors), checked by text search in both filings.
RISK_NOTES = {"AAPL": [
    'NEW in fiscal 2026 (not in fiscal 2025): "Issues related to artificial intelligence may result in '
    "reputational, competitive and financial harm to the Company, regulatory action, legal liability, and other "
    "adverse effects to the Company's business.\"",
    'Supply risk widened. Fiscal 2025: results depend on the ability to "obtain components in sufficient '
    'quantities". Fiscal 2026: "obtain components, compute capacity and storage resources in sufficient quantities".',
    'Product defect risk now names AI. Fiscal 2026 says products "including artificial intelligence technologies '
    'and features" may be affected by design and manufacturing defects. Not in fiscal 2025.',
]}

FILING_TEXT_FILES = {"AAPL": {"FY2026": DATA / "aapl_10K_FY2026_full.txt",
                              "FY2025": DATA / "aapl_10K_FY2025_full.txt"}}
_text_cache: dict = {}


def filing_text(ticker: str, year: str) -> str:
    key = (ticker, year)
    if key not in _text_cache:
        path = FILING_TEXT_FILES.get(ticker, {}).get(year)
        _text_cache[key] = path.read_text(encoding="utf-8") if path and path.exists() else ""
    return _text_cache[key]


def _r1(x: float) -> Decimal:
    """Round half up to 1 decimal, like an analyst (34.55 -> 34.6)."""
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fmt(f: dict) -> str:
    v, k = f["value"], f["kind"]
    if k == "usd":
        sign = "-" if v < 0 else ""
        return f"{sign}${_r1(abs(v) / 1e9):,} billion"
    if k == "usd_per_share":
        return f"{'-' if v < 0 else ''}${abs(v):.2f} per share"
    if k == "pts":
        return f"{_r1(v):+} percentage points"
    return f"{_r1(v):+}%" if "change" in f["label"] else f"{_r1(v)}%"


def fact_sheet(ticker: str) -> str:
    """The only data the model sees."""
    lines = [f"{fid} | {f['label']} | {fmt(f)}" for fid, f in FACTS[ticker].items()]
    risks = "\n".join(f"- {r}" for r in RISK_NOTES.get(ticker, []))
    return ("FACTS (id | what | value):\n" + "\n".join(lines) + "\n\nRISK FACTOR CHANGES (exact quotes):\n" + risks)
