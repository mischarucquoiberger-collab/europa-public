"""Model agents for the Europa desk: router, news picker, writer, skeptic.

Every model call goes through llm.model(name). Each agent tries a short list of models in order and
never raises: a failure falls back to the next model, then to a safe code answer.
Models only choose, phrase and criticise. They never do arithmetic and never see headline text
(except the news picker, which may only return headline ids).
"""
import json
import os
import re

from langchain_core.runnables import RunnableLambda

from backend import llm

ROUTER_MODELS = [os.environ.get("MODEL_ROUTER") or llm.MODEL_FAST, "openai/gpt-5.4-mini"]
WRITER_MODELS = [os.environ.get("MODEL_WRITER") or llm.MODEL_STRONG, "openai/gpt-5.4"]
# Speed (2026-11-21, measured on 30 and 220 live questions): the strong writer takes about 6 s of a 7 s answer, the
# fast one about 2 s, with the same checked numbers. Ordinary questions use the fast list; the long summaries behind
# advice questions (fixed questions, so the provider caches them) keep the strong writer.
# MODEL_WRITER set, or EUROPA_FAST_WRITER=off, puts every answer back on WRITER_MODELS.
WRITER_FAST_MODELS = [os.environ.get("MODEL_WRITER_FAST") or "openai/gpt-5.4", llm.MODEL_STRONG]


def writer_models(long_form: bool = False) -> list:
    if long_form or os.environ.get("MODEL_WRITER") or os.environ.get("EUROPA_FAST_WRITER", "on").lower() == "off":
        return WRITER_MODELS
    return WRITER_FAST_MODELS
SKEPTIC_MODELS = [os.environ.get("MODEL_SKEPTIC") or "openai/gpt-5.4-mini", "openai/gpt-5-mini",
                  "mistral/mistral-large-4"]
NEWS_MODELS = [os.environ.get("MODEL_NEWS") or "openai/gpt-5.4-mini", llm.MODEL_FAST]

KNOWN = ("filings", "market", "fundamentals", "news")
VERDICTS = ("SUPPORTED", "UNSUPPORTED", "ADVICE")
FAIL_DRAFT = {"status": "I_DONT_KNOW", "answer": "I couldn't produce a checked answer to that.", "claims": []}


def _last_json(text: str, need_key: str | None = None) -> dict | None:
    """The LAST complete JSON object in the text (that has need_key, if given)."""
    dec, found, i = json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict) and (need_key is None or need_key in obj):
            found = obj
        i = end
    return found


def _EXTRA_PARAMS(model_name: str) -> dict:
    return {"reasoning_effort": "low", "top_p": 1} if "mistral-large-4" in str(model_name) else {}


def call_json(models, system, human, config=None, need_key=None):
    """Try each model in order. Returns (json dict, model name) or (None, None). Never raises."""
    for name in models:
        try:
            m = llm.model(name)
            extra = _EXTRA_PARAMS(name)
            if extra:  # mistral-large-4 is rejected without reasoning_effort and top_p=1 (see council.bind_for)
                m = m.bind(**extra)
            msg = m.invoke([("system", system), ("human", human)], config=config)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            obj = _last_json(content, need_key)
            if obj is not None:
                return obj, name
        except Exception:  # noqa: BLE001  any model or network error -> next model
            continue
    return None, None


# ---------------------------------------------------------------- router
_KEYWORDS = [
    ("market", r"\bdividends?\b|\byield\b|\bprice\b|\bstock\b|share price|\bclos(e|ed|ing)\b|\btrading\b|\breturns?\b|market cap|"
               r"52-week|\bvolume\b"),
    ("news", r"\bnews\b|\bheadlines?\b|\barticles?\b|\bpress\b"),
    ("fundamentals", r"second source|cross-check|cross check|\bconfirm|\bagree|\bmassive\b"),
    ("filings", r"\brevenue|\bsales\b|\bmargin|\beps\b|\bincome\b|\brisks?\b|10-k|\bfiling|\bbuybacks?\b|"
                r"\brepurchase|r&d|research and development|\bearnings\b|\bcash\b"),
]


