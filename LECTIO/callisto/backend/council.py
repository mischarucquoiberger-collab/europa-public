"""Europa council: three models from three companies answer the same question on the same evidence sheets,
then code compares their numbers and one final answer is written from what they agree on.

Round 1 (parallel): council_claude, council_gpt, council_mistral each return the writer JSON {status, answer, claims}.
Compare (code):     per fact id, AGREED = every member that answered gave the same value, MAJORITY = two of three,
                    DISPUTED = different values and no two members agree, SOLO = only one member used the fact.
Round 2 (merge):    if a member's draft uses only AGREED / MAJORITY facts it is kept as it is; otherwise Claude
                    rewrites the answer from the confirmed facts only. DISPUTED fact ids are handed to the number
                    gate as exclusions, so code (not a model) cuts any sentence that still uses one.
The skeptic and the number gate run afterwards exactly as before. The council never raises: with fewer than two
members answering it reports ok=False and the desk uses the single writer.
Every model call goes through llm.model(). Switch: EUROPA_COUNCIL=on|off (default OFF since the 2026-11-21 review:
the single writer is the proven path; the council is opt-in).
Publish rule (2026-11-21 review): a draft is published only when code confirmed every claim and every number in its
text; otherwise the council reports ok=False and the desk uses the single writer.
Time limits: EUROPA_COUNCIL_TIMEOUT (default 20 s) is how long the first two answers are waited for;
EUROPA_COUNCIL_SOFT (default 9 s) is how long the third member gets once two have answered.
"""
import contextvars
import json
import os
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from langchain_core.runnables import RunnableLambda

from backend import agents, checker, llm

def bind_for(model_name: str) -> dict:
    """Extra request parameters a model needs. mistral-large-4 on Nicrron rejects the default request: it needs
    reasoning_effort, and top_p=1 with temperature 0 (live check 2026-11-21: without them the provider answers
    400 "reasoning_effort none is not supported"; mistral-medium-3.5 and large-3 reject reasoning_effort)."""
    return {"reasoning_effort": "low", "top_p": 1} if "mistral-large-4" in model_name else {}


def _member(key: str, label: str, env: str, default: str) -> dict:
    name = os.environ.get(env) or default
    return {"key": key, "label": label, "model": name, "bind": bind_for(name)}


# Mistral member: mistral-large-3 by default. Measured live 2026-11-21 with the writer prompt: large-3 answered in
# 3.8 to 4.8 s; large-4 (reasoning, cannot be switched off) took 3 to 20+ s and missed the 9 s soft limit on 7 of 13
# test-plan questions. MODEL_COUNCIL_MISTRAL=mistral/mistral-large-4 switches back (reasoning_effort is then added).
MEMBERS = (
    _member("claude", "Claude", "MODEL_COUNCIL_CLAUDE", "anthropic/claude-sonnet-5-5"),
    _member("gpt", "GPT", "MODEL_COUNCIL_GPT", "openai/gpt-5.4"),
    _member("mistral", "Mistral", "MODEL_COUNCIL_MISTRAL", "mistral/mistral-large-3"),
)
MERGE_MODELS = [MEMBERS[0]["model"], MEMBERS[1]["model"]]  # Claude writes the merge; GPT only if Claude is down
CONFIRMED = ("AGREED", "MAJORITY")
MAX_ANSWER = 4000  # characters of one member answer that are kept
NO_DATA = "I don't know: the data Europa has does not cover this."
_ID_RX = re.compile(r"[A-Za-z0-9_.:\-]{1,80}")


def enabled() -> bool:
    return os.environ.get("EUROPA_COUNCIL", "off").strip().lower() in ("on", "1", "true", "yes")


def member_timeout() -> float:
    try:
        return max(0.05, float(os.environ.get("EUROPA_COUNCIL_TIMEOUT", "20")))
    except ValueError:
        return 20.0


def soft_timeout() -> float:
    """Once two members have answered, the last one is only waited for until this many seconds after the start.
    Keeps a question near 12 s when one model is slow (live 2026-11-21: Mistral took 3 to 20+ s)."""
    try:
        return max(0.0, float(os.environ.get("EUROPA_COUNCIL_SOFT", "9")))
    except ValueError:
        return 9.0


