"""SYNTHETIC DEMO: show the number checker catching a wrong number. Not a real answer, not real data.

The real Callisto desk runs (guard, router, SEC filings specialist, skeptic, number_gate, notices).
Only the writer is swapped for a labeled synthetic one that states Apple's FY2026 net sales as
$512.4 billion on purpose (the SEC 10-K says $478.8 billion), next to one correct sentence.
  checker OFF -> the wrong number is shown (the problem Europa exists to stop)
  checker ON  -> number_gate cuts it as a mismatch against the SEC value and keeps the correct sentence
Every run is traced to PRISM like a normal question; the question and the writer step both say SYNTHETIC.

Usage: .venv/bin/python scripts/demo_synthetic_wrong_number.py [off|on|both]   (default: both)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langchain_core.runnables import RunnableLambda  # noqa: E402

from backend import desk  # noqa: E402

TICKER = "AAPL"
QUESTION = ("[SYNTHETIC DEMO: the writer is replaced by one that states a wrong number on purpose] "
            "What were Apple's net sales in fiscal 2026 and fiscal 2025?")
WRONG = "$512.4 billion"  # synthetic; the real SEC value is $478.8 billion
DRAFT = {
    "status": "ANSWERED",
    "answer": (f"Apple's net sales in fiscal 2026 were {WRONG}. "
               "Apple's net sales in fiscal 2025 were $416.2 billion."),
    "claims": [{"value": WRONG, "fact_id": "revenue_fy2026"},
               {"value": "$416.2 billion", "fact_id": "revenue_fy2025"}],
}


def _synthetic_writer(inp: dict) -> dict:
    return {"draft": json.loads(json.dumps(DRAFT)), "model": "SYNTHETIC-writer (no model, wrong number on purpose)"}


WRITER = RunnableLambda(_synthetic_writer, name="write_answer_SYNTHETIC_wrong_number")


def demo_deps(router=None, skeptic=None) -> desk.Deps:
    """Real desk parts, synthetic writer. router/skeptic can be stubbed (tests)."""
    d = desk.default_deps()
    d.writer = WRITER
    if router is not None:
        d.router = router
    if skeptic is not None:
        d.skeptic = skeptic
    return d


def run(deps: desk.Deps | None = None) -> dict:
    return desk.answer(TICKER, QUESTION, deps=deps or demo_deps())


def _show(mode: str) -> dict:
    os.environ["EUROPA_CHECKER"] = mode
    os.environ["EUROPA_PIPELINE"] = "multi"
    out = run()
    print(f"\n=== SYNTHETIC DEMO, checker {mode.upper()} ===")
    print("answer :", out["answer"])
    for b in out.get("blocked") or []:
        print("blocked:", b.get("status"), "|", b.get("text"), "|", b.get("note"))
    print("steps  :", " > ".join(r["name"] for r in out.get("agents") or []))
    print("PRISM session:", out.get("prism_session_id"))
    return out


if __name__ == "__main__":
    arg = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    for m in (["off", "on"] if arg == "both" else [arg]):
        _show(m)
    from backend import tracing
    tracing.close()  # flush traces to PRISM