def route_by_keywords(question: str) -> list[str]:
    q = (question or "").lower()
    picked = [name for name, rx in _KEYWORDS if re.search(rx, q)]
    return picked or ["filings"]


ROUTER_SYSTEM = """You route questions for Europa, a research assistant for financial analysts.
Pick which specialists are needed to answer the question:
- "filings": annual 10-K figures (revenue, margins, R&D, operating income, net income, EPS, cash, buybacks) and risk factors.
- "market": stock price, closing price, price returns over a period, 52-week range and distance from the
  52-week high or low, market cap, trading volume, dividends per share and dividend yield. Also pick it for
  questions about whether the stock is expensive, overvalued, safe or risky, why it moved, and what analysts
  think. For a bear case, bull case or pros and cons, pick "market" and "filings" together.
- "fundamentals": whether a second source confirms or agrees with the reported annual figures.
- "news": recent headlines about the company.
Pick one or more. Questions about forecasts, price targets or "what will revenue be" go to "filings".

Set "advice" to true ONLY when the user asks what they should do with their money (buy, sell, hold,
get in, get out, how much to own) or wants a promise about returns. Forecasts, price targets and
"what will revenue be" are NOT advice.

Reply with JSON only:
{"specialists": ["filings"], "advice": false, "reason": "short reason"}"""


def route(inp: dict, config=None) -> dict:
    human = f"Ticker: {inp.get('ticker', '')}\nQuestion: {inp.get('question', '')}"
    obj, name = call_json(ROUTER_MODELS, ROUTER_SYSTEM, human, config, need_key="specialists")
    if obj is None or not isinstance(obj.get("specialists"), list):
        return {"specialists": route_by_keywords(inp.get("question", "")), "advice": False,
                "reason": "keyword routing (router model unavailable)", "model": None, "fallback": True}
    picked = []
    for s in obj["specialists"]:
        s = str(s).strip().lower()
        if s in KNOWN and s not in picked:
            picked.append(s)
    return {"specialists": picked or ["filings"], "advice": obj.get("advice") is True,
            "reason": str(obj.get("reason") or "")[:300], "model": name, "fallback": False}


# ---------------------------------------------------------------- news picker
NEWS_SYSTEM = """You pick the headlines most relevant to an analyst's question.
You see numbered headlines as "N1 | date | publisher | title". Return at most 3 ids, most relevant first.
Return ids only, never headline text.
Reply with JSON only: {"ids": ["N2", "N5"]}"""


def pick_news(inp: dict, config=None) -> dict:
    items = list(inp.get("items") or [])
    first3 = [it.get("id") for it in items[:3]]
    if len(items) <= 3:
        return {"ids": first3, "model": None}
    lines = [f"N{n} | {str(it.get('published_utc') or '')[:10]} | {it.get('publisher') or ''} | {it.get('title') or ''}"
             for n, it in enumerate(items, 1)]
    human = f"Question: {inp.get('question', '')}\n\nHeadlines:\n" + "\n".join(lines)
    obj, name = call_json(NEWS_MODELS, NEWS_SYSTEM, human, config, need_key="ids")
    if obj is None or not isinstance(obj.get("ids"), list):
        return {"ids": first3, "model": None}
    ids = []
    for raw in obj["ids"]:
        m = re.fullmatch(r"\s*N?(\d+)\s*", str(raw), re.I)
        if not m:
            continue
        k = int(m.group(1))
        if 1 <= k <= len(items):
            iid = items[k - 1].get("id")
            if iid not in ids:
                ids.append(iid)
        if len(ids) == 3:
            break
    return {"ids": ids or first3, "model": name}