def _row(name, kind, model=None, status="ok", note="", seconds=0.0) -> dict:
    return {"name": name, "kind": kind, "model": model, "status": status, "note": note,
            "seconds": round(float(seconds or 0), 2)}


# ---------------------------------------------------------------- round 1: one member
def _text(content) -> str:
    """Model reply as plain text. Reasoning models return a list of blocks; only the text blocks are the answer."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
        return "\n".join(parts)
    return str(content or "")


def clean_draft(obj) -> dict | None:
    """A writer draft with the right shape, or None."""
    if not isinstance(obj, dict) or not isinstance(obj.get("answer"), str) or not obj["answer"].strip():
        return None
    claims = obj.get("claims")
    return {"status": "I_DONT_KNOW" if obj.get("status") == "I_DONT_KNOW" else "ANSWERED",
            "answer": obj["answer"][:MAX_ANSWER],
            "claims": [c for c in claims if isinstance(c, dict)] if isinstance(claims, list) else []}


def _ask_member(spec: dict, inp: dict, config=None) -> dict:
    try:
        m = llm.model(spec["model"])
        if spec.get("bind"):
            m = m.bind(**spec["bind"])
        msg = m.invoke([("system", agents.WRITER_SYSTEM), ("human", agents.writer_human(inp))], config=config)
        draft = clean_draft(agents._last_json(_text(msg.content), "answer"))
        if draft is None:
            return {"status": "failed", "draft": None, "note": "reply was not a usable draft"}
        return {"status": "ok", "draft": draft, "note": f"draft {draft['status']}"}
    except Exception as e:  # noqa: BLE001  a member never crashes the council
        return {"status": "failed", "draft": None, "note": f"model call failed ({type(e).__name__})"}


def member_runnable(spec: dict) -> RunnableLambda:
    def run(inp: dict, config) -> dict:
        return _ask_member(spec, inp, config)
    return RunnableLambda(run, name=f"council_{spec['key']}")


# ---------------------------------------------------------------- compare (code)
def value_key(text) -> tuple:
    """A claim value as something comparable:
    ('num', kind, value, tol, written, written_tol, sign, scaled) or ('str', text).
    sign: -1 / +1 when the text has an explicit minus / plus before the number, 0 when it states none.
    scaled: the number carries a word such as "billion", so its digits alone are not its value."""
    v = str(text if text is not None else "").replace("−", "-").replace("–", "-")
    v = re.sub(r"\s+", " ", v).strip()
    sm = re.match(r"^[^0-9]*?([+-])\s*\$?\s*\.?[0-9]", v)
    sign = 0 if not sm else (-1 if sm.group(1) == "-" else 1)
    nums = checker.find_numbers(v)
    if nums:
        n = nums[0]
        dec = len(n["raw"].split(".")[1]) if "." in n["raw"] else 0
        written = float(n["raw"])
        return ("num", n["kind"], n["value"], n["tol"], written, 0.5 * 10 ** -dec + 1e-9, sign,
                abs(n["value"] - written) > 1e-9)
    m = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", v)
    if m:
        raw = m.group(0).replace(",", "")
        dec = len(raw.split(".")[1]) if "." in raw else 0
        return ("num", "bare", float(raw), 0.5 * 10 ** -dec + 1e-9, float(raw), 0.5 * 10 ** -dec + 1e-9, sign, False)
    return ("str", v.lower())


def same_value(a: tuple, b: tuple) -> bool:
    """Same number within the rounding the writers used ("$478.8 billion" = "$478,834 million").
    An explicit minus never equals an explicit plus; bare digits never equal a scaled figure ("8.98" is not
    "$8.98 billion")."""
    if a[0] == "str" or b[0] == "str":
        return a == b
    if a[6] and b[6] and a[6] != b[6]:
        return False
    if "bare" in (a[1], b[1]):  # "8.98" next to "$8.98": compare the digits as written
        if a[7] or b[7]:
            return False
        return abs(a[4] - b[4]) <= max(a[5], b[5])
    return a[1] == b[1] and abs(a[2] - b[2]) <= max(a[3], b[3])


def _order(key: tuple) -> tuple:
    return (0, key[2], key[1]) if key[0] == "num" else (1, 0.0, key[1])


def _date_only(text: str) -> bool:
    """'2026-11-20' cited under a fact id is the fact's as-of date, not a second value for it."""
    return bool(checker._DATE_RX.search(text)) and not checker.find_numbers(text)


