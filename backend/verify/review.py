"""The self-check: independent model readers check the draft, at the same time, before the audit.

Two readers with different instructions (REVIEWERS) get the same material: the writer's fact list
as `token | label | period | direction` lines (no values) and the draft section as numbered
sentences, its `[[F:key|period]]` tokens left as they are. Each answers strict JSON, one verdict
per sentence. A sentence REJECTED by at least one reader is removed from the section and listed
with the reader's reason; a sentence nobody rejected stays. A reader that fails, or answers
something unusable, abstains: it neither confirms nor rejects. Beside the two model readers, a
code reader ("rules") rejects what can be checked exactly: three or more periods of one figure in
a sentence, a growth rate said to rise or fall, a sentence about the data instead of the company,
a figure used as if it were a period ("seen in [figure]"). After removals `keep` repairs the
survivors (a paragraph no longer opens with "Also," and the like) and removes a survivor that
refers back to a removed sentence ("those years"). Nothing here raises.

    verdicts = review_sections(raw, packet, session_id=...)      # every section, every reader
    text, removed = keep(raw["results"], verdicts["results"])     # then audit.apply(text, ledger)
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Callable, Iterable

from backend import agents, model
from backend.verify import audit

log = logging.getLogger(__name__)

REVIEWERS = ("auditor", "skeptic")
RULES = "rules"                 # the code reader: rejects only, never confirms
MAX_REASONS = 2
TEMPERATURE = 0
MAX_TOKENS = 500
REASON_CAP = 200

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")          # the audit's paragraph rule
_DIRECTION_TEXT = {"up": "up", "down": "down", "flat": "flat (little changed)"}
_FORMAT = ('Reply with strict JSON only: an array with one object per numbered sentence, for '
           'example [{"n": 1, "ok": true}, {"n": 2, "ok": false, "why": "says rose; the listed '
           'direction is down"}]. Give "why" for every sentence you do not confirm. No prose, no '
           'code fence.')
_MATERIAL = ("The writer was given only the fact list below. Each line is `token | label | period | "
             "direction`; direction is up (higher than the year before), down (lower than the year "
             "before), flat (little changed: the same once rounded, to be written \"was little "
             "changed\") or none (no direction may be claimed). A growth rate always has direction "
             "none: it is stated plainly and never said to rise or fall. \"negative\" or \"turned "
             "negative\" marks a figure below zero (a loss or an outflow). The latest fiscal year's "
             "tokens come first. Figures appear in the sentences as those tokens; you never see the "
             "values.")
_REJECT_ALSO = (
    "Also reject:\n"
    "- a sentence that says a growth rate rose, fell, increased, decreased, slowed or accelerated "
    "(a growth rate is stated plainly);\n"
    "- a sentence that uses three or more periods of the same figure;\n"
    "- a sentence whose subject is a year older than the latest fiscal year (an older year may "
    "only appear as a brief trend);\n"
    "- a sentence that describes the data instead of the company: what the figures cover, how many "
    "years there are, \"the most recent figure available\";\n"
    "- a figure that is not attached to its own metric and period words, for example a figure used "
    "as if it were a period or a place (\"increases seen in [[F:revenue|FY2023]]\", \"since "
    "[[F:revenue|FY2022]]\");\n"
    "- a sentence that says a figure listed as flat rose or fell.\n"
)
_INSTRUCTIONS = {
    "auditor": (
        "You are the auditor of one section of a company report built from SEC filings. "
        + _MATERIAL + "\n"
        "Confirm a sentence (ok true) only if everything it claims is supported by the list:\n"
        "- a direction word (rose, fell, increased, decreased, higher, lower, grew, declined, "
        "unchanged, little changed) must match the listed direction of the token it describes;\n"
        "- a statement comparing two periods must agree with the listed directions;\n"
        "- it must not state a cause, an intention, a forecast or an opinion that the list does "
        "not contain;\n"
        "- it must not advise (buy, sell, hold, or any other recommendation).\n"
        + _REJECT_ALSO +
        "Otherwise answer ok false and say briefly why.\n" + _FORMAT
    ),
    "skeptic": (
        "You are a skeptical second reader of one section of a company report built from SEC "
        "filings. " + _MATERIAL + "\n"
        "Assume each numbered sentence is wrong unless the list proves it. Look especially for:\n"
        "- a direction attached to the wrong figure (for example \"revenue rose\" when the token "
        "that is up is net income, or a direction word next to a token whose listed direction is "
        "different or none);\n"
        "- a token used for a figure or a period it does not name;\n"
        "- sentences that are grammatical nonsense or do not make sense as written;\n"
        "- any cause, intention, forecast, opinion or advice the list does not contain.\n"
        + _REJECT_ALSO +
        "Answer ok true only when the list proves every claim in the sentence; otherwise ok false "
        "with a short reason.\n" + _FORMAT
    ),
}
assert tuple(_INSTRUCTIONS) == REVIEWERS

# ---- the code reader's exact checks ----------------------------------------------------------
_MOVE = (r"(?:rose|rises|risen|fell|falls|fallen|increas(?:ed|es|ing)|decreas(?:ed|es|ing)|"
         r"declin(?:ed|es|ing)|dropped|climbed|slowed|accelerated|improved|worsened|weakened|eased|"
         r"jumped|surged|higher|lower)")
_GROWTH_MOVES = re.compile(
    r"\b(?:growth|growth\s+rate|cagr)\b(?:\s+\S+){0,3}?\s+" + _MOVE + r"\b"
    r"|\b" + _MOVE + r"\s+(?:to\s+|from\s+|by\s+)?\[\[F:[a-z_]*(?:growth|cagr)", re.IGNORECASE)
_ABOUT_THE_DATA = re.compile(
    r"\b(?:figures|data|dataset|data\s+set|tokens|facts|statements)\b[^.;]{0,80}?"
    r"\b(?:cover|covers|covered|covering|span|spans|spanned|spanning)\b"
    r"|\bfiscal\s+years\s+(?:presented|shown|listed|provided|available)\b"
    r"|\b(?:two|three|four|five|six|seven|eight|nine|ten)\s+(?:consecutive\s+|full\s+|fiscal\s+)*years\b"
    r"|\bfigures?\s+available\b", re.IGNORECASE)
_FIGURE_AS_PERIOD = re.compile(
    r"\b(?:seen|recorded|observed|reported|noted)\s+(?:in|at)\s+\[\[F:"
    r"|\b(?:since|during|throughout|through|across|until)\s+\[\[F:", re.IGNORECASE)
# survivors after removals
_OPENER = re.compile(r"^(?:also|in\s+addition|additionally|however|meanwhile|as\s+a\s+result)\b,?\s*",
                     re.IGNORECASE)
_ALSO = re.compile(r"\s+also\b(?=[\s,])", re.IGNORECASE)
_REFERS_BACK = re.compile(
    r"\b(?:those\s+years|these\s+years|that\s+year|this\s+followed|that\s+followed|"
    r"the\s+same\s+period|over\s+that\s+period|the\s+same\s+years)\b", re.IGNORECASE)
REFERS_BACK = "refers to a removed sentence"


def rule_reasons(sentence: str) -> list[str]:
    """What the code reader rejects in one sentence (empty when nothing)."""
    reasons = []
    periods: dict[str, set] = {}
    for key, period in audit.find_placeholders(sentence):
        periods.setdefault(key, set()).add(period)
    if any(len(p) >= 3 for p in periods.values()):
        reasons.append("it uses three or more periods of one figure")
    if _GROWTH_MOVES.search(sentence):
        reasons.append("it says a growth rate rose or fell; a growth rate is stated plainly")
    if _ABOUT_THE_DATA.search(audit.PLACEHOLDER.sub(" ", sentence)):
        reasons.append("it describes the data, not the company")
    if _FIGURE_AS_PERIOD.search(sentence):
        reasons.append("it uses a figure as if it were a period")
    return reasons


@dataclass(frozen=True)
class Verdict:
    """What the readers said about one sentence (numbered from 1 across the whole section)."""
    n: int
    sentence: str
    confirmed_by: tuple[str, ...] = ()
    rejected_by: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return bool(self.rejected_by)


# ---- material -------------------------------------------------------------------------------
def _paragraphs(text: str) -> list[list[str]]:
    """The section as paragraphs of sentences, split exactly as the audit splits them."""
    out = []
    for para in _PARAGRAPH_SPLIT.split(text or ""):
        found = audit.sentences(para)
        if found:
            out.append(found)
    return out


def numbered(text: str) -> list[str]:
    """Every sentence of the section in order; sentence n is item n - 1."""
    return [s for para in _paragraphs(text) for s in para]


def fact_lines(packet: dict) -> list[str]:
    lines = []
    for f in (packet or {}).get("facts") or []:
        if not isinstance(f, dict) or not f.get("token"):
            continue
        direction = _DIRECTION_TEXT.get(f.get("direction") or "", "none")
        if f.get("rate"):
            direction = "none (a growth rate: stated, never said to rise or fall)"
        if f.get("sign"):
            direction += f", {f['sign']}"
        lines.append(f"{f['token']} | {f.get('label', '')} | {f.get('period', '')} | {direction}")
    return lines


def messages_for(reviewer: str, section: str, sentences: list[str], packet: dict) -> list[dict]:
    company = (packet or {}).get("company") or {}
    title = section.replace("_", " ").capitalize()
    facts = fact_lines(packet)
    user = (
        f"Section: {title}\n"
        f"Company: {company.get('name', '')} ({company.get('ticker', '')})\n"
        "Fact list:\n" + ("\n".join(facts) if facts else "(none)") + "\n\n"
        "Sentences:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1))
    )
    return [{"role": "system", "content": _INSTRUCTIONS[reviewer]},
            {"role": "user", "content": user}]


# ---- one reader -----------------------------------------------------------------------------
def _ok_value(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "yes"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "no"):
        return False
    return None


def _n_value(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _clean_reason(value) -> str:
    text = " ".join(audit.readable(str(value or "")).split())
    return text if len(text) <= REASON_CAP else text[:REASON_CAP - 1].rstrip() + "…"


def _parse_answer(reply, count: int) -> dict[int, tuple[bool, str]] | None:
    """{sentence number: (ok, why)} from a reader's JSON, or None when it is unusable (the reader
    then abstains). A sentence the reader mentions twice, once rejecting, counts as rejected."""
    if isinstance(reply, dict):
        lists = [v for v in reply.values() if isinstance(v, list)]
        reply = lists[0] if len(lists) == 1 else None
    if not isinstance(reply, list):
        return None
    out: dict[int, tuple[bool, str]] = {}
    for item in reply:
        if not isinstance(item, dict):
            continue
        n, ok = _n_value(item.get("n")), _ok_value(item.get("ok"))
        if n is None or ok is None or not 1 <= n <= count:
            continue
        why = _clean_reason(item.get("why")) if not ok else ""
        if n in out and not out[n][0]:
            continue                          # a rejection stands
        out[n] = (ok, why)
    return out or None


def _read(reviewer: str, section: str, sentences: list[str], packet: dict, session_id: str,
          ask_json: Callable) -> dict[int, tuple[bool, str]] | None:
    try:
        reply = ask_json(messages_for(reviewer, section, sentences, packet), session_id=session_id,
                         agent_id=agents.REVIEWERS.get(reviewer), temperature=TEMPERATURE,
                         max_tokens=MAX_TOKENS)
    except Exception as exc:                    # the reader failed: it abstains
        log.info("reviewer %s abstained on %s: %s", reviewer, section, exc)
        return None
    answer = _parse_answer(reply, len(sentences))
    if answer is None:
        log.info("reviewer %s gave no usable verdicts on %s", reviewer, section)
    return answer


def _combine(sentences: list[str], answers: dict[str, dict | None]) -> list[Verdict]:
    verdicts = []
    for n, sentence in enumerate(sentences, 1):
        confirmed, rejected, reasons = [], [], []
        for reviewer in REVIEWERS:
            said = (answers.get(reviewer) or {}).get(n)
            if said is None:
                continue                        # abstained on this sentence
            ok, why = said
            if ok:
                confirmed.append(reviewer)
            else:
                rejected.append(reviewer)
                reasons.append(why or f"the {reviewer} did not confirm it")
        found = rule_reasons(sentence)
        if found:
            rejected.append(RULES)
            reasons.extend(found)
        verdicts.append(Verdict(n, sentence, tuple(confirmed), tuple(rejected), tuple(reasons)))
    return verdicts


# ---- public ---------------------------------------------------------------------------------
def review_section(section: str, text: str, packet: dict, *, session_id: str,
                   ask_json: Callable | None = None) -> list[Verdict]:
    """Both readers on one section at the same time. Never raises."""
    return review_sections({section: text}, packet, session_id=session_id,
                           ask_json=ask_json).get(section, [])


def review_sections(raw: dict[str, str], packet: dict, *, session_id: str,
                    ask_json: Callable | None = None) -> dict[str, list[Verdict]]:
    """Every section and every reader at once, on one pool (backend.model's gate limits how many
    model calls really run together). {section: [Verdict, ...]}; never raises."""
    ask_json = ask_json or model.ask_json
    try:
        material = {key: numbered(text) for key, text in (raw or {}).items()}
        jobs = [(key, reviewer) for key, sentences in material.items() if sentences
                for reviewer in REVIEWERS]
        answers: dict[tuple[str, str], dict | None] = {}
        if jobs:
            with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="review") as pool:
                futures = {job: pool.submit(_read, job[1], job[0], material[job[0]], packet,
                                            session_id, ask_json) for job in jobs}
                for job, future in futures.items():
                    try:
                        answers[job] = future.result()
                    except Exception:
                        answers[job] = None
        return {key: _combine(sentences, {r: answers.get((key, r)) for r in REVIEWERS})
                for key, sentences in material.items()}
    except Exception as exc:
        log.warning("the self-check could not run: %s", exc)
        return {key: [] for key in (raw or {})}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _similar(a: str, b: str) -> bool:
    """The same or nearly the same reason (two readers often say one thing in two ways)."""
    na, nb = _norm(a), _norm(b)
    if na == nb or (na and nb and (na in nb or nb in na)):
        return True
    wa, wb = set(na.split()), set(nb.split())
    if wa and wb and len(wa & wb) / len(wa | wb) >= 0.5:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.75


def reason_text(reasons) -> str:
    """The reasons as shown: one when they say the same thing, else at most the first two."""
    shown: list[str] = []
    for reason in reasons or ():
        reason = " ".join(str(reason or "").split())
        if not reason or any(_similar(reason, s) for s in shown):
            continue
        shown.append(reason)
        if len(shown) == MAX_REASONS:
            break
    return "; ".join(shown) or "a reader did not confirm it"


def _plan(text: str, verdicts) -> tuple[list[list[tuple[str, str | None]]], int]:
    """([paragraph: [(sentence, why it goes, or None)]], sentence count). A sentence goes when a
    reader rejected it, or when it refers back ("those years") and a sentence before it went."""
    rejected = {v.n: v for v in verdicts or () if v.rejected_by}
    by_sentence = {v.sentence: v for v in rejected.values()}
    plan, n, gone = [], 0, False
    for para in _paragraphs(text):
        rows = []
        for sentence in para:
            n += 1
            v = rejected.get(n)
            if v is None or v.sentence != sentence:
                v = by_sentence.get(sentence)
            if v is not None:
                why = reason_text(v.reasons)
            elif gone and _REFERS_BACK.search(sentence):
                why = REFERS_BACK
            else:
                why = None
            gone = gone or why is not None
            rows.append((sentence, why))
        plan.append(rows)
    return plan, n


def _repair(sentence: str) -> str:
    """A survivor that now opens a paragraph: no leading "Also," / "However," / ..., and no "also"
    that pointed at a removed sentence."""
    fixed = _OPENER.sub("", sentence, count=1)
    fixed = _ALSO.sub("", fixed)
    if fixed and fixed[0].islower():
        fixed = fixed[0].upper() + fixed[1:]
    return fixed or sentence


def keep(text: str, verdicts: list[Verdict]) -> tuple[str, list[str]]:
    """(the text without every sentence a reader rejected, paragraphs kept, survivors repaired;
    the removed sentences, readable (see audit.readable), each prefixed with its reason). A text
    with nothing rejected comes back unchanged. Never raises: on any problem the text comes back
    whole."""
    try:
        plan, _count = _plan(text, verdicts)
        if not any(why for rows in plan for _s, why in rows):
            return text, []
        paragraphs, removed = [], []
        for rows in plan:
            kept = [sentence for sentence, why in rows if why is None]
            removed += [f"Removed by review ({why}): {audit.readable(sentence).strip()}"
                        for sentence, why in rows if why is not None]
            if kept:
                kept[0] = _repair(kept[0])
                paragraphs.append(" ".join(kept))
        return "\n\n".join(paragraphs), removed
    except Exception as exc:
        log.warning("the self-check result could not be applied: %s", exc)
        return text, []


def share_removed(text: str, verdicts: list[Verdict]) -> float:
    """The share (0 to 1) of the section's sentences that `keep` removes; 0.0 for an empty text
    or on any problem."""
    try:
        plan, count = _plan(text, verdicts)
        gone = sum(1 for rows in plan for _s, why in rows if why is not None)
        return gone / count if count else 0.0
    except Exception as exc:
        log.warning("the self-check share could not be computed: %s", exc)
        return 0.0


def summary(all_verdicts) -> dict:
    """Counts over every section's verdicts ({section: [Verdict]} or a flat list): sentences,
    confirmed_by_both, confirmed_by_one, rejected (by a reader or the code rules), rejected_by_rules,
    abstained_only, reviewers_answered (model readers that gave at least one usable verdict)."""
    out = {"sentences": 0, "confirmed_by_both": 0, "confirmed_by_one": 0, "rejected": 0,
           "rejected_by_rules": 0, "abstained_only": 0, "reviewers_answered": 0,
           "reviewers": list(REVIEWERS)}
    try:
        if isinstance(all_verdicts, dict):
            items: Iterable = [v for vs in all_verdicts.values() for v in (vs or ())]
        else:
            items = list(all_verdicts or ())
        answered: set[str] = set()
        for v in items:
            out["sentences"] += 1
            answered.update(r for r in v.confirmed_by + v.rejected_by if r in REVIEWERS)
            if RULES in v.rejected_by:
                out["rejected_by_rules"] += 1
            if v.rejected_by:
                out["rejected"] += 1
            elif set(REVIEWERS) <= set(v.confirmed_by):
                out["confirmed_by_both"] += 1
            elif v.confirmed_by:
                out["confirmed_by_one"] += 1
            else:
                out["abstained_only"] += 1
        out["reviewers_answered"] = len(answered)
    except Exception as exc:
        log.warning("the self-check summary could not be built: %s", exc)
    return out


def describe(counts: dict) -> str:
    """One plain line for the job's event log."""
    if not counts.get("sentences"):
        return "Self-check: there were no sentences to check"
    if not counts.get("reviewers_answered"):
        ruled = counts.get("rejected_by_rules", 0)
        if ruled:
            return f"Self-check: no reader answered; the code rules removed {ruled}"
        return "Self-check: no reader answered; nothing was removed"
    n, both, rejected = counts.get("sentences", 0), counts.get("confirmed_by_both", 0), counts.get("rejected", 0)
    return (f"Self-check: {n} sentence{'s' if n != 1 else ''}, {both} confirmed by both readers, "
            f"{rejected} removed")
