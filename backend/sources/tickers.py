"""Ticker symbols. Inside the backend a symbol is always in one form: upper case, a class share
written with a dot (`BRK.B`). Each provider gets its own spelling at the edge:
the SEC's ticker list writes class shares with a dash (`BRK-B`); Massive uses the dot (`BRK.B`,
confirmed against the live API)."""
from __future__ import annotations

from backend import contract


def normalise(symbol: str) -> str:
    """`" brk-b "` -> `"BRK.B"`. Raises ValueError unless the symbol matches contract.TICKER_RE
    (one to five letters, optionally a dot or dash and one class letter)."""
    if not isinstance(symbol, str):
        raise ValueError(f"not a ticker symbol: {symbol!r}")
    cleaned = symbol.strip().upper()
    if not contract.TICKER_RE.fullmatch(cleaned):
        raise ValueError(f"not a ticker symbol: {symbol!r}")
    return cleaned.replace("-", ".")


def for_sec(symbol: str) -> str:
    """The SEC's spelling: class shares with a dash (`BRK-B`)."""
    return normalise(symbol).replace(".", "-")


def for_massive(symbol: str) -> str:
    """Massive's spelling: class shares with a dot (`BRK.B`)."""
    return normalise(symbol)
