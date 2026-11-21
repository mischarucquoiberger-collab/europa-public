"""Workspace bridge: the Callisto page's pre-built chat client (a LibreChat fork, LECTIO/kabu/public/xyz)
talks to the research desk through these routes.

Wire protocol (from the fork's source in ~/Desktop/LLM/LibreChat):
- client/src/hooks/SSE/useResumableSSE.ts: the client POSTs the question to /api/agents/chat/:endpoint and
  expects JSON with a `streamId`, then opens GET /api/agents/chat/stream/:streamId as Server-Sent Events.
  The start reply carries no `generationProtocolVersion: 2`, so the client stays on protocol 1 (no status
  check before it accepts the final frame).
- api/server/controllers/agents/request.js: frames are `{created: true, message}` (the user message), step
  events `{event: "on_run_step" | "on_reasoning_delta" | "on_message_delta", data}`, and the closing
  `{final: true, conversation, title, requestMessage, responseMessage}`.
- client/src/components/Chat/Research/Query: the Query answer's thinking line is a `think` content part
  (lines `Looking up <Label>: <hint>` / `✓ <Label> ⟨hint⟩: <summary>` / `› <thought>`, steps.ts); the
  look-up chips and the price card are the `::indago-query-head{...}` directive line at the top of the text
  (Run/directive.ts parseQueryHead); the follow-up buttons are the `::indago-query{...}` footer directive.
  The card's range buttons read GET /api/price-history/{code}?days=&interval= -> [{date, close}].

The bridge never calls a model and never writes a number of its own: every figure is the desk's text or a
Massive bar.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import queue as _queue
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="workspace-bridge")

ENDPOINT = "Indago"
DEFAULT_MODEL = "indago-query"
SENDER = "Callisto"
FALLBACK_TICKER = "AAPL"
PRELIM = "USE_PRELIM_RESPONSE_MESSAGE_ID"
MAX_CONVOS = 200
_JOB_TTL = 600.0

# tests replace these: desk_fn(question, ticker, last_question) -> reply shaped like POST /api/ask;
# bars_fn(ticker) -> Massive daily bars [{"date", "c"}] oldest first (or raises)
desk_fn = None
bars_fn = None
resolve_fn = None    # (question, ticker, last_question) -> ticker the desk will answer about, or ""

_lock = threading.Lock()
_convos: dict = {}   # conversationId -> {"ticker", "last_question", "title", "messages", "created", "updated"}
_jobs: dict = {}     # streamId -> job

# the client's own look-up names (Query/steps.ts ADAPTER_TOOL_LABELS)
LABELS = {"lookup_company": "Company lookup", "get_stock_prices": "Stock prices", "get_financials": "Financials"}
_SPECIALIST_TOOL = {"specialist_market": "get_stock_prices", "specialist_filings": "get_financials",
                    "specialist_fundamentals": "get_financials"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sse(obj: dict) -> str:
    return "event: message\ndata: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _attr(v) -> str:
    """A directive attribute value: no quotes, braces or line breaks, at most 380 characters."""
    return re.sub(r"[\"{}\n\r\\]", "", " ".join(str(v or "").split()))[:380]


# ---------- answer text -> Markdown (layout only; words and figures stay as the desk wrote them)
_LABEL_RX = re.compile(r"^(Strengths|Watch-outs|What it means|Deeper read|Bear case|Bull case|To weigh|"
                       r"How to decide|In the news[^:]{0,40}|Market data|Data|Sources?):\s*")


def answer_markdown(text: str) -> str:
    out: list[str] = []
    prev_bullet = False
    for raw in str(text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("• "):
            if not prev_bullet and out:
                out.append("")
            out.append("- " + line[2:].strip())
            prev_bullet = True
            continue
        m = _LABEL_RX.match(line)
        if m:
            line = f"**{m.group(0).strip()}** " + line[m.end():]
        if out:
            out.append("")
        out.append(line)
        prev_bullet = False
    return "\n".join(out).strip()


def small_print(reply: dict) -> str:
    """data_note and disclaimer as small italic lines. A data-note sentence the answer already says is left
    out, and so is a filings note on an answer that used no filings (the desk's note can name Apple's 10-K
    on a market-only answer about another stock)."""
    answer = str(reply.get("answer") or "")
    used_sec = any(s["tool"] == "get_financials" for s in lookups(reply))
    note = []
    for sent in re.split(r"(?<=\.)\s+", str(reply.get("data_note") or "").strip()):
        if not sent or sent in answer or (not used_sec and re.search(r"\b10-K\b|SEC filings", sent)):
            continue
        note.append(sent)
    bits = [b for b in (" ".join(note), str(reply.get("disclaimer") or "").strip()) if b]
    return "\n\n".join("*" + b.replace("*", "") + "*" for b in bits)


# ---------- look-ups: only the data sources the desk really used
def lookups(reply: dict) -> list[dict]:
    """[{tool, hint, summary, src}] for the chips and the finished thinking lines."""
    ticker = str(reply.get("ticker") or "").upper()
    if str(reply.get("status") or "") == "CHAT" or not ticker:
        return []
    rows = {str(a.get("name") or ""): a for a in reply.get("agents") or [] if isinstance(a, dict)}
    ok = lambda n: n in rows and rows[n].get("status", "ok") == "ok"   # noqa: E731
    claims = [c for c in reply.get("claims") or [] if isinstance(c, dict)]
    srcs = " ".join(str(s.get("name") or "") for s in reply.get("sources") or [] if isinstance(s, dict)).lower()
    has_market = ok("specialist_market") or bool(reply.get("stats")) or any(
        str(c.get("provider") or "") == "massive" for c in claims)
    has_sec = ok("specialist_filings") or ok("specialist_fundamentals") or "sec" in srcs
    out: list[dict] = []
    company = str(reply.get("company") or "").strip()
    if company or has_market or has_sec:
        out.append({"tool": "lookup_company", "hint": ticker, "summary": company or ticker,
                    "src": "Massive reference data"})
    if has_market:
        out.append({"tool": "get_stock_prices", "hint": ticker, "summary": "Massive end-of-day bars",
                    "src": "Massive"})
    if has_sec:
        out.append({"tool": "get_financials", "hint": ticker, "summary": "SEC EDGAR 10-K filings",
                    "src": "SEC EDGAR"})
    return out


def think_lines(reply: dict) -> str:
    lines = ["Thinking…"]
    for s in lookups(reply):
        lines.append(f"✓ {LABELS[s['tool']]} ⟨{s['hint']}⟩: {s['summary']}")
    return "\n".join(lines) + "\n"


# ---------- price card (Massive bars only)
_PRICE_Q_RX = re.compile(r"\b(price|stock|shares?|done|doing|perform\w*|returns?|mov(e|ed|ing)|chart|graph|"
                         r"ytd|rall(y|ied)|drop(ped)?|fell|rose|gain\w*|past (year|month|week)|this year)\b", re.I)


def wants_card(reply: dict, question: str) -> bool:
    if str(reply.get("status") or "") not in ("ANSWERED", "DECLINED_ADVICE") or reply.get("kind") == "compare":
        return False
    if any(isinstance(c, dict) and c.get("type") == "line" and c.get("unit") == "usd_price"
           for c in reply.get("charts") or []):
        return True
    return bool(_PRICE_Q_RX.search(question or ""))


def _daily_bars(ticker: str, days: int) -> list[dict]:
    if bars_fn is not None:
        return bars_fn(ticker)
    from backend import massive
    end = massive.today_et()
    return massive.daily_bars(ticker, end - timedelta(days=days), end)


def _num(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


def card_attrs(ticker: str) -> dict | None:
    """price / chg / prev / asof / hist from Massive daily closes; None when Massive has no bars."""
    try:
        bars = [b for b in _daily_bars(ticker, 400) if isinstance(b.get("c"), (int, float)) and b["c"] > 0]
    except Exception:
        return None
    if len(bars) < 2:
        return None
    last, prev = bars[-1], bars[-2]
    year = [b for b in bars if b["date"] >= (date.fromisoformat(last["date"]) - timedelta(days=365)).isoformat()]
    step = max(1, -(-len(year) // 39))
    pts = year[::step]
    if pts[-1] is not last:
        pts.append(last)
    pts = pts[-40:]
    hist = ",".join(b["date"][2:4] + b["date"][5:7] + b["date"][8:10] + ":" + _num(b["c"]) for b in pts)
    return {"price": _num(last["c"]), "prev": _num(prev["c"]),
            "chg": f"{(last['c'] / prev['c'] - 1) * 100:.2f}", "state": "CLOSED",
            "asof": f"{last['date']} close · ET", "hist": hist, "last_date": last["date"]}


def head_directive(reply: dict, question: str) -> str:
    steps = lookups(reply)
    if not steps:
        return ""
    ticker = str(reply.get("ticker") or "").upper()
    attrs = {"v": "1", "code": ticker}
    card = card_attrs(ticker) if wants_card(reply, question) else None
    if card:
        attrs.update({"pcode": ticker, "price": card["price"], "chg": card["chg"], "prev": card["prev"],
                      "state": card["state"], "asof": card["asof"], "hist": card["hist"]})
    for n, s in enumerate(steps[:8], 1):
        attrs[f"t{n}"] = "|".join(_attr(x).replace("|", "/") for x in (s["tool"], s["hint"], s["summary"], s["src"]))
    return "::indago-query-head{" + " ".join(f'{k}="{_attr(v)}"' for k, v in attrs.items()) + "}"


def footer_directive(reply: dict) -> str:
    steps = lookups(reply)
    tips = [str(t) for t in reply.get("followups") or [] if str(t).strip()][:3]
    if not steps and not tips:
        return ""
    srcs = []
    for s in steps:
        if s["src"] not in srcs:
            srcs.append(s["src"])
    attrs = {"v": "1", "status": "ok", "tools": str(len(steps)), "sources": str(len(srcs)), "landed": "1",
             "deep": "0", "src": " | ".join(srcs)}
    if isinstance(reply.get("seconds"), (int, float)):
        attrs["elapsed"] = f"{reply['seconds']:.1f}"
    for n, t in enumerate(tips, 1):
        attrs[f"f{n}"] = t
    if steps:
        attrs["used"] = " ".join(s["tool"] for s in steps)
    return "::indago-query{" + " ".join(f'{k}="{_attr(v)}"' for k, v in attrs.items() if v != "") + "}"


def answer_text(reply: dict, question: str) -> str:
    head = head_directive(reply, question)
    body = answer_markdown(reply.get("answer") or "") or "I couldn't produce a checked answer to that."
    parts = [p for p in (head, body, small_print(reply), footer_directive(reply)) if p]
    return "\n\n".join(parts)


# ---------- live progress: desk stage rows -> thinking lines in the client's grammar
def progress_line(row: dict, ticker: str) -> list[str]:
    name, status = str(row.get("name") or ""), str(row.get("status") or "ok")
    tool = _SPECIALIST_TOOL.get(name)
    if name == "desk_router":
        note = str(row.get("note") or "")
        picked = [p.strip() for p in note.split("picked ")[-1].split(",")] if "picked " in note else []
        out = [f"✓ Company lookup ⟨{ticker}⟩"] if ticker else []
        seen = set()
        for p in picked:
            t = _SPECIALIST_TOOL.get("specialist_" + p)
            if t and t not in seen:
                seen.add(t)
                out.append(f"Looking up {LABELS[t]}: {ticker}" if ticker else f"Looking up {LABELS[t]}")
        if "news" in picked:
            out.append("› Reading the latest headlines")
        return out
    if tool:
        tail = "" if status == "ok" else ": Error: data unavailable"
        return [f"✓ {LABELS[tool]}" + (f" ⟨{ticker}⟩" if ticker else "") + tail]
    if name == "write_answer":
        return ["› Draft written; checking every figure against the sources"]
    if name == "skeptic_review":
        return ["› Skeptic review done"]
    if name == "number_gate":
        return ["› Number check done"]
    return []


def _remember(conv_id: str, **fields) -> dict:
    with _lock:
        c = _convos.setdefault(conv_id, {"ticker": "", "last_question": "", "title": "", "messages": [],
                                         "created": _now_iso()})
        c.update(fields)
        c["updated"] = _now_iso()
        if len(_convos) > MAX_CONVOS:
            for k in sorted(_convos, key=lambda k: _convos[k].get("updated", ""))[: len(_convos) - MAX_CONVOS]:
                _convos.pop(k, None)
        return c


def conversation_state(conv_id: str) -> dict:
    with _lock:
        return dict(_convos.get(conv_id) or {})


def _title(q: str) -> str:
    q = " ".join(str(q or "").split())
    return (q[:48].rstrip() + "…") if len(q) > 50 else (q or "New chat")


def _resolve(question: str, ticker: str, last: str) -> str:
    if resolve_fn is not None:
        return resolve_fn(question, ticker, last)
    if desk_fn is not None:
        return ""
    try:
        from backend import app as desk_app, smalltalk
        if smalltalk.reply(question):
            return ""
        q = desk_app._standalone(question, last)
        if smalltalk.reply(q):
            return ""
        return desk_app._resolve_ticker(q, ticker)
    except Exception:
        return ""


def _run_desk(question: str, ticker: str, last: str, emit) -> dict:
    """Runs in a worker thread with its own context, so the desk's progress hook sees only this question."""
    def work():
        tk = _resolve(question, ticker, last)
        if tk:
            emit({"think": f"Looking up Company lookup: {tk}\n"})
        hook = None
        try:
            from backend import desk
            hook = desk.on_step
        except Exception:
            pass
        if hook is not None:
            hook.set(lambda row: [emit({"think": ln + "\n"}) for ln in progress_line(row, tk)])
        if desk_fn is not None:
            return desk_fn(question, ticker, last)
        from backend import app as desk_app
        return desk_app.ask(desk_app.AskRequest(ticker=ticker, question=question, last_question=last))
    return contextvars.copy_context().run(work)