def claim_values(draft: dict) -> dict:
    """fact id -> every value text this draft gives for it. Quotes and as-of dates are not compared."""
    out: dict = {}
    for c in (draft or {}).get("claims") or []:
        if not isinstance(c, dict) or c.get("type") == "quote":
            continue
        fid = c.get("fact_id")
        text = str(c.get("value") if c.get("value") is not None else c.get("text") or "")
        if isinstance(fid, str) and fid.strip() and not _date_only(text):
            out.setdefault(fid.strip(), []).append(text)
    return out


def self_conflicts(draft: dict) -> set:
    """Fact ids for which this one draft gives two different values."""
    bad = set()
    for fid, texts in claim_values(draft).items():
        first = value_key(texts[0])
        if any(not same_value(first, value_key(t)) for t in texts[1:]):
            bad.add(fid)
    return bad


def sheet_values(sheets) -> dict:
    """fact id -> value text, read from 'id | what | value' lines of the evidence sheets."""
    out: dict = {}
    for sheet in sheets or []:
        for line in str(sheet).splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and _ID_RX.fullmatch(parts[0]) and parts[-1]:
                out.setdefault(parts[0], parts[-1])
    return out


def _contradicts_sheet(value_text, sheet_text) -> bool:
    """True only on a clear mismatch: both are numbers of the same kind and they differ."""
    a, b = value_key(value_text), value_key(sheet_text)
    if a[0] != "num" or b[0] != "num" or "bare" in (a[1], b[1]) or a[1] != b[1]:
        return False
    return not same_value(a, b)


def fact_claims(draft: dict) -> dict:
    """fact id -> the value text this draft gives for it (first mention; a second, different value for the
    same id is caught by self_conflicts). Quotes are not compared."""
    return {fid: texts[0] for fid, texts in claim_values(draft).items()}


def compare(drafts: dict, sheet: dict | None = None) -> dict:
    """drafts: member label -> draft, for the members that answered. sheet: fact id -> value on the evidence
    sheet; a value the members agree on that contradicts the sheet is DISPUTED, not confirmed. Pure code."""
    n = len(drafts)
    sheet = sheet or {}
    cites: dict = {}
    conflicted = set()
    for label, d in drafts.items():
        if d.get("status") != "ANSWERED":  # an abstention is not a vote for any figure
            continue
        conflicted |= self_conflicts(d)
        for fid, text in fact_claims(d).items():
            cites.setdefault(fid, {})[label] = text
    facts = {}
    for fid, by in cites.items():
        clusters = []
        for key, label, text in sorted(((value_key(t), l, t) for l, t in by.items()),
                                       key=lambda x: (_order(x[0]), x[1])):  # same result in any member order
            for c in clusters:
                if same_value(c["key"], key):
                    c["members"].append(label)
                    break
            else:
                clusters.append({"key": key, "text": text, "members": [label]})
        clusters.sort(key=lambda c: -len(c["members"]))
        top = clusters[0]
        k = len(top["members"])
        if len(clusters) == 1:
            status = "AGREED" if k == n and n >= 2 else ("MAJORITY" if k >= 2 else "SOLO")
        elif k >= 2 and len(clusters[1]["members"]) < k:
            status = "MAJORITY"
        else:
            status = "DISPUTED"
        if fid in conflicted:  # one member gave two different values for this fact
            status = "DISPUTED"
        elif status in CONFIRMED and fid in sheet and _contradicts_sheet(top["text"], sheet[fid]):
            status = "DISPUTED"  # agreement is not truth: the sheet says something else
        facts[fid] = {"status": status, "value": None if status == "DISPUTED" else top["text"],
                      "members": [] if status == "DISPUTED" else list(top["members"]),
                      "values_by_model": dict(by), "conflict": len(clusters) > 1 or fid in conflicted}
    answered = [label for label, d in drafts.items() if d.get("status") == "ANSWERED"]
    return {"n": n, "facts": facts, "vote": "ANSWERED" if len(answered) * 2 > n else "I_DONT_KNOW",
            "answered": answered,
            **{s.lower(): [fid for fid, f in facts.items() if f["status"] == s]
               for s in ("AGREED", "MAJORITY", "DISPUTED", "SOLO")}}


