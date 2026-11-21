"""Follow-up helpers, pure code (no model, no network): turn "and Microsoft?" into a full question, build clickable
next questions, and spot a two-company comparison. Company words come from tickers.NAMES only."""
from __future__ import annotations

import re

from backend import tickers

_WORDY = {"COST", "SNOW", "SPOT", "SHOP", "COIN", "HOOD", "DIS"}   # real words: not a ticker when typed in lower case
_Q_START = re.compile(r"^(what|how|why|is|are|does|do|did|has|have|should|can|could|who|when|where|which|will)\b", re.I)
_PREFIX = re.compile(r"^\W*(?:and now|and for|and|what about|how about|what of|same for|same with|do the same for|now do|now|also|then|try)\s+", re.I)
_ANGLE_PREFIX = re.compile(r"^\W*(?:and|what about|how about|also|then)\s+", re.I)
_TIME = re.compile(
    r"(?:over |in |during |for )?(?:the )?(?:last |past )?(?:\d+|one|two|three|five|ten) ?-? ?(?:years?|months?|weeks?|days?)|"
    r"(?:this|last) (?:year|month|week|quarter)|today|yesterday|year to date|ytd|in (?:19|20)\d\d|"
    r"(?:over )?(?:the )?(?:past|last) (?:year|month|week|decade)", re.I)
_TOPIC_WORDS = {"why", "dividend", "dividends", "revenue", "risks", "risk", "chart", "news", "price"}


def _find(text: str):
    """(position, ticker, matched text) for each company in text, left to right, one per ticker."""
    hits = []
    for m in tickers._NAME_RX.finditer(text):
        tail, head = text[m.end():m.end() + 7].lower(), text[max(0, m.start() - 6):m.start()].lower()
        if m.group(1).lower() == "target" and ("price" in tail or "price" in head):
            continue
        hits.append((m.start(), tickers.NAMES[m.group(1).lower()], m.group(0), m.end()))
    for m in re.finditer(r"\$([A-Za-z]{1,5})\b", text):
        hits.append((m.start(), m.group(1).upper(), m.group(0), m.end()))
    for m in re.finditer(r"\b[A-Za-z]{3,5}\b", text):
        t = m.group(0)
        up = t.upper()
        if up in tickers._KNOWN and up not in tickers._STOP and not (t.islower() and up in _WORDY):
            if t.isupper() or t.islower():
                hits.append((m.start(), up, t, m.end()))
    hits.sort()
    out, seen = [], set()
    for pos, tk, txt, end in hits:
        if tk in seen:
            continue
        if any(pos < e and end > p for p, _, _, e in out):
            continue
        seen.add(tk)
        out.append((pos, tk, txt, end))
    return out


def _pretty(txt: str, tk: str) -> str:
    if txt.startswith("$"):
        return tk
    if txt.isupper() or txt.lower() == tk.lower():
        return tk if txt.lower() == tk.lower() else txt
    return " ".join(w[:1].upper() + w[1:] for w in txt.split())


def _stem(q: str) -> str:
    return q.strip().rstrip("?!. ").strip()


