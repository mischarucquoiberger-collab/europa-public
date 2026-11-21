"""The workspace's stock price card in US dollars (owner 2026-11-22: "everything should be for US stocks").

Run after dev/patch_workspace_copy.py, dev/workspace_callisto.py and dev/workspace_query_only.py; safe to
run again:

    python3 dev/workspace_usd.py

The Query answer's price card (the client's LivePriceTicker) was built for Tokyo prices: its price and its
change were printed with a yen sign and at most one decimal. Here they become US dollars with two decimals
("$125.53", "89.97"). The card's data comes from the Callisto research desk (Massive bars); nothing else
in the client is changed. Every edit must match exactly once; the script refuses a copy it does not
recognise.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "public" / "xyz"

EDITS = [
    ("card price (big figure)",
     "_1=new Intl.NumberFormat(`en-US`,{style:`currency`,currency:`JPY`,maximumFractionDigits:1})",
     "_1=new Intl.NumberFormat(`en-US`,{style:`currency`,currency:`USD`,minimumFractionDigits:2,maximumFractionDigits:2})"),
    ("card change (amount)",
     "v1=new Intl.NumberFormat(`en-US`,{maximumFractionDigits:1})",
     "v1=new Intl.NumberFormat(`en-US`,{minimumFractionDigits:2,maximumFractionDigits:2})"),
    ("card price (chart tooltip)",
     "S1=e=>`¥${e.toLocaleString(`en-US`,{maximumFractionDigits:1})}`",
     "S1=e=>`$${e.toLocaleString(`en-US`,{minimumFractionDigits:2,maximumFractionDigits:2})}`"),
]


def main() -> int:
    assets = ROOT / "assets"
    if not assets.is_dir():
        print(f"no workspace client at {ROOT}", file=sys.stderr)
        return 1
    hits = [p for p in sorted(assets.glob("*.js"))
            if any(old in p.read_text(encoding="utf-8") or new in p.read_text(encoding="utf-8")
                   for _, old, new in EDITS)]
    if len(hits) != 1:
        print(f"refusing: expected the price card in exactly one chunk, found {len(hits)}", file=sys.stderr)
        return 1
    path = hits[0]
    text = path.read_text(encoding="utf-8")
    changed = 0
    for name, old, new in EDITS:
        n_old, n_new = text.count(old), text.count(new)
        if n_old == 0 and n_new == 1:
            continue                      # already applied
        if n_old != 1 or n_new != 0:
            print(f"refusing: '{name}' found {n_old} time(s) (applied form {n_new}) in {path.name}", file=sys.stderr)
            return 1
        text = text.replace(old, new)
        changed += 1
    for sibling in (path.with_name(path.name + ".br"), path.with_name(path.name + ".gz")):
        if sibling.exists():
            print(f"refusing: {sibling.name} would keep the old card; remove it first", file=sys.stderr)
            return 1
    if changed:
        path.write_text(text, encoding="utf-8")
    print(f"{path.name}: {changed} edit(s) applied, {len(EDITS) - changed} already in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
