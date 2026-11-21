"""Record the SEC's public answers for the offline tests and for a demo without network.

    python3 scripts/record_fixtures.py AAPL JPM BRK.B TSM
    python3 scripts/record_fixtures.py --with-text AAPL      # also the newest annual report's document

For each symbol: the SEC ticker list, the CIK, the filings index (with its overflow files) and the
XBRL company facts, saved under tests/backend/fixtures/replay/ (or REPLAY_DIR). This is public
data and the recordings are committed. Massive is never called here: provider data stays in the
git-ignored cache. Prints URLs and file names only, never a header, the contact line or a key.
Needs SEC_USER_AGENT in .env (a name and a contact address; the SEC requires both).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import settings  # noqa: E402  (loads .env through the root config)
from backend.sources import sec, tickers  # noqa: E402
from backend.sources.http import Client, SourceUnavailable  # noqa: E402

ANNUAL_FORMS = ("10-K", "20-F")


def _print_new(client: Client, seen: set[str]) -> None:
    for url, name in client.recorded:
        if name not in seen:
            seen.add(name)
            print(f"  saved {url}\n     -> {name}")


def record(symbol: str, client: Client, seen: set[str], with_text: bool) -> bool:
    """Record one symbol. True when everything it needs was saved."""
    try:
        symbol = tickers.normalise(symbol)
    except ValueError:
        print(f"{symbol!r}: not a ticker symbol, skipped")
        return False
    print(f"{symbol}:")
    try:
        cik = sec.cik_for(symbol, client)
        if cik is None:
            print("  not in the SEC's ticker list, skipped")
            _print_new(client, seen)
            return False
        found = sec.filings(cik, client=client)
        sec.company_facts(cik, client)
        if with_text:
            annual = next((f for f in found if f.form in ANNUAL_FORMS), None)
            if annual is None:
                print("  no 10-K or 20-F in the index, no document recorded")
            else:
                sec.filing_text(annual, client)
    except SourceUnavailable as error:
        _print_new(client, seen)
        print(f"  FAILED: {error.reason} ({error.url})")
        return False
    _print_new(client, seen)
    print(f"  CIK {cik}, {len(found)} filings of {', '.join(sec.DEFAULT_FORMS)}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record SEC answers for replay mode.")
    parser.add_argument("symbols", nargs="+", help="ticker symbols, e.g. AAPL JPM BRK.B TSM")
    parser.add_argument("--with-text", action="store_true",
                        help="also record the newest 10-K or 20-F primary document")
    args = parser.parse_args(argv)

    try:
        sec._agent()
    except SourceUnavailable as error:
        print(f"Cannot record: {error.reason}.")
        print("Add a line like  SEC_USER_AGENT=Your Name you@example.com  to .env and run again.")
        return 2

    replay = settings.replay_dir()
    client = Client("record", replay_dir=replay)
    print(f"Recording SEC answers into {replay}")
    seen: set[str] = set()
    results = [record(symbol, client, seen, args.with_text) for symbol in args.symbols]
    print(f"Saved {len(seen)} file(s). {results.count(True)} of {len(results)} symbol(s) complete.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