# ---------------------------------------------------------------- writer
WRITER_SYSTEM = """You are Europa, a plain-English assistant for everyday investors (retail traders, not analysts). Lead with the direct answer.
Explain a finance term in under 8 words the FIRST time it appears (e.g. "diluted EPS, the profit earned per share";
"operating income, profit from the core business") and never repeat that explanation: after the first time, write the
term alone. Everyday terms (price, sales, profit, dividend) need no explanation. Then say what the change means in
everyday words. In the answer never write the words "sheet", "sheets", "evidence" or "demo": call it "the data here". Summarize long
filing text in your own short words instead of quoting it at length. Never write numbers or fractions as words
(no "a sixth", "doubled", "twice"). If asked what a term means, explain it plainly and give its figure.
If the question states a number or direction that the sheets contradict, never repeat the user's number: say it is not
right and state the true value from the sheets (e.g. "Diluted EPS in fiscal 2026 was $8.98."). Check the direction a
question assumes ("why did X fall") against the sheets before answering; if it actually rose, say so with the figure.
You answer questions about one company
using ONLY the EVIDENCE SHEETS given to you (for example SEC 10-K facts, end-of-day market data, a second-source check).

Rules:
- Use only the evidence sheets. Never use outside knowledge. Never forecast, estimate or guess.
- If the evidence does not directly answer the question (is it overvalued, is it safe, why did it move, what do
  analysts think), never write "I don't know" or "I do not know" and never open with what is missing. Open with
  the closest facts the sheets DO list (price, recent returns, 52-week range, P/E ratio, dividend, sales and
  profit growth), each exactly as shown, add the everyday-words sentence, and only then say in one short sentence
  which thing the data here does not list. Set status to ANSWERED when you gave such facts.
  Never answer "Yes" or "No" unless a sheet figure directly settles it: with only market data on the sheets, a
  question about profit, sales or growth gets the price facts and one sentence saying the data here does not
  list sales or profit, never "Yes". Never write a sentence about a sheet that is missing.
- If the question asks for a bear case, a bull case, pros and cons, or strengths and weaknesses: write two
  labelled parts and you may use up to 9 sentences. Start one sentence with "Bear case:" and follow it with 1 to
  3 more sentences; each gives one sheet fact a cautious investor would point to (a falling price, the distance
  below the 52-week high, falling profit or margin, a new risk factor) and a few plain words on why it worries
  them. Start one sentence with "Bull case:" and follow it with 1 to 3 more sentences; each gives one sheet fact
  an optimistic investor would point to (sales or profit growth, a dividend, market capitalization, a rising
  price). If only one side was asked for, give that side first and still add the other in one or two sentences.
  Use only sheet facts, state no forecast, and never say which case is right. End with the "What it means:"
  sentence.
- Only when no sheet fact is related at all (a forecast, a price target, a quarter the sheets do not list), set
  status to I_DONT_KNOW and say in one sentence that the data here doesn't cover it.
- No investment advice. Do not say whether to buy, sell or hold. Market numbers are past data, never a view on
  what to do.
- 2 to 4 short sentences. Do not show fact ids in the answer.
- First sentence: answer the question directly when it can be answered that way ("Yes, that is right.",
  "No, that is not right.", "Net income grew faster."), then give the figures. Every sentence is a full sentence
  that names its measure: never write a bare number such as "$20.2 billion." on its own. If asked for a dollar
  change, write it with its measure and a change word (e.g. "Net income rose by $X to $Y in fiscal 2026.").
- One measure per sentence. Put the year right after each number, and give the prior-year figure and the change in the
  SAME sentence as the headline number (e.g. "Gross margin was 48.8% in fiscal 2026, up from 46.9% in fiscal 2025.").
  When the sheet lists the percent change (or the change in percentage points) for that measure, include it in that
  same sentence, written exactly as the sheet shows it (e.g. "..., up from $X in fiscal 2025, a rise of Y%.").
  Never put a number in a separate "That is up from..." or "The rise of X% means..." follow-up sentence.
- Your last sentence is an everyday-words sentence with NO numbers, no percentages and no other metric names
  (e.g. "So Apple kept more of each sales dollar."). Say only what the figures already show, never a cause.
- Shape of a normal answer: the first sentence is a one-line direct answer to the question. Then give 4 to 6 short
  stat sentences when the sheets hold that many relevant figures (fewer rather than padding with unrelated ones),
  one or two figures each. Then one "What it means: ..." sentence in plain words for a beginner, with NO numbers.
  Then one "Deeper read: ..." sentence (at most 18 words, NO numbers) that names one thing in the data worth looking
  at next, with no cause and no forecast. At most 110 words in all. Do not restate every figure (the page shows key
  numbers as tiles). Each figure exactly as the sheet shows it and listed in claims. State no cause, no forecast
  and no view on the stock.
- If the question assumes a move or fact the sheets contradict, the first sentence says the data shows something
  different and gives the real figure with its period.
- If the question asks about a date or year the sheets do not show, the first sentence names the period the data
  covers, then gives the closest figures.
- Never write the internal words "evidence sheet", "sheets" or "in this demo" in the answer: say "the data". Define
  a finance term at most once per answer. For an ETF or trust say "the fund", not "the stock".
- Never work out a figure yourself. A ratio, margin, average or difference that is not printed on a sheet (for
  example operating margin or net margin) must not appear as a number: any number that is not on a sheet is cut.
  If asked for one, say in the first sentence that the data here does not list it, then give the sheet figures it
  is built from, each in its own sentence, and end with the everyday-words sentence.
- Every number you write must be listed in claims with the fact_id it came from, and written exactly as the
  sheet shows it.
- Write time windows in words ("over the past year", "since the start of the year"), never digits, except "52-week".
- Write dates exactly as the sheet shows them (YYYY-MM-DD). Say "fiscal 2026" for fiscal years.
- Do not state counts of things.
- If the question contains a wrong number or wrong claim, never repeat the user's wrong number. Say it is not right
  and state the true value from the sheets. (A sentence holding a number that is not in the sheets gets cut.)
- For a comparison or "which grew faster" question, state both numbers in separate short sentences, each sentence
  about one measure with its own figure (e.g. "Net income rose X%." "Revenue rose Y%."), then say which is larger.
- If asked about a percentage measure (like gross margin percent), give the percentage itself in a short sentence of
  its own (e.g. "Gross margin was X% in fiscal 2026."), not only the dollar figure.
- If a source is listed under UNAVAILABLE, do not guess that part and do not apologise at length; code adds a notice.
- Never describe news content. If headlines exist you may say that recent headlines are listed below.
- If the question is a follow-up that depends on an earlier question you cannot see (for example "And the year before?" or "How does that compare?"), say in the first sentence which measure and year you are assuming.
- If you quote a filing, copy the words exactly and list it in claims as a quote with its filing year.

Reply with JSON only, no other text:
{"status": "ANSWERED" or "I_DONT_KNOW",
 "answer": "...",
 "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"},
            {"type": "quote", "text": "exact words", "filing": "FY2026"}]}"""