@router.post("/xyz/api/agents/chat/abort")
async def abort(request: Request):
    return JSONResponse({"success": True})


@router.post("/xyz/api/agents/chat/{endpoint}")
async def start(endpoint: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    text = str(body.get("text") or "").strip()
    if not text:
        return JSONResponse({"message": "Please type a question."}, status_code=400)
    conv_id = str(body.get("conversationId") or "")
    if not conv_id or conv_id in ("new", "null", "undefined") or len(conv_id) > 80:
        conv_id = str(uuid.uuid4())
    msg_id = str(body.get("messageId") or uuid.uuid4())
    parent = str(body.get("parentMessageId") or "00000000-0000-0000-0000-000000000000")
    response_id = str(body.get("responseMessageId") or (msg_id + "_"))
    model = str(body.get("model") or DEFAULT_MODEL)
    state = conversation_state(conv_id)
    ticker, last_q = state.get("ticker") or FALLBACK_TICKER, state.get("last_question") or ""
    user = {"messageId": msg_id, "parentMessageId": parent, "conversationId": conv_id, "text": text,
            "sender": "User", "isCreatedByUser": True, "endpoint": ENDPOINT, "model": model,
            "createdAt": _now_iso()}
    queue: _queue.SimpleQueue = _queue.SimpleQueue()   # thread-safe: the desk thread writes, the stream reads
    future = _POOL.submit(_run_desk, text, ticker, last_q, queue.put)
    with _lock:
        for k in [k for k, j in _jobs.items() if j["created"] < time.monotonic() - _JOB_TTL]:
            _jobs.pop(k, None)
        _jobs[conv_id] = {"future": future, "queue": queue, "user": user, "response_id": response_id,
                          "model": model, "created": time.monotonic(), "question": text}
    _remember(conv_id, title=state.get("title") or _title(text))
    return JSONResponse({"streamId": conv_id, "conversationId": conv_id, "status": "started"})


def final_frame(job: dict, reply: dict, conv: dict) -> dict:
    user, rid, model = job["user"], job["response_id"], job["model"]
    content = []
    think = think_lines(reply) if lookups(reply) else ""
    if think:
        content.append({"type": "think", "think": think})
    content.append({"type": "text", "text": answer_text(reply, job.get("question", ""))})
    response = {"messageId": rid, "parentMessageId": user["messageId"], "conversationId": user["conversationId"],
                "sender": SENDER, "isCreatedByUser": False, "endpoint": ENDPOINT, "model": model,
                "text": content[-1]["text"], "content": content, "unfinished": False, "error": False,
                "createdAt": _now_iso()}
    conversation = {"conversationId": user["conversationId"], "title": conv.get("title") or _title(user["text"]),
                    "endpoint": ENDPOINT, "model": model, "createdAt": conv.get("created") or _now_iso(),
                    "updatedAt": _now_iso()}
    return {"final": True, "conversation": conversation, "title": conversation["title"],
            "requestMessage": user, "responseMessage": response}


def _step(step_id: str, index: int) -> dict:
    return {"event": "on_run_step", "data": {"id": step_id, "runId": PRELIM, "index": index,
                                             "type": "message_creation",
                                             "stepDetails": {"type": "message_creation",
                                                             "message_creation": {"message_id": step_id}}}}


async def stream_frames(job: dict):
    """Every frame of one answer, in order, as dicts (the SSE route serialises them)."""
    user, rid = job["user"], job["response_id"]
    yield {"created": True, "message": user, "streamId": user["conversationId"]}
    think_id, text_id = f"think_{rid}", f"text_{rid}"
    think_open = False
    future, queue = job["future"], job["queue"]
    while True:
        finished = future.done()          # read before draining, so no line written before the end is lost
        while True:
            try:
                item = queue.get_nowait()
            except _queue.Empty:
                break
            if not think_open:
                think_open = True
                yield _step(think_id, 0)
                yield {"event": "on_reasoning_delta", "data": {"id": think_id, "delta": {
                    "content": [{"type": "think", "think": "Thinking…\n"}]}}}
            yield {"event": "on_reasoning_delta", "data": {"id": think_id, "delta": {
                "content": [{"type": "think", "think": item["think"]}]}}}
        if finished:
            break
        await asyncio.sleep(0.05)
    try:
        reply = future.result()
    except Exception:
        reply = {"status": "I_DONT_KNOW", "answer": "Callisto's research desk hit an error on that question. "
                                                    "Please try again.", "claims": []}
    if not isinstance(reply, dict):
        reply = {"status": "I_DONT_KNOW", "answer": str(reply or ""), "claims": []}
    tk = str(reply.get("ticker") or "").upper()
    conv = _remember(user["conversationId"], last_question=user["text"], **({"ticker": tk} if tk else {}))
    final = final_frame(job, reply, conv)
    text = final["responseMessage"]["content"][-1]["text"]
    yield _step(text_id, 1 if think_open else 0)
    for i in range(0, len(text), 240):
        yield {"event": "on_message_delta", "data": {"id": text_id, "delta": {
            "content": [{"type": "text", "text": text[i:i + 240]}]}}}
    with _lock:
        conv["messages"] = (conv.get("messages") or []) + [final["requestMessage"], final["responseMessage"]]
        _jobs.pop(user["conversationId"], None)
    yield final


@router.get("/xyz/api/agents/chat/stream/{stream_id}")
async def stream(stream_id: str, request: Request):
    with _lock:
        job = _jobs.get(stream_id)
    if not job:
        return JSONResponse({"message": "This answer has finished or expired."}, status_code=404)

    async def gen():
        async for frame in stream_frames(job):
            yield _sse(frame)
            if frame.get("event") == "on_message_delta":
                await asyncio.sleep(0.02)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


# ---------- the price card's range buttons: GET /api/price-history/{code}?days=&interval=
_INTERVALS = {"1d": (1, "day"), "5m": (5, "minute"), "15m": (15, "minute"), "30m": (30, "minute"),
              "60m": (1, "hour")}


@router.get("/api/price-history/{code}")
def price_history(code: str, days: int = 90, interval: str = "1d"):
    from zoneinfo import ZoneInfo
    from backend import massive
    t = str(code or "").upper()
    if not massive.valid_ticker(t) or not 1 <= int(days) <= 2000 or interval not in _INTERVALS:
        return JSONResponse({"detail": "bad request"}, status_code=400)
    mult, span = _INTERVALS[interval]
    end = massive.today_et()
    start = end - timedelta(days=int(days) + (4 if interval != "1d" else 0))
    try:
        data = massive.get(f"/v2/aggs/ticker/{t}/range/{mult}/{span}/{start.isoformat()}/{end.isoformat()}",
                           {"adjusted": "true", "sort": "asc", "limit": 50000}, ttl=300)
    except Exception:
        return JSONResponse([], status_code=200)
    et = ZoneInfo("America/New_York")
    out = []
    for row in data.get("results") or []:
        try:
            ts = datetime.fromtimestamp(float(row["t"]) / 1000.0, tz=et)
            c = float(row["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if interval == "1d":
            out.append({"date": ts.date().isoformat(), "close": c})
        elif 9 * 60 + 30 <= ts.hour * 60 + ts.minute < 16 * 60:     # regular session only
            out.append({"date": ts.strftime("%Y-%m-%d %H:%M"), "close": c, "open": float(row.get("o") or c),
                        "high": float(row.get("h") or c), "low": float(row.get("l") or c)})
    if interval != "1d" and out:
        days_seen = sorted({p["date"][:10] for p in out})
        keep = set(days_seen[-max(1, int(days) if int(days) <= 5 else len(days_seen)):])
        out = [p for p in out if p["date"][:10] in keep]
    return out


# ---------- what the client reads back after an answer: stream status, the conversation, its messages, titles
@router.get("/xyz/api/agents/chat/status/{conversation_id}")
def stream_status(conversation_id: str):
    with _lock:
        job = _jobs.get(conversation_id)
    if job is None:
        return {"active": False}
    return {"active": True, "streamId": conversation_id, "status": "running"}


def _convo_row(cid: str, c: dict) -> dict:
    return {"conversationId": cid, "title": c.get("title") or "New chat", "endpoint": ENDPOINT,
            "model": DEFAULT_MODEL, "createdAt": c.get("created"), "updatedAt": c.get("updated")}


@router.get("/xyz/api/messages/{conversation_id}")
def messages(conversation_id: str):
    with _lock:
        return list((_convos.get(conversation_id) or {}).get("messages") or [])


@router.get("/xyz/api/convos/gen_title/{conversation_id}")
def gen_title(conversation_id: str):
    c = conversation_state(conversation_id)
    if not c:
        return JSONResponse({"message": "Not found"}, status_code=404)
    return {"title": c.get("title") or "New chat"}


@router.get("/xyz/api/convos/{conversation_id}")
def convo(conversation_id: str):
    c = conversation_state(conversation_id)
    if not c:
        return JSONResponse({"message": "Not found"}, status_code=404)
    return _convo_row(conversation_id, c)


@router.get("/xyz/api/convos")
def convos():
    with _lock:
        rows = [_convo_row(k, v) for k, v in _convos.items() if v.get("messages")]
    rows.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)
    return {"conversations": rows, "nextCursor": None}
