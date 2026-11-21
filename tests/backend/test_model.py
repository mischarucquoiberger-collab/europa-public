"""backend.model: the gate, the retries and the JSON reading (offline: llm.call_llm is faked)."""
import threading

import pytest

import llm
from backend import model, settings


def test_gate_never_lets_more_than_model_concurrency_calls_overlap(monkeypatch):
    cap = settings.MODEL_CONCURRENCY
    lock = threading.Lock()
    state = {"active": 0, "max": 0, "calls": 0}
    # every call waits until `cap` calls are inside together: proves the gate lets `cap` in,
    # and a broken gate would let a further call in (counted) before the first round leaves
    barrier = threading.Barrier(cap, timeout=5)

    def fake(messages, *, session_id, **params):
        with lock:
            state["active"] += 1
            state["calls"] += 1
            state["max"] = max(state["max"], state["active"])
        try:
            barrier.wait()
        finally:
            with lock:
                state["active"] -= 1
        return "ok"
    monkeypatch.setattr(llm, "call_llm", fake)

    results, errors = [], []

    def worker():
        try:
            results.append(model.ask([{"role": "user", "content": "x"}], session_id="s", sleep=lambda s: None))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(cap * 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors and results == ["ok"] * (cap * 2)
    assert state["max"] == cap and state["calls"] == cap * 2


def test_429_then_success_is_retried_with_the_injected_sleep(monkeypatch):
    calls, pauses = [], []

    def fake(messages, *, session_id, **params):
        calls.append(params)
        if len(calls) == 1:
            raise llm.LLMError("Nicrron answered HTTP 429")
        return "fine"
    monkeypatch.setattr(llm, "call_llm", fake)
    assert model.ask([], session_id="s", sleep=pauses.append, temperature=0) == "fine"
    assert pauses == [2.0] and len(calls) == 2 and calls[0] == {"temperature": 0}


def test_retryable_failures_retry_twice_then_raise(monkeypatch):
    pauses, calls = [], []

    def fake(messages, *, session_id, **params):
        calls.append(1)
        raise llm.LLMError("Nicrron unreachable (URLError)" if len(calls) == 1 else "Nicrron answered HTTP 503")
    monkeypatch.setattr(llm, "call_llm", fake)
    with pytest.raises(llm.LLMError, match="HTTP 503"):
        model.ask([], session_id="s", sleep=pauses.append)
    assert pauses == [2.0, 5.0] and len(calls) == 3


def test_non_retryable_error_is_raised_at_once(monkeypatch):
    pauses, calls = [], []

    def fake(messages, *, session_id, **params):
        calls.append(1)
        raise llm.LLMError("Nicrron answered HTTP 400")
    monkeypatch.setattr(llm, "call_llm", fake)
    with pytest.raises(llm.LLMError, match="HTTP 400"):
        model.ask([], session_id="s", sleep=pauses.append)
    assert pauses == [] and calls == [1]


def test_gate_is_released_after_failures(monkeypatch):
    def fake(messages, *, session_id, **params):
        raise llm.LLMError("NICRRON_API_KEY is not set. Put it in .env.")
    monkeypatch.setattr(llm, "call_llm", fake)
    for _ in range(settings.MODEL_CONCURRENCY + 2):
        with pytest.raises(llm.LLMError):
            model.ask([], session_id="s", sleep=lambda s: None)
    monkeypatch.setattr(llm, "call_llm", lambda messages, *, session_id, **p: None)
    assert model.ask([], session_id="s") == ""      # still callable, and None becomes ""


@pytest.mark.parametrize("reply, expected", [
    ('```json\n[{"n": 1, "ok": true}]\n```', [{"n": 1, "ok": True}]),
    ('Here are the verdicts:\n[{"n": 1, "ok": false, "why": "says [rose]"}]\nThat is all.',
     [{"n": 1, "ok": False, "why": "says [rose]"}]),
    ('{"verdicts": [{"n": 2, "ok": true}]}', {"verdicts": [{"n": 2, "ok": True}]}),
    ("Sentence [1] is fine. [{\"n\": 1, \"ok\": true}]", [1]),      # the FIRST balanced one
    ("I cannot judge these sentences.", None),
    ("[{n: 1, ok: true}", None),
    ("", None),
    ("42", None),
])
def test_ask_json_reads_defensively(monkeypatch, reply, expected):
    monkeypatch.setattr(llm, "call_llm", lambda messages, *, session_id, **p: reply)
    assert model.ask_json([], session_id="s", sleep=lambda s: None) == expected
