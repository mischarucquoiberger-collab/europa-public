"""The writer: the model gets tokens and directions, never values, and writes placeholders.
Everything it returns goes through backend.verify.audit before it reaches a page.

The packet holds only the latest fiscal year and the year before it (plus two older years of
revenue and net income, for a trend), and only for metrics that have a value in the latest
year: a metric the latest year lacks is not written about at all (the page shows it as not
available), so an older figure can never be passed off as the current one."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from backend import format as fmt
from backend import agents, model, settings
from backend.facts import metrics
from backend.verify import audit

SECTIONS = ("overview", "results", "financial_position", "cash_flow")
TITLES = {"overview": "Overview", "results": "Results",
          "financial_position": "Financial position", "cash_flow": "Cash flow"}
NOT_COVERED = "NOT COVERED"
RETRY_PAUSES = model.RETRY_PAUSES   # the retries live in backend.model
YEARS = 4                           # the latest fiscal year, the year before, two older trend years
TREND_KEYS = ("revenue", "net_income")
MAX_TOKENS = 700                    # room for a whole section: a cut-off reply leaves a fragment

_FY_RE = re.compile(r"^FY(\d{4})$")
_RATE_RE = re.compile(r"growth|cagr")
# the valuation arithmetic's own facts belong to its section, not to the written narrative
_VALUATION_KEYS = frozenset({"revenue_cagr_2y", "revenue_cagr_4y", "revenue_growth_estimate", "net_debt",
                             "pre_tax_cost_of_debt", "effective_tax_rate"})
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
# a finished sentence ends with . ! or ?, optionally followed by closing quotes or brackets
_FINISHED = re.compile(r"[.!?][\"'”’)\]]*$")
_SENTENCES = {"overview": "two or three"}
_FOCUS = {
    "overview": "the company's latest fiscal year: its revenue, its net income, its operating margin, "
                "and the one most notable change from the year before",
    "results": "revenue, gross profit, operating income, net income, earnings per share and margins in "
               "the latest fiscal year, against the year before",
    "financial_position": "total assets, total liabilities, shareholders' equity, cash and long-term debt "
                          "at the latest fiscal year end, against the year before, and the "
                          "debt-to-equity ratio",
    "cash_flow": "operating cash flow, capital expenditure, free cash flow and free cash flow margin in "
                 "the latest fiscal year, against the year before",
}
_DIRECTION_WORDS = {"up": "rose", "down": "fell", "flat": "was little changed"}
_SIGN_NOTES = {"negative": "negative",
               "turned negative": "turned negative from a positive figure the year before",
               "turned positive": "turned positive from a negative figure the year before"}
_ROLES = (("latest", "Latest fiscal year ({period}): the subject of every sentence"),
          ("prior", "The year before ({period}): for comparison only"),
          ("trend", "Older years: at most once in the whole section, as a trend, never as the subject"))


def fiscal_years(ledger) -> list[int]:
    """Fiscal years with at least one FY fact, newest first."""
    years = {int(m.group(1)) for key in ledger.keys() for p in ledger.periods(key)
             if (m := _FY_RE.match(p))}
    return sorted(years, reverse=True)


def annual_period(ledger, key: str, year: int) -> str | None:
    """The period a key's value for fiscal `year` is held under: `FY2024` for a flow or a ratio,
    the fiscal year-end date for a balance (an instant metric)."""
    m = metrics.METRICS.get(key)
    if m is not None and m.kind == "instant":
        return ledger.period_end(f"FY{year}")
    return f"FY{year}"


def annual_fact(ledger, key: str, year: int):
    period = annual_period(ledger, key, year)
    return ledger.get(key, period) if period else None


def is_rate(key: str) -> bool:
    """A growth rate (or CAGR): it is stated, never said to rise or fall."""
    return bool(_RATE_RE.search(key or ""))


def narrative_key(key: str) -> bool:
    """A metric the written sections may use: a statement figure or one of its ratios."""
    if key in _VALUATION_KEYS or "cagr" in key or "estimate" in key:
        return False
    return key in metrics.METRICS or key in metrics.COMPUTED_LABELS


def _shown(f) -> str:
    try:
        return fmt.fact(f)
    except Exception:
        return repr(f.value)


def _direction(cur, prior) -> str | None:
    """up / down / flat against the year before; flat also when the two read the same once
    formatted ("$371.4 billion" against "$371.4 billion"): "rose to X from X" is never written."""
    if cur is None or prior is None or cur.value is None or prior.value is None:
        return None
    if cur.unit != prior.unit:
        return None
    if _shown(cur) == _shown(prior):
        return "flat"
    if cur.value > prior.value:
        return "up"
    if cur.value < prior.value:
        return "down"
    return "flat"


def _sign(cur, prior) -> str | None:
    if cur is None or cur.value is None:
        return None
    before = prior.value if prior is not None and prior.value is not None else None
    if cur.value < 0:
        return "turned negative" if before is not None and before > 0 else "negative"
    if cur.value > 0 and before is not None and before < 0:
        return "turned positive"
    return None


def _latest_year(ledger) -> int | None:
    years = {int(m.group(1)) for key in ledger.keys() if narrative_key(key)
             for p in ledger.periods(key) if (m := _FY_RE.match(p))}
    return max(years) if years else None


def _has(f) -> bool:
    return f is not None and f.value is not None


def build_packet(ledger, company: dict) -> dict:
    """Tokens, labels, periods and directions; NO values. The latest fiscal year's tokens come
    first, then the year before's, then the older trend years' (revenue and net income only)."""
    latest = _latest_year(ledger)
    facts = []
    if latest is not None:
        keys = [k for k in ledger.keys() if narrative_key(k) and _has(annual_fact(ledger, k, latest))]
        plan = [(latest, "latest", keys), (latest - 1, "prior", keys)]
        plan += [(latest - back, "trend", [k for k in keys if k in TREND_KEYS]) for back in (2, 3)]
        for year, role, wanted in plan[:YEARS]:
            for key in wanted:
                f = annual_fact(ledger, key, year)
                if not _has(f):
                    continue
                prior = annual_fact(ledger, key, year - 1)
                rate = is_rate(f.key)
                entry = {
                    "token": f"[[F:{f.key}|{f.period}]]",
                    "label": metrics.label(f.key),
                    "period": fmt.period_label(f.period),
                    "kind": "computed" if f.is_computed else "reported",
                    "direction": None if rate else _direction(f, prior),
                    "year": year,
                    "role": role,
                }
                if rate:
                    entry["rate"] = True
                sign = None if rate else _sign(f, prior)
                if sign:
                    entry["sign"] = sign
                facts.append(entry)
    periods = sorted({f"FY{e['year']}" for e in facts}, key=lambda p: -int(p[2:]))
    return {"company": {"name": str(company.get("name") or ""),
                        "ticker": str(company.get("ticker") or "")},
            "facts": facts,
            "periods": periods}


def _system_prompt() -> str:
    return (
        "You write one short section of a company report from SEC filings. Rules:\n"
        "- Write the number of sentences the request asks for, about the company, using only the "
        "listed tokens.\n"
        "- Write about the company's LATEST fiscal year, compared with the year before. An older "
        "year may appear at most once in the section, as a trend, and never as the subject of a "
        "sentence. Write only about figures the latest fiscal year has; never write 'the most "
        "recent figure available'.\n"
        "- Name the fiscal year of every figure you write (for example \"in fiscal 2025\"), and keep "
        "each figure next to its own metric and year words.\n"
        "- Every figure must be written as its exact token, for example [[F:revenue|FY2024]], and "
        "nothing else.\n"
        "- Never write a digit yourself: no amounts, no percentages, no dates other than what a "
        "token carries.\n"
        "- Describe direction only with the given words: \"rose\" or \"fell\" where that direction "
        "is given, and \"was little changed at\" for a figure that was little changed. Write nothing "
        "about direction where none is given.\n"
        "- State a growth rate plainly (for example \"revenue growth was [[F:revenue_growth|FY2025]]\"); "
        "never say a growth rate rose, fell, increased, decreased, slowed or accelerated.\n"
        "- Use at most two periods of the same figure in one sentence.\n"
        "- For a negative figure write \"was negative at\" (or \"turned negative at\" when the year "
        "before was positive); never say a figure \"fell to\" a negative amount.\n"
        "- Every sentence must make sense on its own if the others are removed: name the figure in "
        "each sentence, and do not begin with It, This, These, Also, However or Meanwhile.\n"
        "- Write about the company, never about the data: never describe the dataset, never count "
        "the years, never write \"the figures cover\" or anything like it.\n"
        "- Do not recommend, rate or predict. Do not state causes or intentions. Do not say whether "
        "the stock is a good or bad investment.\n"
        "- End every sentence with a full stop.\n"
        f"- If the tokens do not cover the section, answer exactly {NOT_COVERED}\n"
        "Answer with the sentences only, no heading."
    )


def _line(f: dict) -> str:
    notes = [f.get("kind") or "reported"]
    word = _DIRECTION_WORDS.get(f.get("direction") or "")
    if word:
        notes.append(f"{word} from the year before")
    if f.get("rate"):
        notes.append("a growth rate: state it plainly, never say it rose or fell")
    if f.get("sign") in _SIGN_NOTES:
        notes.append(_SIGN_NOTES[f["sign"]])
    return f"{f['token']}: {f['label']}, {f['period']} ({'; '.join(notes)})"


def prompt_for(section: str, packet: dict) -> list[dict]:
    """System + user messages for one section."""
    title = TITLES.get(section, section)
    company = packet.get("company") or {}
    facts = [f for f in packet.get("facts") or [] if isinstance(f, dict) and f.get("token")]
    if facts and all(f.get("role") for f in facts):
        blocks = []
        for role, heading in _ROLES:
            group = [f for f in facts if f.get("role") == role]
            if group:
                years = sorted({f.get("year") for f in group if f.get("year")}, reverse=True)
                period = ", ".join(fmt.period_label(f"FY{y}") for y in years)
                blocks.append(heading.format(period=period) + ":\n" + "\n".join(_line(f) for f in group))
        tokens = "\n\n".join(blocks)
    else:
        tokens = "Tokens:\n" + ("\n".join(_line(f) for f in facts) if facts else "(none)")
    count = _SENTENCES.get(section, "two to four")
    user = (
        f"Section: {title}\n"
        f"Company: {company.get('name', '')} ({company.get('ticker', '')})\n"
        f"Write {count} sentences on {_FOCUS.get(section, title.lower())}.\n"
        + tokens
    )
    return [{"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user}]


def finished(sentence: str) -> bool:
    """True for a sentence that ends properly: a closing full stop, question or exclamation mark
    (a closing quote or bracket may follow) and no placeholder left open."""
    s = (sentence or "").strip()
    if not _FINISHED.search(s):
        return False
    rest = audit.PLACEHOLDER.sub(" ", s)
    return "[[" not in rest and "]]" not in rest


def drop_unfinished(text: str) -> str:
    """The text without a final sentence that was cut off (a reply that ran out of room). A text
    that is only a fragment becomes ""."""
    paragraphs = [p for p in _PARAGRAPH_SPLIT.split((text or "").strip()) if p.strip()]
    if not paragraphs:
        return ""
    sentences = audit.sentences(paragraphs[-1])
    if sentences and not finished(sentences[-1]):
        sentences = sentences[:-1]
        if sentences:
            paragraphs[-1] = " ".join(sentences)
        else:
            paragraphs.pop()
    return "\n\n".join(p.strip() for p in paragraphs)


def _one(section: str, packet: dict, session_id: str, sleep: Callable[[float], None]) -> str | None:
    try:
        reply = model.ask(prompt_for(section, packet), session_id=session_id, sleep=sleep,
                          agent_id=agents.WRITER, temperature=0.2, max_tokens=MAX_TOKENS)
    except Exception:          # the model failed (after backend.model's retries): leave it out
        return None
    text = (reply or "").strip()
    if not text or text.upper().startswith(NOT_COVERED):
        return None
    return drop_unfinished(text) or None


def write_sections(packet: dict, *, session_id: str,
                   sleep: Callable[[float], None] = time.sleep) -> dict[str, str]:
    """One model call per section, all at the same time (through backend.model: its gate, and its
    retries on 429/5xx/unreachable); failed or NOT COVERED sections are left out. Never raises."""
    out: dict[str, str] = {}
    try:
        with ThreadPoolExecutor(max_workers=max(1, settings.MODEL_CONCURRENCY)) as pool:
            futures = {s: pool.submit(_one, s, packet, session_id, sleep) for s in SECTIONS}
            for section in SECTIONS:
                try:
                    text = futures[section].result()
                except Exception:
                    text = None
                if text:
                    out[section] = text
    except Exception:
        pass
    return out


def fallback_overview(ledger, company: dict) -> str:
    """The overview built in code, used when the model did not write one: the latest fiscal year's
    headline figures as linked values. HTML, or "" when the ledger has none of them."""
    import html as _html
    from backend import format as fmt
    years = fiscal_years(ledger)
    if not years:
        return ""
    year = years[0]
    parts = []
    for key, label in (("revenue", "revenue of"), ("net_income", "net income of"), ("operating_margin", "an operating margin of")):
        f = annual_fact(ledger, key, year)
        if f is not None and f.value is not None:
            parts.append(f"{label} {fmt.cited(f, ledger)}")
    if not parts:
        return ""
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    name = _html.escape(str(company.get("name") or company.get("ticker") or "The company"))
    return f"<p>{name} reported {listed} for {_html.escape(fmt.period_label(f'FY{year}'))}.</p>"


# ---- code-built sections ---------------------------------------------------------------------
# Each slot is one sentence: the first key of the slot that the latest fiscal year has.
_FALLBACK_SLOTS = {
    "results": (("revenue",), ("net_income",),
                ("operating_margin", "operating_income", "gross_margin", "net_margin")),
    "financial_position": (("total_assets",), ("shareholders_equity", "total_liabilities"),
                           ("long_term_debt", "cash")),
    "cash_flow": (("operating_cash_flow",), ("free_cash_flow", "capex"), ("fcf_margin",)),
}


def _when(key: str, year: int) -> str:
    m = metrics.METRICS.get(key)
    if m is not None and m.kind == "instant":
        return f"at the end of fiscal {year}"
    return f"in fiscal {year}"


def _comparison(ledger, key: str, year: int) -> str | None:
    """One sentence with placeholders: the latest year against the year before, or the latest
    year alone. Neutral wording around a negative figure; "little changed" when the two read the
    same once formatted."""
    cur = annual_fact(ledger, key, year)
    if not _has(cur):
        return None
    label = metrics.label(key)
    token = f"[[F:{cur.key}|{cur.period}]]"
    prior = annual_fact(ledger, key, year - 1)
    if not _has(prior) or cur.unit != prior.unit:
        return f"{label} was {token} {_when(key, year)}."
    before = f"[[F:{prior.key}|{prior.period}]] {_when(key, year - 1)}"
    direction = _direction(cur, prior)
    if cur.value < 0 or prior.value < 0:
        return f"{label} was {token} {_when(key, year)}, against {before}."
    if direction == "up":
        return f"{label} rose to {token} {_when(key, year)} from {before}."
    if direction == "down":
        return f"{label} fell to {token} {_when(key, year)} from {before}."
    return f"{label} was little changed at {token} {_when(key, year)}, against {before}."


def fallback_section(section: str, ledger, company: dict) -> str:
    """A section built in code ("results", "financial_position" or "cash_flow"), for when the model's
    section is missing or the checks removed too much of it: two or three sentences with
    `[[F:key|period]]` placeholders (to go through audit.apply like the model's text), the latest
    fiscal year against the year before, from facts that exist. "" when fewer than two can be
    written, or for any other section."""
    slots = _FALLBACK_SLOTS.get(section)
    year = _latest_year(ledger)
    if not slots or year is None:
        return ""
    sentences = []
    for keys in slots:
        for key in keys:
            sentence = _comparison(ledger, key, year)
            if sentence:
                sentences.append(sentence)
                break
    return " ".join(sentences) if len(sentences) >= 2 else ""