def _compare_step(inp: dict) -> dict:
    return compare(inp["drafts"], sheet_values(inp.get("sheets")))


COMPARE = RunnableLambda(_compare_step, name="council_compare")


# ---------------------------------------------------------------- round 2: merge
MERGE_SYSTEM = agents.WRITER_SYSTEM + """

COUNCIL RULES (these come on top of the rules above):
- Three models answered this question separately. Code compared the numbers they used.
- Use ONLY the facts listed under CONFIRMED FACTS, written exactly as shown there.
- Never use a fact listed under DISPUTED FACTS or UNCONFIRMED FACTS, and never use any other number.
- If a disputed fact is needed to answer, say in one short sentence, without digits, that the council
  could not agree on that figure.
- Every number in your answer must be one of the CONFIRMED FACTS, with a claim that names its fact id."""


def text_ok(draft: dict, cmp: dict) -> bool:
    """Every number written in the answer text equals a confirmed value that this draft claims."""
    keys = [value_key(cmp["facts"][fid]["value"]) for fid in fact_claims(draft)
            if fid in cmp["facts"] and cmp["facts"][fid]["status"] in CONFIRMED]
    for n in checker.find_numbers(str(draft.get("answer") or "")):
        if not any(same_value(value_key(n["text"]), k) for k in keys):
            return False
    return True


def claims_ok(draft: dict, cmp: dict) -> bool:
    """Every claim names a confirmed fact id and gives the confirmed value; no fact has two values."""
    if self_conflicts(draft):
        return False
    for fid, texts in claim_values(draft).items():
        f = cmp["facts"].get(fid)
        if not f or f["status"] not in CONFIRMED:
            return False
        if any(not same_value(value_key(t), value_key(f["value"])) for t in texts):
            return False
    return True


def is_clean(label: str, draft: dict, cmp: dict) -> bool:
    """True when every fact this draft uses was confirmed by the council, it gave the confirmed value, and
    every number in its text is one of those confirmed values."""
    if not isinstance(draft, dict) or draft.get("status") != "ANSWERED":
        return False
    if not fact_claims(draft) and re.search(r"\d", str(draft.get("answer", ""))):
        return False  # digits with no fact claims = nothing confirmed (red-team B #3)
    for fid in fact_claims(draft):
        f = cmp["facts"].get(fid)
        if not f or f["status"] not in CONFIRMED or label not in f["members"]:
            return False
    return claims_ok(draft, cmp) and text_ok(draft, cmp)


def _safe(text) -> str:
    """A member-supplied value with everything but number characters removed, so it cannot carry instructions."""
    nums = checker.find_numbers(str(text or ""))
    return nums[0]["text"] if nums else re.sub(r"[^0-9$%.,+\- ]", "", str(text or ""))[:40].strip()


def merge_human(inp: dict, drafts: dict, cmp: dict) -> str:
    """Only code-checked facts go to the merge model. Member prose is never included (review 2026-11-21:
    a member answer could carry instructions for the merger)."""
    facts = cmp["facts"]
    ids = lambda xs: [x for x in xs if _ID_RX.fullmatch(x)]  # noqa: E731
    confirmed = [f"{fid} | {_safe(facts[fid]['value'])} | "
                 + ("all members agree" if facts[fid]["status"] == "AGREED" else "majority of members")
                 for fid in ids(cmp["agreed"] + cmp["majority"])]
    parts = [agents.writer_human(inp),
             "CONFIRMED FACTS (fact id | value | agreement):\n" + ("\n".join(confirmed) or "(none)")]
    if ids(cmp["disputed"]):
        parts.append("DISPUTED FACTS (members gave different values, do not use):\n" + "\n".join(ids(cmp["disputed"])))
    if ids(cmp["solo"]):
        parts.append("UNCONFIRMED FACTS (not confirmed by two members, leave out):\n" + "\n".join(ids(cmp["solo"])))
    return "\n\n".join(parts)


