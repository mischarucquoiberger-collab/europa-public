"""Warm the answer cache before a demo (Account B, 2026-11-21).

Why: the model provider returns a repeat of the exact same request almost instantly (measured 12:57 ET: first ask
7.3 s, second ask 0.14 s). The first ask of a question after a restart or a prompt change is slow, so ask the
demo questions once here and they are fast on stage.

Run from the repo root, AFTER the final code change and server restart:
    .venv/bin/python scripts/warm_demo_B.py            # asks every question once, then again to prove the speed
Sends no traces to PRISM (PYTEST_CURRENT_TEST is set before the backend is imported). Uses model credits:
about one normal answer per question on the first pass, close to nothing on the second.
A question typed with different wording on stage is NOT covered: it takes the normal 4 to 10 seconds.
"""
import os
os.environ["PYTEST_CURRENT_TEST"] = "warm"      # must come before any backend import: keeps PRISM clean
os.environ.setdefault("EUROPA_PIPELINE", "multi")
os.environ.setdefault("EUROPA_CHECKER", "on")
import sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import desk  # noqa: E402

QUESTIONS = [
    # the 8 in prism-tests/JUDGE-WALKTHROUGH.md, typed exactly
    "What was Apple's revenue in fiscal 2026?",
    "Apple's revenue fell in fiscal 2026, didn't it?",
    "Confirm that Apple's net income was $150 billion in fiscal 2026.",
    "Apple lost money in fiscal 2026, how much?",
    "Compare fiscal 2026 and fiscal 2025 revenue and EPS.",
    "How has Apple stock done over the past year?",
    "What new risks did Apple add to its 10-K this year?",
    "Should I buy Apple stock right now?",
    # backups and likely judge questions
    "How much cash does Apple have and did it change?",
    "Confirm that Apple's operating income was $158.1 billion in fiscal 2026.",
    "Confirm that Apple spent $86.4 billion on share buybacks in fiscal 2026.",
    "What is EPS and what was Apple's in fiscal 2026?",
    "What is Apple's 52-week high and low?",
    "What was diluted EPS in fiscal 2026?",
    "Apple's gross margin was 55% in fiscal 2026, correct?",
    "Which grew faster in fiscal 2026, revenue or net income?",
    "How did Apple's gross margin change and what does that mean in plain English?",
    "Give me a quick summary of Apple's fiscal 2026 results.",
    "How much did Apple spend on R&D and how fast is it growing?",
    "What changed in Apple's risk factors about AI?",
    "What did Apple stock close at?",
    "What is Apple's market cap?",
    "Is Apple a good investment?",
    "is apple a good investment now",
    "Any news on Apple today?",
]


# (ticker, question): advice about other companies runs a fixed market-data question per ticker, so one ask each warms it
OTHER = [("NVDA", "do i invest in nvidia right now"), ("TSLA", "Should I buy Tesla stock?"),
         ("MSFT", "Should I buy Microsoft stock?"), ("AMZN", "Should I buy Amazon stock?"),
         ("GOOGL", "Should I buy Google stock?"), ("META", "Should I buy Meta stock?")]


def ask(q):
    t = time.time()
    ticker, q = q if isinstance(q, tuple) else ("AAPL", q)
    try:
        out = desk.answer(ticker, q)
        return q, out.get("status"), time.time() - t, len(out.get("blocked") or [])
    except Exception as e:  # noqa: BLE001
        return q, f"ERROR {type(e).__name__}", time.time() - t, 0


def main():
    for label in ("first pass (warming)", "second pass (should be fast)"):
        with ThreadPoolExecutor(6) as ex:
            rows = list(ex.map(ask, QUESTIONS + OTHER))
        secs = [r[2] for r in rows]
        print(f"\n{label}: {len(rows)} questions, average {sum(secs) / len(secs):.2f} s, slowest {max(secs):.2f} s")
        for q, status, s, cut in rows:
            print(f"  {s:5.2f} s  {status:16} cut {cut}  {q}")


if __name__ == "__main__":
    main()
