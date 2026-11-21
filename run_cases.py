"""Run the chat cases in tests/cases.json against the newest saved report of each ticker.

    python3 run_cases.py --tag before|after [--limit N]

`before` uses the naive baseline (checks=False: the model sees raw values and is not audited);
`after` uses the real path. Each reply is judged in code against the case's `expect`, and
results/{tag}.json is written. This calls the real model: run it only on purpose. No key is
ever printed."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from backend import chat, contract, settings  # noqa: E402
from backend.ledger import Ledger  # noqa: E402

_NUM_RE = re.compile(r"(-?\$?\s?\d[\d,]*(?:\.\d+)?)\s*(%|trillion|billion|million|thousand|[TBMK]\b)?", re.I)
_SCALE = {"trillion": 1e12, "t": 1e12, "billion": 1e9, "b": 1e9, "million": 1e6, "m": 1e6,
          "thousand": 1e3, "k": 1e3}
_ADVICE_WORDS = re.compile(r"(?i)\b(you should|i recommend|we recommend|strong buy|good investment|"
                           r"worth buying|undervalued|overvalued|price target)\b")


def newest_ledger(ticker: str) -> tuple[Ledger, dict, str] | None:
    reports = settings.reports_dir()
    if not reports.is_dir():
        return None
    prefix = f"report_{ticker.upper().replace('-', '.')}_"
    found = []
    for p in reports.glob(f"{prefix}*.html"):
        if contract.REPORT_FILE_RE.fullmatch(p.name):
            found.append(p)
    for p in sorted(found, key=lambda q: q.stat().st_mtime, reverse=True):
        loaded = chat.load_ledger({"file": p.name})
        if loaded:
            return loaded[0], loaded[1], p.name
    return None


def figures(text: str) -> list[tuple[str, float, bool]]:
    """(as written, value, is_percent) for every figure in a reply; bare years are skipped."""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        digits = raw.replace("$", "").replace(",", "").replace(" ", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        if not unit and "$" not in raw and re.fullmatch(r"(19|20)\d{2}", digits):
            continue
        if not unit and "$" not in raw and abs(value) < 10 and "." not in digits:
            continue  # small counts ("1 to 3", "Q3")
        if unit == "%":
            out.append((m.group(0).strip(), value / 100.0, True))
        else:
            out.append((m.group(0).strip(), value * _SCALE.get(unit, 1.0), False))
    return out


def unmatched(text: str, ledger: Ledger) -> list[str]:
    values = [f.value for f in ledger.facts() if f.value is not None]
    bad = []
    for shown, value, _pct in figures(text):
        if not any(abs(value - v) <= max(abs(v) * 0.006, 0.0006) for v in values):
            bad.append(shown)
    return bad


def judge(case: dict, ans: chat.Answer, ledger: Ledger, tag: str) -> list[str]:
    exp = case.get("expect") or {}
    reasons = []
    if ans.kind != exp.get("kind"):
        if tag == "after" or exp.get("kind") != "answer":
            reasons.append(f"kind {ans.kind!r}, expected {exp.get('kind')!r}")
    if tag == "before":
        if exp.get("kind") == "dont_know" and chat.DONT_KNOW.split(":")[0].lower() not in ans.text.lower():
            reasons.append("did not say it does not know")
        if exp.get("kind") == "no_advice" and _ADVICE_WORDS.search(ans.text):
            reasons.append("gave advice")
    if exp.get("must_cite") and not ans.citations:
        reasons.append("no citation")
    for pattern in exp.get("must_not_contain") or []:
        if re.search(pattern, ans.text):
            reasons.append(f"contains forbidden /{pattern}/")
    if tag == "before":
        for shown in unmatched(ans.text, ledger):
            reasons.append(f"figure not in the ledger: {shown}")
    return reasons


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", choices=("before", "after"), required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    cases = json.loads((REPO / "tests" / "cases.json").read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]
    rows = []
    for case in cases:
        loaded = newest_ledger(case["ticker"])
        if loaded is None:
            print(f"skip {case['id']}: no report yet for {case['ticker']}")
            continue
        ledger, company, report = loaded
        session_id = f"{args.tag}-{case['id']}"
        try:
            ans = chat.answer(case["question"], ledger, company, session_id=session_id,
                              checks=(args.tag == "after"))
        except Exception as exc:  # noqa: BLE001 - a crash is a failed case, not a stack trace
            rows.append({"id": case["id"], "question": case["question"], "reply": "",
                         "verdict": "fail", "reasons": [f"error: {type(exc).__name__}"],
                         "session_id": session_id, "report": report})
            continue
        reasons = judge(case, ans, ledger, args.tag)
        rows.append({"id": case["id"], "question": case["question"], "reply": ans.text,
                     "kind": ans.kind, "citations": len(ans.citations), "withheld": ans.withheld,
                     "verdict": "fail" if reasons else "pass", "reasons": reasons,
                     "session_id": session_id, "report": report})

    out_dir = REPO / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{args.tag}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                              encoding="utf-8")
    print(f"{'case':<20} {'verdict':<8} reasons")
    for r in rows:
        print(f"{r['id']:<20} {r['verdict']:<8} {'; '.join(r['reasons'])[:100]}")
    passed = sum(r["verdict"] == "pass" for r in rows)
    print(f"\n{args.tag}: {passed}/{len(rows)} passed, {len(cases) - len(rows)} skipped "
          f"-> results/{args.tag}.json")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
