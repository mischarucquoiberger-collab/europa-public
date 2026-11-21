"""A house peer group for the companies on the coverage list, used ONLY when the market data
provider lists no related companies (it leaves many smaller companies empty).

These groups are a plain sector reading of the coverage list, not data from a filing: the report
says so wherever it uses them. Every figure in the peer table still comes from each peer's own
SEC filings."""
from __future__ import annotations

# the first group that contains the ticker is its group; order inside a group is the display order
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Consumer internet and software", ("DUOL", "DOCS", "UPST", "ETSY", "ADBE", "CRM", "NFLX")),
    ("Consumer brands", ("CROX", "NKE", "YETI", "BOOT", "ELF", "CELH")),
    ("Restaurants", ("CAVA", "SHAK", "WING", "MCD")),
    ("Retail", ("FIVE", "SFM", "COST", "WMT", "ETSY", "BOOT")),
    ("Consumer staples", ("KO", "PEP", "PG", "CELH", "COST", "WMT")),
    ("Banks and payments", ("BAC", "JPM", "MA", "V", "UPST")),
    ("Health care", ("ABBV", "JNJ", "LLY", "UNH", "DOCS")),
    ("Energy", ("CVX", "XOM")),
    ("Media and leisure", ("DIS", "NFLX", "PLNT")),
    ("Large technology", ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "AMD", "ORCL", "TSLA")),
)
NOTE = ("Peer group: the same sector within this coverage list (the market data provider lists too few "
        "related companies in the same industry).")


def group_of(ticker: str) -> tuple[str, tuple[str, ...]] | None:
    symbol = str(ticker or "").strip().upper().replace("-", ".")
    for name, members in GROUPS:
        if symbol in members:
            return name, members
    return None


def fallback(ticker: str) -> list[str]:
    """The other members of the ticker's group, in display order; [] when it is in none."""
    found = group_of(ticker)
    if found is None:
        return []
    symbol = str(ticker).strip().upper().replace("-", ".")
    return [m for m in found[1] if m != symbol]
