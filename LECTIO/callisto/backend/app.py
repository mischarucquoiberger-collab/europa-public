"""What Changed: backend API (FastAPI).

Starting point: returns FAKE data in the agreed contract shape (TEAM-PLAN.md), so the
front end can be built against it right away. Replace fake_compare / fake_ask with the
real agent. Keep the response shape the same.

Run:  uvicorn backend.app:app --reload --reload-dir backend --port 8000
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import ask as ask_agent
from backend import charts, smalltalk, snapshot, tickers
from backend.workspace_bridge import router as workspace_bridge_router

app = FastAPI(title="What Changed")
app.include_router(workspace_bridge_router)   # the Callisto page's chat client (LECTIO/kabu, /xyz)

import os as _os
import warnings as _warnings
if not _os.environ.get("NICRRON_API_KEY"):
    _warnings.warn("NICRRON_API_KEY missing in .env: every question will answer \"I couldn't produce a checked answer\".")

# The Ninoo front end runs on a different address, so allow cross-site calls.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DISCLAIMER = "Research aid, not investment advice."


class CompareRequest(BaseModel):
    ticker: str


class AskRequest(BaseModel):
    ticker: str
    question: str
    last_question: str = ""   # optional: the previous question in this chat, so "and Microsoft?" can be understood


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    """Which pipeline runs and which data sources are switched on. Booleans only, never key values."""
    import os

    from backend import massive, tracing
    return {"pipeline": os.environ.get("EUROPA_PIPELINE", "multi").strip().lower() or "multi",
            "massive": massive.available(), "prism": tracing.handler is not None,
            "nicrron": bool(os.environ.get("NICRRON_API_KEY"))}


@app.post("/api/compare")
def compare(req: CompareRequest):
    return fake_compare(req.ticker.upper())


MAX_Q = 2000
_TICKER_RX = __import__("re").compile(r"[A-Za-z.]{1,10}")


_SURR_RX = __import__("re").compile("[\ud800-\udfff]")


def _san(s) -> str:
    """Drop lone UTF-16 surrogates (they crash UTF-8 encoding in logs, tracing and model calls)."""
    return _SURR_RX.sub("", s) if isinstance(s, str) else s


def _clean_ticker(t) -> str:
    t = _san(str(t or "AAPL")).strip()
    return t.upper() if _TICKER_RX.fullmatch(t) else ""


def _bad(msg: str) -> dict:
    return {"answer": msg, "reply": msg, "response": msg, "status": "I_DONT_KNOW", "claims": [], "blocked": []}


@app.exception_handler(__import__("fastapi").exceptions.RequestValidationError)
def _validation_error(request, exc):
    """Never echo the raw bad input back (public link)."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": "Send JSON like {\"ticker\": \"AAPL\", \"question\": \"...\"}."})


# ---- chat behaviour around the desk (round K): follow-ups, one layout, suggestions. All code, no model.
_OLD_YEAR_RX = __import__("re").compile(r"\b(19\d\d|20[01]\d|202[0-4])\b")
OLD_DATE = ("That date is outside the figures Callisto checks. Price figures here cover the last trading day, the past "
            "week, month and year, the year so far and the 52-week range; filing figures cover Apple's fiscal 2025 "
            "and fiscal 2026. A chart can reach further back: try \"5 year chart of Apple\".")
UNKNOWN_HINT = " If you meant a company, type its name, for example \"How is Nvidia doing?\""
COMPARE_NOTE = ("These are source figures from Massive's end-of-day data, printed by code side by side; no model wrote "
                "them. Callisto does not say which is the better buy.")
COMPARE_WEIGH = ("To weigh: what each company earns, how its price compares with those profits, and how much of your "
                 "money sits in one stock. The buy or sell decision is yours.")


def _standalone(q: str, last: str) -> str:
    """A follow-up with no subject ("and Microsoft?") becomes a full question, using the previous one."""
    if not last:
        return q
    try:
        from backend import followup
        out = _san(str(followup.resolve(q, last) or "")).strip()
        return out[:MAX_Q] if out else q
    except Exception:
        return q


def _made_up_ticker(q: str):
    """The one ticker-looking word in a question when it is not a real stock ("how is ZZZQ doing?"), else None."""
    try:
        if q == q.upper() or tickers._NAME_RX.search(q):
            return None
        toks = [t for t in __import__("re").findall(r"(?<![\w$])\$?([A-Z]{2,5})\b", q) if t not in tickers._STOP]
        if len(toks) != 1 or not tickers.massive.available():
            return None
        return None if tickers._real_ticker(toks[0]) else toks[0]
    except Exception:
        return None


