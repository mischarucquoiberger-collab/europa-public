"""number_gate: the final word on every answer from the multi-agent desk. Pure code, no model calls.

Order (fails closed at each step):
1. skeptic deletions (REFUTED) -> 2. advice-phrase filter (ADVICE) -> 3. checker.check() over SEC facts plus
market-data facts minus quarantined ids -> 4. naked-number sweep (UNCHECKABLE) -> 5. status.
"""
import re

from langchain_core.runnables import RunnableLambda

from backend import checker

FALLBACK = "I couldn't verify that answer against my sources, so I won't show it."
IDK_FALLBACK = "The data I have doesn't answer that, so I won't guess."

ADVICE_PHRASES = [re.compile(p, re.I) for p in (
    r"\byou should\b",
    r"\bi (would )?recommend\b",
    r"\b(is|looks like) a (good|great|strong|bad) (buy|investment|time to)\b",
    r"\b(buy|sell|hold) (rating|now|the stock|shares)\b",
    r"\bworth (buying|selling)\b",
    r"\bwill (rise|fall|go up|go down|outperform)\b",
)]

# Digits that are not claims: fiscal years, SEC form names, risk-factor items, quarters, and the time windows
# the market sheet has facts for (the checker ties a return to the window its sentence names).
GENERIC_ALLOWED = [re.compile(p, re.I) for p in (
    r"\bFY\s?\d{4}\b",
    r"\b(10-K|10-Q|8-K|13-F|20-F)\b",
    r"\bItem\s+\d+[A-Z]?\b",
    r"\bQ[1-4]\b",
    r"\b(?:1[- ](?:day|week|month|year)|5[- ](?:trading[- ])?days?|3[- ]months?|12[- ]months?)\b",
)]
# A bare year is allowed only where a year is read as a year ("in 2026", "fiscal 2026", "Apple's 2026 10-K").
# "Apple has 2026 retail stores" is a count and is not allowed.
YEAR = re.compile(r"\b(?:19|20)[0-9]{2}\b")
_YEAR_LEAD = re.compile(
    r"(?:[(\[\"\u201c]|['\u2019]s\s+|[0-9]\s?[-\u2013/]\s?|\b(?:fiscal|fy|in|for|of|during|since|from|to|through|"
    r"throughout|until|by|before|after|and|or|vs\.?|versus|with|than|the|its|their|both|years?|calendar|late|early|"
    r"mid|end|ended|ending|between|into|over|across|beyond|q[1-4]|" + checker._MONTHS + r")\s+)$", re.I)
DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Numbers written without digits. The checker cannot read them, so the sentence is cut.
_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
         r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)")
WORD_NUMBERS = [re.compile(p, re.I) for p in (
    r"\b(?:hundred|thousand|million|billion|trillion)\b",  # a scale word no checked number covers
    rf"\b{_WORD}(?:[- ]{_WORD})?[\s-]+(?:percent|per cent|percentage points?|basis points?|dollars?|cents?|times)\b",
    r"\b(?:doubl|tripl|trebl|quadrupl|quintupl|sextupl|octupl|halv)\w*|\btwice\b|\bthrice\b",
    r"\b(?:single|double|triple)[- ]digits?\b",  # a size in words; sweep() lets it through only when the facts agree
    # "grew by a quarter", "rose a third" (a size). "in the fourth quarter" / "a quarter ago" are not matched.
    r"\b(?:by|grew|rose|up|down|fell|increased|decreased|dropped|gained|jumped|climbed|declined|shrank)\s+"
    r"(?:about |roughly |nearly |almost |over |just )?(?:a|one)\s+(?:quarter|third|fifth|tenth)\b",
    rf"\b(?:{_WORD}|[0-9]+)[- ]?fold\b",
    r"\b(?:a|one|by|in|about|roughly|nearly|almost|over|than)\s+half\b|\bhalf (?:of|as)\b",
    r"\b(?:one|two|three|a)[- ](?:third|fifth|tenth)s?\b|\ba quarter of\b",
)]

_VALID_KINDS = ("usd", "usd_per_share", "pct", "pts", "count")


expand_dates = checker.expand_dates  # moved to the checker, which also ties a market number to its date


_DIGIT_RATE = re.compile(r"\b(single|double|triple)[- ]digits?\b", re.I)
_RATE_FACT = {"revenue": "revenue_change_pct", "gross_margin": "gross_margin_change_pct", "rnd": "rnd_change_pct",
              "operating_income": "operating_income_change_pct", "net_income": "net_income_change_pct",
              "eps_diluted": "eps_diluted_change_pct", "cash": "cash_change_pct", "buybacks": "buybacks_change_pct"}