def _rewrite(inp: dict, config=None) -> dict:
    """Default merge writer: Claude (GPT if Claude is down) writes from the confirmed facts."""
    obj, name = agents.call_json(MERGE_MODELS, MERGE_SYSTEM, inp["human"], config, need_key="answer")
    return {"draft": clean_draft(obj), "model": name}


REWRITER = RunnableLambda(_rewrite, name="council_rewrite")


def _merge(inp: dict, config, rewriter) -> dict:
    drafts, cmp, models = inp["drafts"], inp["compare"], inp["models"]
    if cmp["vote"] == "I_DONT_KNOW":
        label = next((l for l, d in drafts.items() if d.get("status") == "I_DONT_KNOW"), next(iter(drafts)))
        d = {"status": "I_DONT_KNOW", "answer": NO_DATA, "claims": []}  # fixed text: no member numbers shown
        return {"draft": d, "model": models[label], "rewritten": False,
                "how": f"kept {label}'s draft: most members said the data does not cover this"}
    for label, d in drafts.items():
        if is_clean(label, d, cmp):
            return {"draft": dict(d), "model": models[label], "rewritten": False,
                    "how": f"kept {label}'s draft: every figure in it was confirmed by the council"}
    try:
        out = rewriter.invoke({"human": merge_human(inp["writer_input"], drafts, cmp)}, config=config)
        out = out if isinstance(out, dict) else {}
        draft = clean_draft(out.get("draft"))
    except Exception:  # noqa: BLE001
        out, draft = {}, None
    if draft is not None and draft["status"] == "I_DONT_KNOW":
        draft = {"status": "I_DONT_KNOW", "answer": NO_DATA, "claims": []}
    if draft is not None and (draft["status"] == "I_DONT_KNOW" or (claims_ok(draft, cmp) and text_ok(draft, cmp))):
        return {"draft": draft, "model": out.get("model"), "rewritten": True,
                "how": "rewritten from the confirmed facts only"}
    # no draft passed the code check (merge model down, or its rewrite used an unconfirmed number): fail closed
    return {"draft": None, "model": None, "rewritten": False,
            "how": "no draft passed the council check: single writer used"}