def _compare(pair, q: str):
    """Two companies side by side, from code-printed source figures (no model, so nothing for the checker to cut)."""
    try:
        from backend import desk, summary
        blocks, names = [], []
        for tk in pair:
            bullets = summary.market_bullets(tk)
            if not bullets:
                return None
            name = desk._ticker_name(tk) or tk
            short = getattr(desk, "_short_name", lambda n: n)(name) or name
            names.append(short)
            blocks += [f"{short} ({tk}):"] + ["• " + b for b in bullets]
        lines = [f"{names[0]} and {names[1]}, side by side:"] + blocks + ["What it means: " + COMPARE_NOTE, COMPARE_WEIGH]
        return {"status": "ANSWERED", "kind": "compare", "answer": "\n".join(lines), "claims": [], "blocked": [],
                "news": [], "ticker": pair[0], "tickers": list(pair), "company": f"{names[0]} vs {names[1]}",
                "checker": "source figures printed by code", "disclaimer": DISCLAIMER, "agent": "Callisto",
                "followups": [f"How has {names[0]} done this year?", f"How has {names[1]} done this year?",
                              f"Bear case for {names[1]}"]}
    except Exception:
        return None


def _key_bullets(text: str, out: dict, ticker: str) -> str:
    """When the checker cut a sentence from a market answer and the last close is no longer in the text, print the
    close and the moves as code-built source bullets right under the lead, so the key numbers are never missing."""
    try:
        if out.get("status") != "ANSWERED" or not out.get("blocked"):
            return text
        if not any(isinstance(c, dict) and c.get("provider") == "massive" for c in out.get("claims") or []):
            return text
        from backend import summary
        bullets = summary.market_bullets(ticker)[:2]
        price = __import__("re").search(r"\$[\d,.]+", bullets[0]) if bullets else None
        if not price or price.group(0).rstrip(".,") in text:
            return text
        lines = text.split("\n")
        return "\n".join(lines[:1] + ["• " + b for b in bullets] + lines[1:])
    except Exception:
        return text


def _finish(out, q: str, ticker: str, lead: str = ""):
    """Same shape for every answer (lead line, bullets, What it means, Deeper read), then follow-up suggestions.
    Layout only adds line breaks and bullet marks: the checked words are not changed."""
    if not isinstance(out, dict):
        return out
    try:
        status = out.get("status")
        if status == "I_DONT_KNOW" and not out.get("kind") and _OLD_YEAR_RX.search(q):
            out["answer"], out["claims"] = OLD_DATE, []
        elif status in ("ANSWERED", "I_DONT_KNOW", "DECLINED_ADVICE") and not out.get("kind"):
            from backend import shape
            out["answer"] = _key_bullets(shape.layout(str(out.get("answer") or "")), out, ticker)
        if lead and status in ("ANSWERED", "DECLINED_ADVICE"):
            out["answer"] = lead.rstrip() + " " + str(out.get("answer") or "")   # the lead shares the first line
    except Exception:
        pass
    try:
        from backend import followup
        tips = followup.suggest(q, ticker, str(out.get("status") or ""), str(out.get("company") or ""))
        if tips and not out.get("followups"):
            out["followups"] = [str(t) for t in tips][:3]
    except Exception:
        pass  # extras never break an answer
    return out


@app.post("/api/ask")
def ask(req: AskRequest):
    ticker, q = _clean_ticker(req.ticker), _san(req.question or "").strip()
    if not ticker:
        return _bad("Please send a stock ticker of up to 10 letters, like AAPL.")
    if not q:
        return _bad("Please send a question.")
    if len(q) > MAX_Q:
        return _bad(f"Please keep questions under {MAX_Q} characters.")
    chat = smalltalk.reply(q)
    if not chat:
        q = _standalone(q, _san(req.last_question or "").strip()[:MAX_Q])
        chat = smalltalk.reply(q)
    if chat:      # greetings, "what are you", trust, off-topic: fixed text from code, no model, no data
        return _finish({"status": "CHAT", "kind": chat[0], "answer": chat[1], "claims": [], "blocked": [], "news": [],
                        "agent": "Callisto"}, q, ticker)
    try:
        from backend import followup
        pair = followup.pair(q)
    except Exception:
        pair = None
    if pair:
        both = _compare(pair, q)
        if both:
            return _finish(both, q, pair[0])
    fake = _made_up_ticker(q)
    if fake:
        from backend import desk
        return _finish({"status": "I_DONT_KNOW", "kind": "unknown_ticker", "claims": [], "blocked": [], "news": [],
                        "answer": desk.NOTICE_UNKNOWN_TICKER.format(ticker=fake) + UNKNOWN_HINT, "agent": "Callisto"},
                       q, ticker)
    ticker = _resolve_ticker(q, ticker)
    worry = ""
    try:
        if smalltalk.wants_reassurance(q):
            worry = smalltalk.WORRY_LEAD
    except Exception:
        pass
    if smalltalk.wants_prediction(q) and not charts.wanted(q):
        # no forecast: say so in fixed words, then the normal checked market summary
        out = ask_agent.answer(ticker, "How has the stock price moved recently?")
        if isinstance(out, dict):
            out["ticker"] = ticker
            if out.get("status") == "ANSWERED":
                try:
                    tiles = snapshot.stats(ticker)
                    if tiles:
                        out["stats"] = tiles
                except Exception:
                    pass
                return _finish(out, q, ticker, lead=smalltalk.PREDICT_LEAD)
        return _finish(out, q, ticker)
    want = charts.wanted(q)
    # an asked-for chart is drawn by code, so the writer gets the question without the chart words
    out = ask_agent.answer(ticker, charts.strip_chart_words(q) if want else q)
    if not isinstance(out, dict):
        return out
    out["ticker"] = ticker
    try:
        if want:
            out["charts"] = charts.charts_for(ticker, q)
        elif out.get("status") != "I_DONT_KNOW" and charts.auto_wanted(q):
            auto = charts.auto_charts(ticker, q)
            if auto:
                out["charts"] = auto
        if out.get("status") in ("ANSWERED", "DECLINED_ADVICE"):
            tiles = snapshot.stats(ticker)
            if tiles:
                out["stats"] = tiles
    except Exception:
        pass  # extras never break an answer
    return _finish(out, q, ticker, lead=worry)