_RATE_UP = re.compile(r"\b(?:grew|grow\w*|rose|rise|rising|increas\w*|up|climb\w*|gain\w*|jump\w*|expand\w*|surg\w*)\b", re.I)
_RATE_DOWN = re.compile(r"\b(?:fell|fall\w*|declin\w*|decreas\w*|down|dropp?\w*|shr[ua]nk|shrink\w*|slid\w*|contract\w*)\b", re.I)


def _digit_rate_ok(sentence: str, word: str) -> bool:
    """True when "single/double/triple-digit" matches how the sentence's metric really changed (facts.py)."""
    fams = checker._families(sentence) & set(_RATE_FACT)
    if not fams:
        return False
    pool = checker.fact_pool("AAPL")
    up, down = bool(_RATE_UP.search(sentence)), bool(_RATE_DOWN.search(sentence))
    if up and down:
        return False
    for fam in fams:
        f = pool.get(_RATE_FACT[fam])
        if not f:
            return False
        v = float(f["value"])
        size = abs(v)
        if {"single": size < 10, "double": 10 <= size < 100, "triple": size >= 100}[word.lower()] is False:
            return False
        if (up and v < 0) or (down and v > 0):
            return False
    return True


def sweep(text: str, allow_text=(), allow_dates=()) -> list[str]:
    """Number tokens in `text` that nothing covers (not a checked number, allowed literal, date, year or form name).
    Also returned: numbers written as words ("fifty percent", "doubled"), which the checker cannot read."""
    text = text or ""
    mask = list(text)

    def blank(a, b):
        for i in range(a, b):
            mask[i] = " "

    # (a) numbers the checker understands (by the time we sweep, these are all VERIFIED)
    for n in checker.find_numbers(text):
        blank(n["start"], n["start"] + len(n["text"]))
    # (b) allowed literals and dates, longest first, case-insensitive
    literals = [str(t) for t in (allow_text or ()) if t] + expand_dates(allow_dates)
    for lit in sorted(set(literals), key=len, reverse=True):
        # digit guards: "Nov 2" must not swallow the front of "Nov 20"
        for m in re.finditer(r"(?<![0-9])" + re.escape(lit) + r"(?![0-9])", text, re.I):
            blank(m.start(), m.end())
    # (c) generic patterns, then years that are written as years
    for rx in GENERIC_ALLOWED:
        for m in rx.finditer(text):
            blank(m.start(), m.end())
    for m in YEAR.finditer(text):
        lead = text[:m.start()]
        if not lead.strip() or lead.rstrip()[-1:] in ".!?" or _YEAR_LEAD.search(lead):
            blank(m.start(), m.end())
    for m in _DIGIT_RATE.finditer(text):
        if _digit_rate_ok(text, m.group(1)):
            blank(m.start(), m.end())
    left = "".join(mask)
    return [m.group(0) for m in DIGITS.finditer(left)] + [m.group(0) for rx in WORD_NUMBERS for m in rx.finditer(left)]


def _clean_facts(facts) -> dict:
    """Keep only well-formed facts, so one bad pack cannot crash the checker."""
    out = {}
    if not isinstance(facts, dict):
        return out
    for fid, f in facts.items():
        if not isinstance(fid, str) or not isinstance(f, dict):
            continue
        try:
            value = float(f.get("value"))
        except (TypeError, ValueError):
            continue
        if value != value or f.get("kind") not in _VALID_KINDS:  # NaN or unknown kind
            continue
        out[fid] = {**f, "value": value, "label": str(f.get("label", fid)), "source": str(f.get("source", "unknown"))}
    return out


def _as_list(x):
    if isinstance(x, (list, tuple, set)):
        return list(x)
    return []


