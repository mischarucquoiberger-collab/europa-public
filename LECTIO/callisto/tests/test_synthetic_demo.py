"""SYNTHETIC wrong-number demo (scripts/demo_synthetic_wrong_number.py), written before the script (2026-11-21).

Pass rule: the real desk runs with only the writer swapped for a labeled synthetic one that states
FY2026 net sales as $512.4 billion (real: $478.8 billion) next to a correct FY2025 sentence ($416.2 billion).
- checker OFF: the wrong number reaches the answer (the BEFORE problem).
- checker ON:  the real number_gate cuts the wrong sentence as MISMATCH and keeps the correct one,
               even when the skeptic says everything is SUPPORTED (so the code gate alone catches it).
Router and skeptic are stubbed so the test needs no model or network.
"""
import importlib.util
from pathlib import Path

from langchain_core.runnables import RunnableLambda

_p = Path(__file__).resolve().parents[1] / "scripts" / "demo_synthetic_wrong_number.py"
_spec = importlib.util.spec_from_file_location("demo_synthetic_wrong_number", _p)
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

ROUTER = RunnableLambda(lambda i: {"specialists": ["filings"], "advice": False, "reason": "", "model": "stub",
                                   "fallback": False}, name="desk_router")
SKEPTIC_OK = RunnableLambda(lambda i: {"status": "ok", "model": "stub",
                                       "verdicts": [{"i": n, "verdict": "SUPPORTED", "why": ""}
                                                    for n in range(1, len(i["sentences"]) + 1)]},
                            name="skeptic_review")


def _run(monkeypatch, checker):
    monkeypatch.setenv("EUROPA_CHECKER", checker)
    monkeypatch.setenv("EUROPA_PIPELINE", "multi")
    return demo.run(deps=demo.demo_deps(router=ROUTER, skeptic=SKEPTIC_OK))


def test_label_is_synthetic():
    assert "SYNTHETIC" in demo.QUESTION
    assert "SYNTHETIC" in demo.WRITER.name


def test_checker_off_lets_wrong_number_through(monkeypatch):
    out = _run(monkeypatch, "off")
    assert "$512.4 billion" in out["answer"]


def test_checker_on_blocks_wrong_number_keeps_right_one(monkeypatch):
    out = _run(monkeypatch, "on")
    assert "512.4" not in out["answer"]
    assert "$416.2 billion" in out["answer"]
    cut = [b for b in out["blocked"] if "512.4" in str(b.get("text"))]
    assert cut and cut[0]["status"] == "BLOCKED"  # sentence-level label; the claim below carries the reason
    bad = [c for c in out["claims"] if "512.4" in str(c.get("text"))]
    assert bad and bad[0]["status"] in ("MISMATCH", "NOT_FOUND")
    assert any(r["name"] == "number_gate" for r in out["agents"])
