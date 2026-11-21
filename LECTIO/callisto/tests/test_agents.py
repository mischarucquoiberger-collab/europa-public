"""Model agents: all model calls are faked; no Nicrron call is made."""
import json

import pytest

from backend import agents


class _Msg:
    def __init__(self, content):
        self.content = content


class _Fake:
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages, config=None):
        if isinstance(self.reply, Exception):
            raise self.reply
        return _Msg(self.reply)


def _patch(monkeypatch, replies: dict, default=RuntimeError("no model")):
    """replies: model name -> text or Exception. Records the names called."""
    calls = []

    def model(name=None):
        calls.append(name)
        return _Fake(replies.get(name, default))

    monkeypatch.setattr(agents.llm, "model", model)
    return calls


def test_call_json_falls_back_to_second_model(monkeypatch):
    calls = _patch(monkeypatch, {"a": RuntimeError("down"), "b": 'noise {"x": 1} then {"x": 2}'})
    obj, name = agents.call_json(["a", "b"], "sys", "hi", None)
    assert (obj, name) == ({"x": 2}, "b")
    assert calls == ["a", "b"]


def test_call_json_need_key_and_all_fail(monkeypatch):
    _patch(monkeypatch, {"a": '{"y": 1}', "b": "not json"})
    assert agents.call_json(["a", "b"], "s", "h", None, need_key="x") == (None, None)
    _patch(monkeypatch, {})
    assert agents.call_json(["a", "b"], "s", "h", None) == (None, None)


def test_route_honours_model_and_drops_unknown(monkeypatch):
    first = agents.ROUTER_MODELS[0]
    _patch(monkeypatch, {first: json.dumps({"specialists": ["market", "weather", "news"], "advice": False,
                                            "reason": "price"})})
    r = agents.route({"ticker": "AAPL", "question": "q"}, None)
    assert r["specialists"] == ["market", "news"] and r["advice"] is False
    assert r["model"] == first and r["fallback"] is False


def test_route_empty_and_advice(monkeypatch):
    first = agents.ROUTER_MODELS[0]
    _patch(monkeypatch, {first: '{"specialists": ["bogus"], "advice": true, "reason": "buy?"}'})
    r = agents.route({"ticker": "AAPL", "question": "q"}, None)
    assert r["specialists"] == ["filings"] and r["advice"] is True


def test_route_failure_uses_keywords(monkeypatch):
    _patch(monkeypatch, {})
    r = agents.route({"ticker": "AAPL", "question": "What was the closing stock price?"}, None)
    assert r["fallback"] is True and r["advice"] is False and r["model"] is None
    assert "market" in r["specialists"]


def test_route_by_keywords():
    assert "market" in agents.route_by_keywords("What was the closing stock price?")
    assert agents.route_by_keywords("latest headlines") == ["news"]
    assert agents.route_by_keywords("What were net sales?") == ["filings"]
    assert agents.route_by_keywords("tell me something") == ["filings"]


ITEMS = [{"id": f"id{n}", "title": f"T{n}", "publisher": "P", "published_utc": "2026-11-20T10:00:00Z",
          "url": f"https://example.com/{n}"} for n in range(1, 7)]


def test_pick_news_maps_ids_and_drops_unknown(monkeypatch):
    first = agents.NEWS_MODELS[0]
    _patch(monkeypatch, {first: '{"ids": ["N5", "N99", "zzz", "N2", "N1", "N3"]}'})
    r = agents.pick_news({"question": "q", "items": ITEMS}, None)
    assert r["ids"] == ["id5", "id2", "id1"] and r["model"] == first


def test_pick_news_failure_and_small_lists(monkeypatch):
    calls = _patch(monkeypatch, {})
    assert agents.pick_news({"question": "q", "items": ITEMS}, None)["ids"] == ["id1", "id2", "id3"]
    calls.clear()
    r = agents.pick_news({"question": "q", "items": ITEMS[:2]}, None)
    assert r == {"ids": ["id1", "id2"], "model": None} and calls == []


def test_write_garbage_is_i_dont_know(monkeypatch):
    _patch(monkeypatch, {m: "I am not JSON at all" for m in agents.WRITER_MODELS})
    r = agents.write({"ticker": "AAPL", "company": "Apple Inc.", "question": "q", "sheets": ["S"],
                      "unavailable": [], "has_news": False}, None)
    assert r["draft"]["status"] == "I_DONT_KNOW" and r["draft"]["claims"] == [] and r["model"] is None


def test_write_parses_draft(monkeypatch):
    _patch(monkeypatch, {agents.WRITER_MODELS[0]: json.dumps(
        {"status": "ANSWERED", "answer": "Revenue was $478.8 billion.",
         "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}]})})
    r = agents.write({"ticker": "AAPL", "question": "q", "sheets": ["S"], "unavailable": [{"agent": "market",
                      "reason": "MASSIVE_API_KEY is not set"}], "has_news": True}, None)
    assert r["draft"]["status"] == "ANSWERED" and r["draft"]["claims"][0]["fact_id"] == "revenue_fy2026"


def test_review_drops_bad_index_and_verdict(monkeypatch):
    _patch(monkeypatch, {agents.SKEPTIC_MODELS[0]: json.dumps({"verdicts": [
        {"i": 1, "verdict": "SUPPORTED", "why": ""}, {"i": 7, "verdict": "UNSUPPORTED", "why": "x"},
        {"i": 2, "verdict": "maybe", "why": ""}, {"i": "2", "verdict": "advice", "why": "buy"}]})})
    r = agents.review({"question": "q", "sheets": ["S"], "sentences": ["One.", "Two."]}, None)
    assert r["status"] == "ok"
    assert [(v["i"], v["verdict"]) for v in r["verdicts"]] == [(1, "SUPPORTED"), (2, "ADVICE")]


def test_review_failure_is_unavailable(monkeypatch):
    _patch(monkeypatch, {})
    r = agents.review({"question": "q", "sheets": ["S"], "sentences": ["One."]}, None)
    assert r == {"status": "unavailable", "verdicts": [], "model": None}


def test_runnable_names():
    assert agents.ROUTER.name == "desk_router" and agents.NEWS_PICKER.name == "news_picker"
    assert agents.WRITER.name == "write_answer" and agents.SKEPTIC.name == "skeptic_review"