def _final_check(ticker, draft, packs, verdicts):
    answer = draft.get("answer") or ""
    if not isinstance(answer, str):
        answer = str(answer)
    sentences = checker.split_sentences(answer)

    # (1) skeptic deletions
    refuted, drop = [], {}
    for v in _as_list(verdicts):
        if not isinstance(v, dict):
            continue
        try:
            i = int(v.get("i"))
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(sentences) and str(v.get("verdict", "")).upper() in ("UNSUPPORTED", "ADVICE"):
            drop.setdefault(i, str(v.get("why") or ""))
    remaining = []
    for idx, s in enumerate(sentences, start=1):
        if idx in drop:
            refuted.append(dict(text=s, status="REFUTED", note="Skeptic (second model): " + drop[idx]))
        else:
            remaining.append(s)

    # (2) advice-phrase filter
    advice, kept = [], []
    for s in remaining:
        if any(rx.search(s) for rx in ADVICE_PHRASES):
            advice.append(dict(text=s, status="ADVICE", note="Europa does not give investment advice."))
        else:
            kept.append(s)

    # (3) checker over SEC + extra facts from ok packs, minus quarantined ids (taken from EVERY pack)
    extra, exclude, allow_text, allow_dates = {}, set(), [], []
    for p in _as_list(packs):
        if not isinstance(p, dict):
            continue
        exclude.update(str(x) for x in _as_list(p.get("exclude")))
        if p.get("status") != "ok":
            continue
        for fid, f in _clean_facts(p.get("facts")).items():
            # dates a sentence may put next to this number: the fact's own date or the pack's last trading day
            # a daily-bar fact (a close, open, high, low, volume or return) is bound to its own date only, so a
            # Nov 19 close cannot be stated as Nov 20 (Codex #3); the pack's day is a fallback when it has none.
            # Other facts (market cap) may also carry the pack's last trading day.
            bar = fid.startswith(("px_", "ret_", "volume"))
            own = (f.get("as_of"),) if bar and f.get("as_of") else (f.get("as_of"), p.get("as_of"))
            dates = [str(d) for d in own if d]
            extra[fid] = {**f, "dates": dates} if dates else f
        allow_text += [str(x) for x in _as_list(p.get("allow_text")) if x]
        if "px_52w_high" in extra or "px_52w_low" in extra:
            allow_text += ["52 weeks", "52-weeks"]  # "over the past 52 weeks": the checker ties the figures to the 52-week facts
        allow_dates += [str(x) for x in _as_list(p.get("allow_dates")) if x]
    model_claims = [c for c in _as_list(draft.get("claims")) if isinstance(c, dict)]
    res = checker.check(ticker, " ".join(kept), model_claims, extra, sorted(exclude))

    # (4) naked-number sweep, sentence by sentence
    quote_texts = {c.get("text") for c in model_claims if c.get("type") == "quote" and c.get("text")}
    quote_texts |= set(checker.quoted_spans(" ".join(kept)))
    allow_text += [c["text"] for c in res["claims"] if c.get("status") == "VERIFIED" and c.get("text") in quote_texts]
    claims, unchecked, final, seen = list(res["claims"]), [], [], set()
    for s in checker.split_sentences(res["answer"]):
        leftover = sweep(s, allow_text, allow_dates)
        if not leftover:
            final.append(s)
            continue
        unchecked.append(dict(text=s, status="UNCHECKABLE", note="Contains a number Europa cannot check against a source."))
        for tok in leftover:
            if tok not in seen:
                seen.add(tok)
                claims.append(dict(text=tok, status="UNCHECKABLE", source=None, sec_value=None,
                                   note="Europa has no source to check this number against."))

    # (5) status
    status = draft.get("status")
    if status not in ("ANSWERED", "I_DONT_KNOW"):
        status = "ANSWERED"
    out_answer = " ".join(final).strip()
    if not out_answer:
        # the writer already said it did not know: say that plainly instead of "couldn't verify"
        out_answer = IDK_FALLBACK if status == "I_DONT_KNOW" else FALLBACK
        status = "I_DONT_KNOW"
    return dict(status=status, answer=out_answer, claims=claims, blocked=refuted + advice + res["blocked"] + unchecked)


def final_check(ticker: str, draft: dict, packs: list[dict], verdicts: list[dict] | None = None) -> dict:
    """Return {status, answer, claims, blocked}. Never raises: on any internal error it shows nothing."""
    try:
        if not isinstance(draft, dict):
            raise TypeError("draft must be a dict")
        return _final_check(str(ticker or "").upper(), draft, packs, verdicts)
    except Exception:  # fail closed
        return dict(status="I_DONT_KNOW", answer=FALLBACK, claims=[], blocked=[])


def _gate(inp: dict) -> dict:
    return {**inp, "result": final_check(inp["ticker"], inp["draft"], inp.get("packs", []), inp.get("verdicts"))}


GATE = RunnableLambda(_gate, name="number_gate")