def resolve(question: str, last_question: str) -> str:
    q, last = (question or "").strip(), (last_question or "").strip()
    if not q or not last:
        return q
    words = re.findall(r"[\w'$&./-]+", q)
    if len(words) > 8:
        return q
    low = q.lower().strip(" ?!.")
    if re.fullmatch(r"(and )?why( is that| so| though)?", low):
        return f"{_stem(last)}, and why is that the case?"
    m = _PREFIX.match(q)
    if not m:
        return q
    rest = q[m.end():].strip().rstrip("?!. ").strip()
    if not rest or _Q_START.match(rest) and not re.match(r"^(why)\b", rest, re.I):
        return q
    # 1) a new company, same topic
    found = _find(rest)
    new = None
    if found and len(rest.split()) <= 3 and len(found) == 1:
        pos, tk, txt, end = found[0]
        leftover = (rest[:pos] + rest[end:]).replace("'s", "").strip(" .,'")
        if not leftover or re.fullmatch(r"(the |for |with |on )?", leftover, re.I):
            new = _pretty(txt, tk)
    elif not found and 1 <= len(rest.split()) <= 2 and all(w[:1].isupper() for w in rest.split()) \
            and rest.lower() not in _TOPIC_WORDS and not _TIME.search(rest) and _ANGLE_PREFIX.match(q) or \
            (not found and 1 <= len(rest.split()) <= 2 and all(w[:1].isupper() for w in rest.split())
             and rest.lower() not in _TOPIC_WORDS and not _TIME.search(rest) and re.match(r"^\W*(same for|same with|now do|do the same for)", q, re.I)):
        new = rest
    if new:
        old = _find(last)
        if old:
            pos, tk, txt, end = old[0]
            return last[:pos] + new + last[end:]
        return f"{_stem(last)} for {new}?"
    if not _ANGLE_PREFIX.match(q) or found or _Q_START.match(rest) and rest.lower() != "why" or len(rest.split()) > 5:
        return q
    # 2) same company, new angle
    if rest.lower() == "why":
        return f"{_stem(last)}, and why is that the case?"
    tm = _TIME.search(rest)
    lt = _TIME.search(last)
    if tm and lt and tm.group(0).strip() == rest.strip():
        return last[:lt.start()] + tm.group(0).strip() + last[lt.end():]
    return f"{_stem(last)}, {rest}?"


# ---- suggestions ----------------------------------------------------------------------------------------------
_TOPICS = {
    "price": (r"this year|year to date|ytd|how has .{0,40}(done|moved|performed)|price (move|change)|performance|moved|stock doing",
              lambda n: f"How has {n} done this year?"),
    "chart": (r"chart|graph|plot", lambda n: f"Show me a chart of {n} over 6 months"),
    "bear": (r"\bbear", lambda n: f"What is the bear case for {n}?"),
    "bull": (r"\bbull", lambda n: f"What is the bull case for {n}?"),
    "dividend": (r"dividend|yield", lambda n: f"Does {n} pay a dividend?"),
    "range": (r"52|range|\bhigh\b|\blow\b", lambda n: f"Where is {n} compared with its 52-week high and low?"),
    "recent": (r"recent|happen|news|yesterday|today|lately|this week", lambda n: f"What happened to {n} recently?"),
    "revenue": (r"revenue|sales|growth|grow", lambda n: f"How fast has {n}'s revenue grown?"),
    "risk": (r"\brisks?\b|risk factors?", lambda n: f"What new risk factors did {n} add?"),
}
_STARTERS = ["What happened to Nvidia yesterday?", "Does Apple pay a dividend?", "What is a P/E ratio?"]


def suggest(question: str, ticker: str, status: str, name: str = "") -> list[str]:
    n = (name or ticker or "").strip() or "this stock"
    q = question or ""
    if status == "CHAT":
        return list(_STARTERS)
    asked = {k for k, (rx, _) in _TOPICS.items() if re.search(rx, q, re.I)}
    if status == "I_DONT_KNOW":
        order = ["price", "bear", "dividend", "recent"]
        return [_TOPICS[k][1](n) for k in order if k not in asked][:2] or [_TOPICS["price"][1](n), _TOPICS["bear"][1](n)]
    order = ["price", "bear", "bull", "dividend", "range", "recent", "chart"]
    if (ticker or "").upper() == "AAPL":
        order = ["revenue", "risk", "bear", "price", "dividend", "range", "recent", "bull", "chart"]
    return [_TOPICS[k][1](n) for k in order if k not in asked][:3]


# ---- two-company comparison -------------------------------------------------------------------------------------
_CUE = re.compile(r"\b(compare[ds]?|comparison|vs\.?|versus|against|or|and|between|better|worse|beat|which)\b", re.I)


def pair(question: str):
    q = question or ""
    found = _find(q)
    if len(found) != 2 or not _CUE.search(q):
        return None
    a, b = found[0][1], found[1][1]
    return (a, b) if a != b else None