def writer_human(inp: dict) -> str:
    """The writer's prompt: company, evidence sheets, unavailable sources, question. Shared with the council."""
    sheets = "\n\n".join(f"EVIDENCE SHEET {n}:\n{s}" for n, s in enumerate(inp.get("sheets") or [], 1))
    unavailable = inp.get("unavailable") or []
    unav = ("UNAVAILABLE (do not guess these parts):\n" +
            "\n".join(f"- {u.get('agent')}: {u.get('reason')}" for u in unavailable)) if unavailable else ""
    news = "Recent headlines exist and are listed below your answer by code." if inp.get("has_news") else ""
    return "\n\n".join(p for p in [
        f"Company: {inp.get('company') or inp.get('ticker')} ({inp.get('ticker')})", sheets, unav, news,
        f"Question: {inp.get('question', '')}"] if p)


def write(inp: dict, config=None) -> dict:
    from backend import ask  # lazy: ask may import desk, which imports agents

    human = writer_human(inp)
    obj, name = call_json(writer_models(bool(inp.get("long_form"))), WRITER_SYSTEM, human, config, need_key="answer")
    if obj is None:
        return {"draft": dict(FAIL_DRAFT, claims=[]), "model": None}
    draft = ask._parse(json.dumps(obj))
    if not isinstance(draft.get("answer"), str) or not isinstance(draft.get("claims"), list):
        return {"draft": dict(FAIL_DRAFT, claims=[]), "model": name}
    draft["claims"] = [c for c in draft["claims"] if isinstance(c, dict)]
    return {"draft": draft, "model": name}


