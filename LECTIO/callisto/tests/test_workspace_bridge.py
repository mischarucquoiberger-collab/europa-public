"""The workspace bridge (backend/workspace_bridge.py): the Callisto page's chat client protocol, with a fake desk
and fake Massive bars (no network, no model)."""
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import workspace_bridge as wb

NVDA = {
    "status": "ANSWERED", "ticker": "NVDA", "company": "NVIDIA Corporation",
    "answer": "NVIDIA shares rose over the past year.\n• Last close $180.25.\n• Past year +35.2%.\n"
              "What it means: the move came with strong demand.",
    "claims": [{"text": "$180.25", "status": "VERIFIED", "provider": "massive"}],
    "agents": [{"name": "guard_advice", "status": "ok"}, {"name": "desk_router", "status": "ok"},
               {"name": "specialist_market", "status": "ok"}],
    "stats": [{"label": "Price", "value": "$180.25"}],
    "charts": [{"type": "line", "unit": "usd_price", "points": [{"x": "2025-11-21", "y": 133.0},
                                                                {"x": "2026-11-20", "y": 180.25}]}],
    "followups": ["How has NVIDIA done this year?", "Bear case for NVIDIA"],
    "data_note": "Market data: Massive end-of-day.", "disclaimer": "Research aid, not investment advice.",
    "seconds": 4.2,
}
BARS = [{"date": f"2026-{m:02d}-{d:02d}", "c": 100.0 + m + d / 100} for m in range(1, 12) for d in (3, 10, 17, 24)]


@pytest.fixture
def client(monkeypatch):
    seen = []

    def desk(question, ticker, last):
        seen.append((question, ticker, last))
        if question.lower() == "hi":
            return {"status": "CHAT", "kind": "greeting", "answer": "Hi! Ask me about a US stock.", "claims": []}
        if "apple" in question.lower():
            return {**NVDA, "ticker": "AAPL", "company": "Apple Inc."}
        return dict(NVDA)

    monkeypatch.setattr(wb, "desk_fn", desk)
    monkeypatch.setattr(wb, "bars_fn", lambda t: list(BARS))
    monkeypatch.setattr(wb, "resolve_fn", lambda q, t, last: "" if q.lower() == "hi" else t)
    wb._convos.clear()
    wb._jobs.clear()
    app = FastAPI()
    app.include_router(wb.router)
    c = TestClient(app)
    c.seen = seen
    return c


def ask(client, text, conv=None, msg="m1"):
    body = {"text": text, "messageId": msg, "parentMessageId": "00000000-0000-0000-0000-000000000000",
            "conversationId": conv, "endpoint": "Indago", "model": "indago-query"}
    start = client.post("/xyz/api/agents/chat/Indago", json=body)
    assert start.status_code == 200
    sid = start.json()["streamId"]
    assert "generationProtocolVersion" not in start.json()          # protocol 1: no status check at the end
    r = client.get(f"/xyz/api/agents/chat/stream/{sid}")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"].startswith("no-cache")
    frames = []
    for block in r.text.split("\n\n"):
        if block.strip():
            assert block.startswith("event: message\ndata: ")
            frames.append(json.loads(block.split("data: ", 1)[1]))
    return sid, frames


def test_framing_created_steps_final(client):
    sid, frames = ask(client, "How has Nvidia done over the past year?")
    assert frames[0]["created"] is True and frames[0]["message"]["text"].startswith("How has Nvidia")
    assert frames[-1]["final"] is True
    final = frames[-1]
    assert final["conversation"]["conversationId"] == sid
    assert final["requestMessage"]["messageId"] == "m1"
    resp = final["responseMessage"]
    assert resp["parentMessageId"] == "m1" and resp["endpoint"] == "Indago" and resp["isCreatedByUser"] is False
    kinds = [p["type"] for p in resp["content"]]
    assert kinds == ["think", "text"]
    assert "✓ Company lookup ⟨NVDA⟩: NVIDIA Corporation" in resp["content"][0]["think"]
    events = [f.get("event") for f in frames[1:-1]]
    assert "on_run_step" in events and "on_message_delta" in events and "on_reasoning_delta" in events
    streamed = "".join(f["data"]["delta"]["content"][0]["text"] for f in frames if f.get("event") == "on_message_delta")
    assert streamed == resp["text"] == resp["content"][1]["text"]
    assert client.get(f"/xyz/api/agents/chat/stream/{sid}").status_code == 404      # a finished stream is gone


