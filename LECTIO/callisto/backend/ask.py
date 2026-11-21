"""POST /api/ask: the chatbot. guard -> load facts -> write answer (Nicrron) -> check numbers.

Each stage is a LangChain Runnable with a name, so PRISM records it as its own step.
EUROPA_CHECKER=off skips the checker (for the PRISM BEFORE run). Default: on.
"""
import json
import os
import re
import time
import uuid

from langchain_core.runnables import RunnableLambda

from backend import checker, facts, llm, tracing

DISCLAIMER = "Research aid, not investment advice."
DATA_NOTE = "Data: Apple 10-K fiscal 2026 vs fiscal 2025, public SEC filings."

_ADVICE = [r"\bshould (i|we)\b[^?]*\b(buy|sell|hold|invest|short|own)\b",
           r"\b(is|it'?s|is it)\b[^?]*\ba (buy|sell|good (investment|stock|buy))\b",
           r"\b(guarantee|promise)\b",
           r"\b(buy|sell|short)\b(?!\s*back|-term)[^?]*\b(stock|shares)\b",
           # "invest in <the company or its stock>" only: "invest in research and development" is a filings question
           r"\binvest(ing)? in (apple|aapl|it|them|this|that|the (stock|company|shares))\b", r"\brecommend"]
_INVENT = [r"\bmake up\b", r"\binvent\b", r"\bfabricate\b", r"\bmade[- ]up\b"]

ADVICE_ANSWER = ("I can't give personal investment advice or promise returns. I can tell you what Apple's "
                 "filings say, for example how revenue, margins or risk factors changed.")
INVENT_ANSWER = "I only report numbers that are in the SEC filings, so I won't make one up."

SYSTEM = """You are Europa, a research assistant for financial analysts. You answer questions about one company's
two most recent annual 10-K filings, using ONLY the FACTS and RISK FACTOR CHANGES given to you.

Rules:
- Use only the given data. Never use outside knowledge. Never forecast, estimate or guess.
- If the data does not answer the question (forecasts, stock price, price targets, quarterly figures, anything not
  listed), set status to I_DONT_KNOW and say in one sentence that the filings data here doesn't cover it.
- No investment advice. Do not say whether to buy, sell or hold.
- 2 to 4 short sentences. Write money like "$478.8 billion", per-share like "$8.98", growth like "15.1%",
  margin changes like "1.9 percentage points". Say "fiscal 2026" for years. Do not show fact ids in the answer.
- Every number you write must be listed in claims with the fact_id it came from and the value exactly as written.
- If you quote a filing, copy the words exactly and list it in claims as a quote with its filing year.

Reply with JSON only, no other text:
{"status": "ANSWERED" or "I_DONT_KNOW",
 "answer": "...",
 "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"},
            {"type": "quote", "text": "exact words", "filing": "FY2026"}]}"""


def _guard(inp: dict) -> dict:
    q = inp["question"].lower()
    if any(re.search(p, q) for p in _ADVICE):
        return {**inp, "stop": ("DECLINED_ADVICE", ADVICE_ANSWER)}
    if any(re.search(p, q) for p in _INVENT):
        return {**inp, "stop": ("I_DONT_KNOW", INVENT_ANSWER)}
    if inp["ticker"] not in facts.FACTS:
        return {**inp, "stop": ("I_DONT_KNOW", f"This demo only has filings loaded for AAPL, not {inp['ticker']}.")}
    return inp


def _load_facts(inp: dict) -> dict:
    return {**inp, "sheet": facts.fact_sheet(inp["ticker"])}


def _parse(text: str) -> dict:
    """Take the LAST complete JSON object (the model sometimes self-corrects and writes a second one)."""
    dec, found, i = json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
            if isinstance(obj, dict) and "answer" in obj:
                found = obj
            i = end
        except json.JSONDecodeError:
            i += 1
    out = found
    if out is None:
        return {"status": "I_DONT_KNOW", "answer": "I couldn't produce a checked answer to that.", "claims": []}
    out.setdefault("claims", [])
    if out.get("status") not in ("ANSWERED", "I_DONT_KNOW"):
        out["status"] = "ANSWERED"
    return out


