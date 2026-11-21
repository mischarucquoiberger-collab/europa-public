"""Smoke test: send one small traced run to PRISM (a tool step + a Nicrron model step).

Run:  python -m backend.smoke_trace
Then open PRISM → Developers → SDK setup → Check now. This is a SETUP CHECK, not the product.
"""
import uuid

from langchain_core.tools import tool

from backend import tracing
from backend.llm import chat


@tool
def get_filing_periods(ticker: str) -> str:
    """Return the two filing periods to compare (setup check: fixed values)."""
    return f"{ticker}: 10-K period ending 2026-09-26 vs 10-K period ending 2025-09-27"


def main():
    if tracing.handler is None:
        print("PRISM tracing is OFF: add PRISMTRACE_HOST, PRISMTRACE_PROJECT_ID, PRISMTRACE_API_KEY to .env")
        return
    sid = f"setup-check-{uuid.uuid4().hex[:8]}"
    with tracing.session(sid):
        periods = get_filing_periods.invoke({"ticker": "AAPL"}, config={"callbacks": tracing.callbacks()})
        answer = chat(f"In one short sentence, say which two periods will be compared: {periods}")
    tracing.close()  # flush
    print("session:", sid)
    print("model said:", answer)


if __name__ == "__main__":
    main()