def test_price_card_and_chips_directive(client):
    _, frames = ask(client, "How has Nvidia done over the past year?")
    text = frames[-1]["responseMessage"]["text"]
    head = text.split("\n", 1)[0]
    assert head.startswith("::indago-query-head{") and head.endswith("}")
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', head))
    assert attrs["code"] == attrs["pcode"] == "NVDA"
    assert attrs["price"] == "111.24" and attrs["prev"] == "111.17"              # last two Massive closes
    assert attrs["state"] == "CLOSED" and attrs["asof"] == "2026-11-24 close · ET"
    hist = attrs["hist"].split(",")
    assert 2 <= len(hist) <= 40 and hist[-1] == "261124:111.24"
    assert attrs["t1"].startswith("lookup_company|NVDA|NVIDIA Corporation")
    assert attrs["t2"].startswith("get_stock_prices|NVDA|")
    assert "::indago-query{" in text and 'f1="How has NVIDIA done this year?"' in text


def test_no_numbers_invented(client):
    _, frames = ask(client, "How has Nvidia done over the past year?")
    text = frames[-1]["responseMessage"]["text"]
    allowed = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(NVDA) + json.dumps(BARS)))
    body = re.sub(r"::indago-query-head\{[^}]*\}", "", text)                    # card figures: checked above
    body = re.sub(r'\b(tools|sources|landed|deep|v)="\d+"', "", body)         # counts of look-ups, not figures
    body = re.sub(r"\bf[123]=", "", body)                                      # follow-up slot names
    for n in re.findall(r"\d+(?:\.\d+)?", body):
        assert n in allowed, n
    assert "- Last close $180.25." in text and "**What it means:**" in text


def test_no_card_without_bars(client, monkeypatch):
    def boom(t):
        raise RuntimeError("no data")
    monkeypatch.setattr(wb, "bars_fn", boom)
    _, frames = ask(client, "How has Nvidia done over the past year?")
    head = frames[-1]["responseMessage"]["text"].split("\n", 1)[0]
    assert 'price="' not in head and "t1=" in head                             # chips, no card, no price


def test_chat_reply_plain(client):
    _, frames = ask(client, "hi")
    resp = frames[-1]["responseMessage"]
    assert [p["type"] for p in resp["content"]] == ["text"]
    assert resp["text"] == "Hi! Ask me about a US stock."


def test_conversation_memory(client):
    sid, _ = ask(client, "How has Nvidia done over the past year?")
    ask(client, "and Apple?", conv=sid, msg="m2")
    assert client.seen[0] == ("How has Nvidia done over the past year?", "AAPL", "")
    assert client.seen[1] == ("and Apple?", "NVDA", "How has Nvidia done over the past year?")
    assert wb.conversation_state(sid)["ticker"] == "AAPL"


def test_progress_lines_follow_desk_rows():
    assert wb.progress_line({"name": "desk_router", "note": "picked market, news"}, "NVDA") == [
        "✓ Company lookup ⟨NVDA⟩", "Looking up Stock prices: NVDA", "› Reading the latest headlines"]
    assert wb.progress_line({"name": "specialist_market", "status": "ok"}, "NVDA") == ["✓ Stock prices ⟨NVDA⟩"]
    assert wb.progress_line({"name": "guard_advice"}, "NVDA") == []


def test_markdown_layout_keeps_words():
    md = wb.answer_markdown("Lead line.\n• one\n• two\nBear case: risk.")
    assert md == "Lead line.\n\n- one\n- two\n\n**Bear case:** risk."


def test_small_print_drops_repeats_and_foreign_filing_notes():
    reply = {**NVDA, "answer": NVDA["answer"] + "\nMarket data: Massive, end-of-day.",
             "data_note": "Data: Apple 10-K fiscal 2026 vs fiscal 2025, public SEC filings. Market data: Massive, end-of-day."}
    assert wb.small_print(reply) == "*Research aid, not investment advice.*"
    assert "code=" not in wb.footer_directive(reply)          # no "dive deeper" tools this desk does not have