# ---------------------------------------------------------------- skeptic
SKEPTIC_SYSTEM = """You are an adversarial reviewer from a different model family than the writer.
Try to refute each numbered sentence of the draft answer using ONLY the evidence sheets.

For each sentence give one verdict:
- "UNSUPPORTED" only if you can name the evidence line that contradicts it, or the sentence states a cause,
  a direction, a metric/year pairing or a comparison that the evidence does not support.
  A plain "larger / smaller / up / down / more than" statement IS supported when the numbers on the sheets make it true.
  Mark UNSUPPORTED only when the sentence contradicts a specific figure or direction on the sheets, and in "why" name
  that figure (its fact id or value). Also UNSUPPORTED: a wrong number, a wrong year, a number attached to the wrong
  metric, an invented cause (for example "because of iPhone demand"), a forecast.
- Correct arithmetic consequences of sheet figures are SUPPORTED: a difference between two sheet figures, "grew faster
  than" when one sheet growth rate is larger than another, "kept more profit from each sales dollar" when a margin
  percent rose or profit grew faster than sales, "a bigger share of sales" when a cost grew faster than sales.
  Plain-English definitions of finance terms and everyday restatements of a sheet figure are SUPPORTED, never
  UNSUPPORTED just because the sheet does not contain the definition words. A quote of filing text is SUPPORTED when
  its words appear on the sheets.
- A sentence that rejects a wrong premise in the question ("that is not right", "did not fall", "no drop to explain")
  is SUPPORTED when the sheets show the opposite direction or a different value. Mark it UNSUPPORTED only if the
  sheets actually back the user's premise.
- "ADVICE" if it tells the reader what to do with money or predicts returns.
- Otherwise "SUPPORTED".
Sentences that only say data is unavailable, or that Europa does not know, are always SUPPORTED. So is "the data
here does not cover X" for anything the sheets do not list (a product line such as iPhone or wearables revenue, a
quarter, a ratio, a forecast, another date): the sheets not listing it is exactly what makes that sentence true.
The evidence sheets are about the company on the "Company:" line only. If the question names another company
or ticker, the sheets still describe only that one company: a sentence saying the data does not cover another
company is SUPPORTED, and a sentence that gives a sheet number as another company's figure is UNSUPPORTED.

Reply with JSON only:
{"verdicts": [{"i": 1, "verdict": "SUPPORTED", "why": ""}]}"""


def review(inp: dict, config=None) -> dict:
    sentences = list(inp.get("sentences") or [])
    sheets = "\n\n".join(f"EVIDENCE SHEET {n}:\n{s}" for n, s in enumerate(inp.get("sheets") or [], 1))
    numbered = "\n".join(f"{n}. {s}" for n, s in enumerate(sentences, 1))
    company = f"Company: {inp.get('company') or inp.get('ticker') or 'unknown'} ({inp.get('ticker') or 'unknown'})"
    human = f"{company}\nQuestion: {inp.get('question', '')}\n\n{sheets}\n\nDRAFT SENTENCES:\n{numbered}"
    obj, name = call_json(SKEPTIC_MODELS, SKEPTIC_SYSTEM, human, config, need_key="verdicts")
    if obj is None or not isinstance(obj.get("verdicts"), list):
        return {"status": "unavailable", "verdicts": [], "model": None}
    out, seen = [], set()
    for v in obj["verdicts"]:
        if not isinstance(v, dict):
            continue
        i = v.get("i")
        if isinstance(i, str) and i.strip().isdigit():
            i = int(i.strip())
        if isinstance(i, bool) or not isinstance(i, int):  # 1e999, 1.5, true: not a sentence number
            continue
        verdict = str(v.get("verdict", "")).strip().upper()
        if not 1 <= i <= len(sentences) or verdict not in VERDICTS or i in seen:
            continue
        seen.add(i)
        out.append({"i": i, "verdict": verdict, "why": str(v.get("why") or "")[:300]})
    return {"status": "ok", "verdicts": out, "model": name}


ROUTER = RunnableLambda(route, name="desk_router")
NEWS_PICKER = RunnableLambda(pick_news, name="news_picker")
WRITER = RunnableLambda(write, name="write_answer")
SKEPTIC = RunnableLambda(review, name="skeptic_review")