# ---------------------------------------------------------------- the council
def build(members=None, rewriter=None, timeout: float | None = None, soft: float | None = None) -> RunnableLambda:
    """members: list of (spec, runnable). A runnable takes the writer input and returns
    {"status": "ok" | "failed", "draft": {...}, "note": "..."}. Tests pass fakes; no network."""
    members = list(members) if members is not None else [(m, member_runnable(m)) for m in MEMBERS]
    rewriter = rewriter or REWRITER

    def merge_step(inp: dict, config) -> dict:
        return _merge(inp, config, rewriter)

    merge = RunnableLambda(merge_step, name="council_merge")

    def timed_member(runnable, inp, config):
        t0 = time.time()
        try:
            out = runnable.invoke(inp, config=config)
            out = out if isinstance(out, dict) else {"status": "failed", "draft": None, "note": "bad member reply"}
        except Exception as e:  # noqa: BLE001
            out = {"status": "failed", "draft": None, "note": f"member failed ({type(e).__name__})"}
        return {**out, "seconds": round(time.time() - t0, 2)}

    def run(inp: dict, config) -> dict:
        limit = timeout if timeout is not None else member_timeout()
        soft_limit = soft if soft is not None else soft_timeout()
        t0 = time.time()
        pool = ThreadPoolExecutor(max_workers=max(1, len(members)), thread_name_prefix="council")
        futures = [pool.submit(contextvars.copy_context().run, timed_member, r, inp, config) for _, r in members]
        got, pending = {}, set(futures)
        while pending:
            answered = sum(1 for r in got.values() if r.get("status") == "ok" and clean_draft(r.get("draft")))
            # fewer than two answers: wait the full limit. Two answers: the last member only gets the soft limit.
            deadline = t0 + (limit if answered < 2 else min(limit, soft_limit))
            left = deadline - time.time()
            if left <= 0:
                break
            done, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    got[fut] = fut.result()
                except Exception as e:  # noqa: BLE001
                    got[fut] = {"status": "failed", "draft": None, "note": f"member failed ({type(e).__name__})",
                                "seconds": round(time.time() - t0, 2)}
        waited = round(time.time() - t0, 2)
        results = []
        for (spec, _), fut in zip(members, futures):
            res = got.get(fut) or {"status": "timeout", "draft": None, "seconds": waited,
                                   "note": f"no answer after {waited:g} s, the council went on without it"}
            draft = clean_draft(res.get("draft")) if res.get("status") == "ok" else None
            status = res.get("status") if res.get("status") in ("ok", "timeout") else "failed"
            if status == "ok" and draft is None:
                status, res = "failed", {**res, "note": "reply was not a usable draft"}
            results.append({"spec": spec, "status": status, "draft": draft, "note": str(res.get("note") or ""),
                            "seconds": float(res.get("seconds") or 0)})
        pool.shutdown(wait=False, cancel_futures=True)  # a slow member is left behind, never waited for

        rows = [_row(f"council_{r['spec']['key']}", "model", r["spec"]["model"],
                     "ok" if r["status"] == "ok" else "unavailable", r["note"], r["seconds"]) for r in results]
        info = {"members": [{"name": r["spec"]["label"], "model": r["spec"]["model"], "status": r["status"],
                             "seconds": round(r["seconds"], 2)} for r in results],
                "agreed": 0, "majority": 0, "unconfirmed": 0, "disputed": [], "used": False, "merge": None}
        ok = [r for r in results if r["status"] == "ok"]
        if len(ok) < 2:
            info["merge"] = "fewer than two members answered: single writer used"
            return {"ok": False, "draft": None, "model": None, "rows": rows, "council": info, "exclude": [],
                    "models": []}

        drafts = {r["spec"]["label"]: r["draft"] for r in ok}
        models = {r["spec"]["label"]: r["spec"]["model"] for r in ok}
        t1 = time.time()
        cmp = COMPARE.invoke({"drafts": drafts, "sheets": inp.get("sheets")}, config=config)
        rows.append(_row("council_compare", "code", note=(
            f"{len(cmp['agreed'])} agreed, {len(cmp['majority'])} majority, {len(cmp['disputed'])} disputed, "
            f"{len(cmp['solo'])} from one member only"), seconds=time.time() - t1))
        t2 = time.time()
        merged = merge.invoke({"drafts": drafts, "compare": cmp, "models": models, "writer_input": inp},
                              config=config)
        rows.append(_row("council_merge", "model" if merged["rewritten"] else "code",
                         merged["model"] if merged["rewritten"] else None, note=merged["how"],
                         seconds=time.time() - t2))
        info.update(agreed=len(cmp["agreed"]), majority=len(cmp["majority"]), unconfirmed=len(cmp["solo"]),
                    disputed=[{"fact_id": fid, "members": sorted(cmp["facts"][fid]["values_by_model"])}
                              for fid in cmp["disputed"] if _ID_RX.fullmatch(fid)],  # ids only, never the values
                    used=merged["draft"] is not None, merge=merged["how"])
        if merged["draft"] is None:
            return {"ok": False, "draft": None, "model": None, "rows": rows, "council": info,
                    "exclude": list(cmp["disputed"]), "models": []}
        used = [models[l] for l in drafts]
        if merged["rewritten"] and merged["model"] and merged["model"] not in used:
            used.append(merged["model"])
        return {"ok": True, "draft": merged["draft"], "model": merged["model"], "rows": rows, "council": info,
                "exclude": list(cmp["disputed"]), "models": used}

    return RunnableLambda(run, name="council")


COUNCIL = build()


if __name__ == "__main__":  # one live call per member: .venv/bin/python -m backend.council
    demo = {"ticker": "AAPL", "company": "Apple Inc.", "question": "What were net sales in fiscal 2026?",
            "sheets": ["FACTS (id | what | value):\nrevenue_fy2026 | Net sales (revenue), fiscal 2026 | $478.8 billion"],
            "unavailable": [], "has_news": False}
    res = COUNCIL.invoke(demo)
    print(json.dumps({k: res[k] for k in ("ok", "draft", "council", "exclude")}, indent=2))