def _resolve_ticker(q: str, sent: str) -> str:
    """The stock the question names wins over the ticker box; the box is the fallback."""
    try:
        t = _clean_ticker(tickers.pick_ticker(q, sent))
        return t or sent
    except Exception:
        return sent


@app.post("/api/chat")
def chat(body: dict):
    """Generic chat address for testers like PRISM "Test your AI": accepts {message}, {question}, {input},
    {prompt} or OpenAI-style {messages:[...]}; ticker optional (default AAPL). Same pipeline as /api/ask."""
    def _text(c) -> str:
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(p["text"] for p in c[:50] if isinstance(p, dict) and isinstance(p.get("text"), str))
        return ""
    text = next((body[k] for k in ("message", "question", "input", "prompt", "query")
                 if isinstance(body.get(k), str) and body[k].strip()), "")
    msgs = body.get("messages")
    if not text and isinstance(msgs, list):
        for m in reversed(msgs[-200:]):
            if isinstance(m, dict) and m.get("role", "user") == "user" and _text(m.get("content")).strip():
                text = _text(m.get("content"))
                break
    text = _san(text).strip()
    ticker = _clean_ticker(body.get("ticker"))
    if not ticker:
        return _bad("Please send a stock ticker of up to 10 letters, like AAPL.")
    if not text:
        return _bad("Please send a question.")
    if len(text) > MAX_Q:
        return _bad(f"Please keep questions under {MAX_Q} characters.")
    out = ask_agent.answer(ticker, text)
    return {**out, "reply": out.get("answer", ""), "response": out.get("answer", "")}


@app.get("/")
def chat_page():
    """The simple chat page (same address as the API, so one public link serves both)."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")


# ---------- FAKE DATA: replace with the real agent ----------

def fake_compare(ticker: str) -> dict:
    return {
        "fake_data": True,  # remove when real data flows
        "company": f"FAKE DATA for {ticker}",
        "cik": "0000000000",
        "filings": [
            {"form": "10-K", "period_end": "2026-09-26", "url": "https://www.sec.gov/"},
            {"form": "10-K", "period_end": "2025-09-27", "url": "https://www.sec.gov/"},
        ],
        "changes": [
            {
                "rank": 1,
                "title": "FAKE: new risk factor about a single supplier",
                "summary": "Placeholder text so the page has something to show.",
                "claims": [
                    {"text": "SYNTHETIC (placeholder, not checked): Revenue was $100.0 billion", "status": "UNCHECKABLE",
                     "source": "placeholder", "sec_value": 100000000000},
                ],
            }
        ],
        "blocked": [
            {"text": "SYNTHETIC (placeholder): Revenue was $120.0 billion", "status": "MISMATCH",
             "note": "SYNTHETIC placeholder: SEC says $100.0B"},
        ],
        "cost_usd": 0.0,
        "models": [],
        "prism_session_id": None,
        "disclaimer": DISCLAIMER,
    }


def fake_ask(ticker: str, question: str) -> dict:
    q = question.lower()
    if any(w in q for w in ("buy", "sell", "should i invest", "price target")):
        return {"answer": "I can't give personal investment advice. I can show what the filings say.",
                "claims": [], "status": "DECLINED_ADVICE", "fake_data": True}
    return {"answer": f"FAKE DATA: placeholder answer about {ticker}.", "claims": [],
            "status": "I_DONT_KNOW", "fake_data": True}