def _write(inp: dict, config) -> dict:
    prompt = f"Company: {facts.COMPANY[inp['ticker']]} ({inp['ticker']})\n\n{inp['sheet']}\n\nQuestion: {inp['question']}"
    msg = llm.model(llm.MODEL_STRONG).invoke([("system", SYSTEM), ("human", prompt)], config=config)
    return {**inp, "draft": _parse(msg.content)}


def _check(inp: dict) -> dict:
    d = inp["draft"]
    res = checker.check(inp["ticker"], d.get("answer", ""), d.get("claims", []))
    status = d["status"]
    if res["blocked"] and not res["answer"]:
        status, res["answer"] = "I_DONT_KNOW", "I couldn't verify the numbers for that answer against the SEC data, so I won't show it."
    return {**inp, "result": {"status": status, **res}}


GUARD = RunnableLambda(_guard, name="guard_advice")
LOAD = RunnableLambda(_load_facts, name="load_sec_facts")
WRITE = RunnableLambda(_write, name="write_answer")
CHECK = RunnableLambda(_check, name="check_numbers")


def _pipeline(inp: dict, config) -> dict:
    inp = GUARD.invoke(inp, config=config)
    if "stop" in inp:
        status, answer = inp["stop"]
        return {"status": status, "answer": answer, "claims": [], "blocked": []}
    inp = LOAD.invoke(inp, config=config)
    inp = WRITE.invoke(inp, config=config)
    if checker_on():
        return CHECK.invoke(inp, config=config)["result"]
    d = inp["draft"]  # BEFORE mode: model output shown unchecked
    return {"status": d["status"], "answer": d.get("answer", ""), "blocked": [],
            "claims": [{"text": str(c.get("value") or c.get("text")), "status": "UNCHECKED"} for c in d["claims"]]}


PIPELINE = RunnableLambda(_pipeline, name="europa_ask")


def checker_on() -> bool:
    return os.environ.get("EUROPA_CHECKER", "on").lower() != "off"


def answer(ticker: str, question: str) -> dict:
    """EUROPA_PIPELINE=multi (default) runs the research desk; single (or any desk error) runs answer_single()."""
    if os.environ.get("EUROPA_PIPELINE", "multi").strip().lower() == "single":
        return answer_single(ticker, question)
    try:
        from backend import desk  # inside the function: desk imports ask
        return desk.answer(ticker, question)
    except Exception:  # noqa: BLE001  the old single-agent path (which checks numbers) is the safety net
        out = {**answer_single(ticker, question), "pipeline": "single_fallback"}
        if checker_on():  # 2026-11-21 Codex final review #1: same naked-number sweep as the desk's gate
            from backend import gate
            ok = [c["text"] for c in out.get("claims") or [] if c.get("status") == "VERIFIED" and c.get("text")]
            keep = [s for s in checker.split_sentences(out.get("answer") or "") if not gate.sweep(s, ok)]
            if len(keep) != len(checker.split_sentences(out.get("answer") or "")):
                out["answer"] = " ".join(keep) or gate.FALLBACK
                if not keep:
                    out["status"] = "I_DONT_KNOW"
        return out


def answer_single(ticker: str, question: str) -> dict:
    ticker = ticker.strip().upper()
    sid = f"ask-{uuid.uuid4().hex[:12]}"
    t0 = time.time()
    with tracing.session(sid):
        out = PIPELINE.invoke({"ticker": ticker, "question": question.strip()},
                              config={"callbacks": tracing.callbacks(), "run_name": "europa_ask",
                                      "metadata": {"ticker": ticker, "checker": checker_on()}})
    return {**out, "company": facts.COMPANY.get(ticker), "prism_session_id": sid if tracing.handler else None,
            "models": [llm.MODEL_STRONG], "checker": "on" if checker_on() else "off",
            "seconds": round(time.time() - t0, 2), "data_note": DATA_NOTE, "disclaimer": DISCLAIMER,
            "pipeline": "single"}
