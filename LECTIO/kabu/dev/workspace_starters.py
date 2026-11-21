"""Three starter questions under the Callisto landing's question box (owner 2026-11-22).

Run after dev/workspace_query_only.py; safe to run again:

    python3 dev/workspace_starters.py

The starters live in one self-contained file, public/xyz/assets/callisto/starters.js (its own
style, its own container outside the app's React tree; nothing in the bundle is edited). This
script only loads it: one script tag, inserted immediately before </head> in public/xyz/index.html.
The insertion point must match exactly once; the script refuses a page it does not recognise.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "public" / "xyz"
SRC = "assets/callisto/starters.js"
TAG = '    <script defer src="%s"></script>\n' % SRC
BEFORE = "  </head>"


def main():
    if not (ROOT / SRC).is_file():
        sys.exit(f"workspace_starters: {SRC} is missing under {ROOT}")
    page = ROOT / "index.html"
    html = page.read_text()
    if SRC in html:
        print("workspace_starters: nothing to do")
        return
    if html.count(BEFORE) != 1:
        sys.exit(f"workspace_starters: expected exactly one {BEFORE.strip()!r}, found {html.count(BEFORE)}")
    page.write_text(html.replace(BEFORE, TAG + BEFORE))
    print("workspace_starters:", page.name)


if __name__ == "__main__":
    main()
