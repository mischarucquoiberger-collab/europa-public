"""Offline regression check for the number gate: the red-team B and stress-test B cases, with the outcome each SHOULD have.

Run from what-changed/:  .venv/bin/python scripts/gate_regressions_B.py        (no model calls, no credits, no PRISM)
Each case goes through gate.final_check with no skeptic verdicts, so this shows what CODE alone does.
  want "block": the sentence is wrong and must not be shown.   want "pass": the sentence is true and must be shown whole.
Result OK = the gate did what it should. HOLE = a wrong sentence was shown. OVERCUT = a true sentence was cut.
Market cases use made-up values, labelled SYNTHETIC. Written by Account B (Claude), 2026-11-21. Changes nothing.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "gate-regressions-B")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.gate import final_check  # noqa: E402


def _m(v, k, d="2026-11-20"):
    return {"label": "SYNTHETIC", "value": v, "kind": k, "source": "SYNTHETIC", "as_of": d, "provider": "massive"}


MARKET = {"agent": "market", "status": "ok", "as_of": "2026-11-20", "allow_dates": ["2026-11-20"], "facts": {
    "px_close_last": _m(229.87, "usd_per_share"), "px_close_prior": _m(226.10, "usd_per_share", "2026-11-19"),
    "ret_1d_pct": _m(1.67, "pct"), "ret_1m_pct": _m(-3.22, "pct"), "ret_ytd_pct": _m(12.4, "pct"),
    "ret_1y_pct": _m(21.3, "pct")}}
DISPUTE_FY25 = {"agent": "council", "status": "unavailable", "exclude": ["revenue_fy2025"]}
GM = [{"value": "48.8%", "fact_id": "gross_margin_pct_fy2026"}, {"value": "46.9%", "fact_id": "gross_margin_pct_fy2025"},
      {"value": "1.9 percentage points", "fact_id": "gross_margin_pct_change_pts"}]
REV = [{"value": "$62.7 billion", "fact_id": "revenue_change_amount"}, {"value": "$416.2 billion", "fact_id": "revenue_fy2025"},
       {"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]

# (group, want, sentence, packs, claims)
CASES = [
    # --- wrong direction on a right number (red-team 1)
    ("direction", "block", "Apple revenue saw a 15.1% year-over-year decline in fiscal 2026.", [], []),
    ("direction", "block", "Apple net sales had a 15.1% annual drop.", [], []),
    ("direction", "block", "Revenue eroded 15.1% in fiscal 2026.", [], []),
    ("direction", "block", "Revenue cratered 15.1% in fiscal 2026.", [], []),
    ("direction", "block", "Revenue was off 15.1% from the year before.", [], []),
    ("direction", "block", "Revenue collapsed 15.1%.", [], []),
    ("direction", "block", "Net income deteriorated 18.0% in fiscal 2026.", [], []),
    ("direction", "block", "Revenue posted a $62.7 billion year-over-year decline.", [], []),
    ("direction", "block", "Revenue of $478.8 billion in fiscal 2026 was lower than the year before.", [], []),
    ("direction", "block", "Revenue fell to $478.8 billion in fiscal 2026.", [], []),
    ("direction", "block", "Revenue fell to $478.8 billion in fiscal 2026.", [DISPUTE_FY25], []),  # red-team 4
    ("direction", "block", "Buybacks had a 4.8% year-over-year increase.", [], []),
    ("direction", "pass", "Revenue rose 15.1% in fiscal 2026.", [], []),
    ("direction", "pass", "Apple spent less on buybacks: $86.4 billion in fiscal 2026, down from $90.7 billion in fiscal 2025, a decrease of 4.8%.", [], []),
    ("direction", "pass", "Apple's revenue did not fall. Net sales rose 15.1% in fiscal 2026.", [], []),
    ("direction", "pass", "No. Net income was $132.2 billion in fiscal 2026 versus $112.0 billion in fiscal 2025, so it increased rather than dropped.", [], []),
    # --- years (red-team 3, 8)
    ("year", "block", "EPS was $7.46, compared with $8.98 the year before.", [], []),
    ("year", "block", "Revenue was $416.2 billion, versus $478.8 billion a year earlier.", [], []),
    ("year", "block", "Fiscal 2026 was a record year. Revenue was $416.2 billion.", [], []),
    ("year", "block", "In fiscal 2026, revenue was $416.2 billion.", [], []),
    ("year", "block", "Revenue rose 15.1% in fiscal 2025.", [], []),
    ("year", "block", "Revenue rose 15.1% to $416.2 billion in fiscal 2025.", [], []),
    ("year", "pass", "Diluted EPS was $8.98 in fiscal 2026, up from $7.46 in fiscal 2025.", [], []),
    ("year", "pass", "EPS was $8.98, compared with $7.46 the year before.", [], []),
    # --- right number, wrong thing (red-team 6, 7)
    ("binding", "block", "Apple paid a dividend of $8.98 per share in fiscal 2026.", [], []),
    ("binding", "block", "Revenue in Q4 of fiscal 2026 was $478.8 billion.", [], []),
    ("binding", "block", "Operating margin was 48.8% in fiscal 2026.", [], []),
    ("binding", "block", "iPhone revenue was $478.8 billion in fiscal 2026.", [], []),
    ("binding", "block", "Microsoft revenue was $478.8 billion in fiscal 2026.", [], []),
    ("binding", "block", "Apple total debt was $86.4 billion.", [], []),
    ("binding", "block", "Gross margin percentage rose 19.7% in fiscal 2026.", [], []),
    ("binding", "block", "Apple lost $132.2 billion in fiscal 2026.", [], []),
    ("binding", "block", "Net income was a negative $132.2 billion in fiscal 2026.", [], []),
    ("binding", "block", "EPS was -$8.98.", [], []),
    ("binding", "pass", "Apple did not lose money in fiscal 2026. The company reported net income of $132.2 billion.", [], []),
    # --- sizes in words (red-team 9)
    ("words", "block", "Revenue grew by a quarter in fiscal 2026.", [], []),
    ("words", "block", "Revenue grew at a single-digit rate in fiscal 2026.", [], []),
    ("words", "block", "Revenue quintupled in fiscal 2026.", [], []),
    ("words", "block", "Revenue grew fifteen-percent.", [], []),
    ("words", "pass", "Revenue grew at a double-digit rate.", [], []),
    # --- quotes
    ("quote", "block", "Apple 10-K says 'we expect revenue to decline sharply next year'.", [], []),
    ("quote", "block", "Apple 10-K says \"we expect revenue to decline sharply next year\".", [], []),
    # --- true sentences the live stress test saw cut (stress 3, 4)
    ("overcut", "pass", "That is 48.8% of net sales.", [], []),
    ("overcut", "pass", "That is 48.8% of net sales.", [], GM),
    ("overcut", "pass", "It was 48.8% of net sales, compared with 46.9% in fiscal 2025, a change of +1.9 percentage points.", [], GM),
    ("overcut", "pass", "Apple kept 48.8% of each sales dollar after the cost of making its products.", [], GM),
    ("overcut", "pass", "Gross margin was 48.8% of net sales in fiscal 2026.", [], GM),
    ("overcut", "pass", "Apple's net sales increased by $62.7 billion between fiscal 2025 and fiscal 2026, rising from $416.2 billion to $478.8 billion.", [], []),
    ("overcut", "pass", "Apple's net sales increased by $62.7 billion between fiscal 2025 and fiscal 2026, rising from $416.2 billion to $478.8 billion.", [], REV),
    ("overcut", "pass", "Apple's net income increased by $20.2 billion between fiscal 2025 and fiscal 2026, rising from $112.0 billion to $132.2 billion.", [], []),
    # --- a correction that repeats the user's wrong number (stress 1, 2): today the whole sentence is cut
    ("correction", "pass", "No. Diluted EPS was $8.98 per share in fiscal 2026.", [], []),
    ("correction", "block", "Diluted EPS in fiscal 2026 was $8.98 per share, not $9.50.", [], []),  # $9.50 is no fact: cut is the safe result
    # --- wrong value, any format (must stay blocked)
    ("value", "block", "Revenue was $512.4 billion in fiscal 2026.", [], []),
    ("value", "block", "Revenue was $512.4bn in fiscal 2026.", [], []),
    ("value", "block", "Revenue was about 512 billion.", [], []),
    ("value", "block", "Gross margin rose 1.9% in fiscal 2026.", [], []),
    ("value", "block", "Revenue was $478.8 billion, up 25%.", [], []),
    # --- market, SYNTHETIC values (red-team 10)
    ("market", "block", "Apple closed at $226.10, down from $229.87 the day before.", [MARKET], []),
    ("market", "block", "Over the last two years the stock returned 21.3%.", [MARKET], []),
    ("market", "block", "The stock had a 1.7% one-day slide.", [MARKET], []),
    ("market", "block", "A month ago the stock closed at $229.87.", [MARKET], []),
    ("market", "block", "The stock closed at $229.87 on November 19, 2026.", [MARKET], []),
    ("market", "pass", "Apple closed at $229.87 on 2026-11-20, up from $226.10 the day before.", [MARKET], []),
    ("market", "pass", "Over the past month the stock fell 3.2%.", [MARKET], []),
    ("market", "pass", "The last close, on 2026-11-20, was $229.87, up 1.7% on the day.", [MARKET], []),
]


def main() -> int:
    rows, tally = [], {}
    for group, want, text, packs, claims in CASES:
        r = final_check("AAPL", {"status": "ANSWERED", "answer": text, "claims": claims}, packs)
        shown_whole = r["status"] == "ANSWERED" and r["answer"].strip() == text.strip()
        got = "pass" if shown_whole else ("block" if r["status"] != "ANSWERED" else "partial")
        if got == want:
            res = "OK"
        elif want == "block":
            res = "HOLE"
        else:
            res = "OVERCUT"
        tally[res] = tally.get(res, 0) + 1
        why = "; ".join(f"{c.get('text')}: {c.get('status')}" for c in r["claims"] if c.get("status") != "VERIFIED")[:90]
        rows.append((res, group, want, ("+claims " if claims else "") + ("+pack " if packs else "") + text, why))
    for res, group, want, text, why in rows:
        print(f"{res:8}| {group:10}| want {want:5}| {text[:150]}" + (f"   [{why}]" if why and res != "OK" else ""))
    print(f"\n{len(rows)} cases: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
