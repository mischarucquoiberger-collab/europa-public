"""Report chat: answers a question about one finished report from that report's ledger only.

What is decided in code, before any model call: which metrics and periods the question names,
whether it asks for advice, and whether the ledger covers it. The model only arranges tokens
like `[[F:revenue|FY2024]]` into a sentence; `audit.apply` turns each token into the cited value
and drops any sentence with a figure the model typed itself. When anything fails, the reply is
a sentence built in code from the cited values (never a guess)."""
from __future__ import annotations

import html as _html
import json
import queue
import re
import threading
from dataclasses import dataclass, field
from typing import Iterator

import llm
from backend import contract, model, settings
from backend import format as fmt
from backend.facts import metrics as metrics_mod
from backend.facts import metrics as _metrics
from backend.ledger import Fact, Ledger, LedgerError

AGENT = "europa-report-chat"      # this part's name in the PRISM traces
DONT_KNOW = "I don't know: the sources I have do not cover that."
NO_ADVICE = "I can't advise on what to do. I can tell you what the company reported."
NOT_COVERED = "NOT COVERED"
MAX_QUESTION_CHARS = 2000
KEEPALIVE_SECONDS = 10.0

# (pattern, key), longest phrases first; a matched span is blanked so shorter patterns do not
# match inside it ("net margin" is not also "net income").
_SYNONYMS: tuple[tuple[str, str], ...] = (
    (r"(revenue|sales|turnover|top[- ]line)\s+growth|grow(th|n)?\s+(in\s+|of\s+)?(revenue|sales|turnover)", "revenue_growth"),
    (r"(net\s+income|profit|earnings|bottom[- ]line|income)\s+growth|grow(th|n)?\s+(in\s+|of\s+)?(net\s+income|profit|earnings|income)", "net_income_growth"),
    (r"free\s+cash\s+flow\s+margin|fcf\s+margin", "fcf_margin"),
    (r"free\s+cash\s+flow|\bfcf\b", "free_cash_flow"),
    (r"operating\s+cash\s+flow|cash\s+flows?\s+from\s+operations|cash\s+flow", "operating_cash_flow"),
    (r"gross\s+margin", "gross_margin"),
    (r"operating\s+margin", "operating_margin"),
    (r"net\s+(profit\s+)?margin|profit\s+margin", "net_margin"),
    (r"return\s+on\s+equity|\broe\b", "return_on_equity"),
    (r"return\s+on\s+assets|\broa\b", "return_on_assets"),
    (r"debt[- ]to[- ]equity|debt\s+to\s+equity", "debt_to_equity"),
    (r"diluted\s+(eps|earnings\s+per\s+share)", "eps_diluted"),
    (r"\beps\b|earnings\s+per\s+share", "eps_diluted"),
    (r"dividends?(\s+per\s+share)?", "dividends_per_share"),
    (r"operating\s+(income|profit)|\bebit\b", "operating_income"),
    (r"gross\s+profit", "gross_profit"),
    (r"cost\s+of\s+(revenue|sales|goods\s+sold)|\bcogs\b", "cost_of_revenue"),
    (r"net\s+income|net\s+profit|net\s+earnings|profit|earnings|bottom[- ]line", "net_income"),
    (r"revenues?|sales|turnover|top[- ]line", "revenue"),
    # the same two questions in German, French and Spanish
    (r"nettogewinn|reingewinn|jahres(?:ü|ue)berschuss|b(?:é|e)n(?:é|e)fice\s+net|r(?:é|e)sultat\s+net|beneficio\s+neto", "net_income"),
    (r"umsatz|ums(?:ä|ae)tze|erl(?:ö|oe)se|chiffre\s+d'affaires|ingresos|ventas", "revenue"),
    (r"r\s*&\s*d|research(\s+and\s+development)?", "research_and_development"),
    (r"capital\s+expenditures?|\bcapex\b", "capex"),
    (r"total\s+liabilities|liabilities", "total_liabilities"),
    (r"total\s+assets|\bassets\b", "total_assets"),
    (r"shareholders'?\s+equity|stockholders'?\s+equity|book\s+value|\bequity\b", "shareholders_equity"),
    (r"long[- ]term\s+debt|\bdebt\b|borrowings", "long_term_debt"),
    (r"cash(\s+and\s+(cash\s+)?equivalents)?", "cash"),
    (r"shares\s+outstanding|share\s+count", "shares_outstanding"),
)
_SYNONYM_RES = tuple((re.compile(p, re.I), k) for p, k in _SYNONYMS)

_ADVICE_RE = re.compile(
    r"\b(should\s+(i|we|you)|buy|buying|sell|selling\s+the\s+stock|hold|worth\s+(buying|it|investing)|"
    r"good\s+(investment|buy|stock)|bad\s+investment|price\s+target|target\s+price|"
    r"will\s+(it|the\s+stock|the\s+shares?|the\s+price)\s+(go|rise|fall|drop|climb|crash)|go\s+up|go\s+down|"
    r"undervalued|overvalued|recommend\w*|invest\s+in)\b", re.I)
# Questions the saved report answers by itself (its bull and bear points, risk themes, multiples
# and self-check counts): matched in code and answered from the saved document, with no model call.
_TOPICS: tuple[tuple[str, "re.Pattern"], ...] = (
    ("bull", re.compile(r"\bbull(?:ish)?\b|\bstrengths?\b|\bpositives?\b", re.I)),
    ("bear", re.compile(r"\bbear(?:ish)?\b|\bweakness(?:es)?\b|\bnegatives?\b|\bconcerns?\b", re.I)),
    ("risks", re.compile(r"\brisks?\b", re.I)),
    ("thesis", re.compile(r"\bthesis\b|\bkey\s+points?\b|\btakeaways?\b", re.I)),
    ("valuation", re.compile(r"\bvaluation\b|\bmultiples?\b|\bp\s*/\s*e\b|\bprice[- ]to[- ]earnings\b|\bev\s*/", re.I)),
    ("news", re.compile(r"\bnews\b|\bheadlines?\b|\barticles?\b|\bin\s+the\s+press\b|\bon\s+the\s+web\b", re.I)),
    ("release", re.compile(r"\bguidance\b|\boutlook\b|\bmanagement\b|\bresults\s+release\b|\bpress\s+release\b|"
                           r"\bearnings\s+(?:release|call)\b|\bwhat\s+did\s+(?:the\s+company|they|it)\s+say\b", re.I)),
    ("checks", re.compile(r"\bself[- ]?check\w*|\bhallucinat\w*|\bfact[- ]?check\w*|\bcan\s+i\s+trust\b|"
                          r"\bhow\s+(?:was|is|were|are)\s+(?:this|it|the|these)(?:\s+\w+){0,2}\s+(?:checked|verified|made|built)\b|"
                          r"\bverif\w+|\baccura\w+|\breliab\w+|\bmade[- ]up\b", re.I)),
)
NOT_A_RECOMMENDATION = "These points are chosen by fixed rules on the filed figures. They are not a recommendation."
NO_SUCH_PART = "This report does not hold that part."
_Q_RE = re.compile(r"\bQ([1-4])\s*(?:FY\s*)?'?((?:19|20)\d{2})\b", re.I)
_YEAR_RE = re.compile(r"\b(?:FY\s*|fiscal\s+(?:year\s+)?)?((?:19|20)\d{2})\b", re.I)
_TOKEN_RE = re.compile(r"\[\[F:([a-z0-9_]+)\|([A-Za-z0-9-]+)\]\]")
_DIGIT_RE = re.compile(r"\d")

# computed ratios worth showing next to a metric (tokens only; values stay in the ledger)
_RELATED: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue_growth",),
    "net_income": ("net_margin", "net_income_growth"),
    "operating_income": ("operating_margin",),
    "gross_profit": ("gross_margin",),
    "gross_margin": ("gross_profit", "revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"),
    "revenue_growth": ("revenue",),
    "net_income_growth": ("net_income",),
    "operating_cash_flow": ("free_cash_flow",),
    "free_cash_flow": ("operating_cash_flow", "capex", "fcf_margin"),
    "fcf_margin": ("free_cash_flow", "revenue"),
    "capex": ("free_cash_flow",),
    "return_on_equity": ("net_income", "shareholders_equity"),
    "return_on_assets": ("net_income", "total_assets"),
    "long_term_debt": ("debt_to_equity",),
    "debt_to_equity": ("long_term_debt", "shareholders_equity"),
    "shareholders_equity": ("return_on_equity",),
    "total_assets": ("return_on_assets",),
}

_SYSTEM = (
    "You answer one question about a company's reported figures.\n"
    "Rules:\n"
    "1. Answer in 1 to 3 sentences using only the tokens listed below.\n"
    "2. Write every figure as its exact token, e.g. [[F:revenue|FY2024]]. Never write a digit, "
    "a number, a year or a percentage yourself; use the period words given next to each token.\n"
    "3. Inform only. Never advise, recommend, predict or judge whether to buy, sell or hold.\n"
    f"4. If the tokens do not answer the question, reply exactly {NOT_COVERED}"
)


@dataclass
class Answer:
    html: str
    text: str
    withheld: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    kind: str = "answer"  # "answer" | "dont_know" | "no_advice"


# ---- loading --------------------------------------------------------------------------------
def _ledger_paths(report: str) -> list:
    base = settings.reports_dir()
    stem = report.rsplit(".", 1)[0]
    return [base / f"{stem}.ledger.json", base / f"{stem}.html.ledger.json"]


EXTRA_KEYS = ("thesis", "risk_themes", "multiples", "review", "valuation", "news", "release")


def load_ledger(payload: dict) -> tuple[Ledger, dict] | None:
    """The ledger saved beside the report named by `payload["file"]` or `payload["job_id"]`,
    and the company dict saved with it. None when the name is invalid or nothing is saved."""
    loaded = load_report(payload)
    return None if loaded is None else (loaded[0], loaded[1])


def load_report(payload: dict) -> tuple[Ledger, dict, dict] | None:
    """`load_ledger` plus the report's other saved parts (bull and bear points, risk themes,
    multiples, self-check counts) as a dict; a part that was not saved is simply absent."""
    if not isinstance(payload, dict):
        return None
    name = None
    file = payload.get("file")
    job_id = payload.get("job_id")
    if isinstance(file, str) and file:
        if not contract.REPORT_FILE_RE.fullmatch(file):
            return None
        name = file
    elif isinstance(job_id, str) and job_id:
        if not contract.JOB_ID_RE.fullmatch(job_id):
            return None
        reports = settings.reports_dir()
        if not reports.is_dir():
            return None
        tail = f"_{job_id[:8]}.html"
        matches = sorted(p.name for p in reports.iterdir()
                         if p.name.endswith(tail) and contract.REPORT_FILE_RE.fullmatch(p.name))
        if not matches:
            return None
        name = matches[0]
    if not name:
        return None
    for path in _ledger_paths(name):
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ledger = Ledger.from_json(data)
            except (OSError, ValueError, LedgerError, TypeError):
                return None
            company = data.get("company") if isinstance(data.get("company"), dict) else {}
            extras = {k: data[k] for k in EXTRA_KEYS if isinstance(data.get(k), (dict, list)) and data[k]}
            return ledger, dict(company), extras
    return None


# ---- resolving the question (code only) -----------------------------------------------------
def _is_fy(period: str) -> bool:
    return bool(re.fullmatch(r"FY\d{4}", period))


def _newest(ledger: Ledger, key: str) -> str | None:
    periods = [p for p in ledger.periods(key)
               if (f := ledger.get(key, p)) is not None and f.value is not None]
    fy = [p for p in periods if _is_fy(p)]
    if fy:
        return fy[0]
    return periods[0] if periods else None


def _match_period(ledger: Ledger, key: str, period: str) -> str:
    """The period the ledger uses for `key` when the question says `period`: balance-sheet items
    are held by date, so FY2023 maps to that year's recorded end date (or a date in 2023)."""
    if ledger.get(key, period) is not None:
        return period
    m = re.fullmatch(r"FY(\d{4})", period)
    if m:
        end = ledger.period_end(period)
        if end and ledger.get(key, end) is not None:
            return end
        dated = [p for p in ledger.periods(key) if re.fullmatch(rf"{m.group(1)}-\d{{2}}-\d{{2}}", p)]
        if dated:
            return dated[0]
    return period


def resolve(question: str, ledger: Ledger) -> dict:
    """{"metrics": [...], "periods": [...], "advice": bool, "pairs": [(key, period), ...],
    "topics": [...]}  (topics: parts of the saved report the question asks for, see _TOPICS)"""
    q = question or ""
    work = q
    found: list[str] = []
    for rx, key in _SYNONYM_RES:
        if rx.search(work):
            if key not in found:
                found.append(key)
            work = rx.sub(" ", work)
    if re.search(r"\bgrowth|\bgrow\b|\bgrew\b", work, re.I) and not any(k.endswith("_growth") for k in found):
        # "how did it grow" next to a metric that has a growth series
        for base in ("revenue", "net_income"):
            if base in found:
                found[found.index(base)] = f"{base}_growth"
    advice = bool(_ADVICE_RE.search(q))

    explicit: list[str] = []
    rest = q
    for m in _Q_RE.finditer(q):
        explicit.append(f"Q{m.group(1)}-{m.group(2)}")
    rest = _Q_RE.sub(" ", rest)
    for m in _YEAR_RE.finditer(rest):
        p = f"FY{m.group(1)}"
        if p not in explicit:
            explicit.append(p)

    pairs: list[tuple[str, str]] = []
    periods: list[str] = []
    for key in found:
        if explicit:
            for p in explicit:
                pairs.append((key, _match_period(ledger, key, p)))
        else:
            newest = _newest(ledger, key)
            if newest:
                pairs.append((key, newest))
    for _k, p in pairs:
        if p not in periods:
            periods.append(p)
    if not pairs:
        periods = list(explicit)
    topics = [name for name, rx in _TOPICS if rx.search(q)]
    return {"metrics": found, "periods": periods, "advice": advice, "pairs": pairs, "topics": topics}


def covered(ledger: Ledger, metrics: list[str] | None = None) -> str:
    """One sentence saying which years and which kind of source the ledger covers. When the
    question named a metric the ledger holds, the sentence is about THAT metric's years: saying
    "I have figures for 2007 to 2026" while not having that metric for 2009 would mislead."""
    kinds = {s.type for s in ledger.sources()}
    origin = "the company's SEC filings" if "edinet" in kinds else "the report's sources"
    for key in metrics or []:
        own = sorted({int(p[2:]) for p in ledger.periods(key) if _is_fy(p)})
        if own:
            name = metrics_mod.label(key).lower() if hasattr(metrics_mod, "label") else key.replace("_", " ")
            span = f"fiscal {own[0]}" if len(own) == 1 else f"fiscal {own[0]} to fiscal {own[-1]}"
            return f"I have {name} for {span} from {origin}."
    years = sorted({int(p[2:]) for k in ledger.keys() for p in ledger.periods(k) if _is_fy(p)})
    if not years:
        return f"I have no annual figures from {origin} for this company."
    if len(years) == 1:
        return f"I have annual figures for fiscal {years[0]} from {origin}."
    return f"I have annual figures for fiscal {years[0]} to fiscal {years[-1]} from {origin}."


# ---- answering ------------------------------------------------------------------------------
def _held(ledger: Ledger, key: str, period: str) -> Fact | None:
    f = ledger.get(key, period)
    return f if f is not None and f.value is not None else None


def _sentence(f: Fact, ledger: Ledger) -> tuple[str, str]:
    """(html, text) for one fact: "Revenue for fiscal 2023 was <a ...>$383.3 billion</a>."""
    label = _metrics.label(f.key)
    when = fmt.period_label(f.period)
    joiner = "" if when.startswith("as of") else "for "
    return (f"{_html.escape(label)} {joiner}{_html.escape(when)} was {fmt.cited(f, ledger)}.",
            f"{label} {joiner}{when} was {fmt.fact(f)}.")


def _built(facts: list[Fact], ledger: Ledger, lead: str = "") -> tuple[str, str]:
    parts = [_sentence(f, ledger) for f in facts]
    h = " ".join(p[0] for p in parts)
    t = " ".join(p[1] for p in parts)
    if lead:
        h = f"{_html.escape(lead)} {h}".strip()
        t = f"{lead} {t}".strip()
    return h, t


def _citations(facts: list[Fact], ledger: Ledger) -> list[dict]:
    out: dict[str, dict] = {}
    for f in facts:
        for s in ledger.cite(f):
            out.setdefault(s.id, s.as_dict())
    return list(out.values())


def _plain(html_text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", html_text)).strip()


def _prior(ledger: Ledger, key: str, period: str) -> str | None:
    m = re.fullmatch(r"FY(\d{4})", period)
    if m:
        return f"FY{int(m.group(1)) - 1}"
    periods = ledger.periods(key)
    if period in periods:
        i = periods.index(period)
        return periods[i + 1] if i + 1 < len(periods) else None
    return None


def _packet(facts: list[Fact], ledger: Ledger) -> list[Fact]:
    shown: dict[tuple[str, str], Fact] = {}

    def add(key: str, period: str | None) -> None:
        if not period:
            return
        f = _held(ledger, key, _match_period(ledger, key, period))
        if f is not None:
            shown.setdefault((f.key, f.period), f)

    for f in facts:
        add(f.key, f.period)
    for f in facts:
        add(f.key, _prior(ledger, f.key, f.period))
        for rel in _RELATED.get(f.key, ()):
            add(rel, f.period)
    return list(shown.values())


def _token_line(f: Fact) -> str:
    return f"[[F:{f.key}|{f.period}]] = {_metrics.label(f.key)}, {fmt.period_label(f.period)}"


def _naive(question: str, ledger: Ledger, company: dict, session_id: str) -> Answer:
    """BASELINE ONLY. This path exists solely for the before/after proof (run_cases.py --tag
    before) and is NEVER used by the HTTP route: the model gets labels and raw values as plain
    text and whatever it writes is returned unaudited and uncited."""
    lines = []
    for f in ledger.facts():
        if f.value is not None:
            lines.append(f"{_metrics.label(f.key)} {fmt.period_label(f.period)}: {fmt.fact(f)}")
    name = company.get("name") or company.get("ticker") or "the company"
    messages = [
        {"role": "system", "content": f"You are a helpful financial assistant. Company: {name}.\n"
                                      "Data:\n" + "\n".join(lines[:80])},
        {"role": "user", "content": question},
    ]
    try:
        text = model.ask(messages, session_id=session_id, agent_id=AGENT)
    except llm.LLMError as exc:
        text = f"(model error: {exc})"
    text = (text or "").strip()
    return Answer(html=_html.escape(text), text=text, withheld=[], citations=[], kind="answer")


def _items(rows, key: str = "html") -> list[str]:
    return [str(r[key]) for r in rows or [] if isinstance(r, dict) and isinstance(r.get(key), str) and r[key].strip()]


def _block(title: str, items: list[str]) -> str:
    return f"<p><strong>{_html.escape(title)}</strong></p><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _topical(topics: list[str], extras: dict, ledger: Ledger) -> Answer | None:
    """The answer to a question about a saved part of the report, built in code from that part
    (already checked and linked when the report was made). None when no topic was asked; an
    "I don't know" when a topic was asked and the report does not hold it."""
    if not topics:
        return None
    thesis = extras.get("thesis") if isinstance(extras.get("thesis"), dict) else {}
    blocks: list[str] = []
    extra_cites: list[dict] = []
    points = False
    for topic in topics:
        if topic == "bull" and _items(thesis.get("bull")):
            blocks.append(_block("Bull case", _items(thesis.get("bull"))))
            points = True
        elif topic == "bear" and _items(thesis.get("bear")):
            blocks.append(_block("Bear case", _items(thesis.get("bear"))))
            points = True
        elif topic == "thesis" and _items(thesis.get("thesis")):
            rows = [r for r in thesis.get("thesis") or [] if isinstance(r, dict) and str(r.get("html") or "").strip()]
            blocks.append(_block("Investment thesis", [
                (f"<strong>{_html.escape(str(r['title']))}</strong>: " if r.get("title") else "") + str(r["html"])
                for r in rows]))
        elif topic == "risks":
            rows = []
            for t in extras.get("risk_themes") or []:
                if not isinstance(t, dict) or not str(t.get("title") or "").strip():
                    continue
                line = f"<strong>{_html.escape(str(t['title']))}</strong>"
                if str(t.get("summary_html") or "").strip():
                    line += f": {t['summary_html']}"
                if str(t.get("quote") or "").strip():
                    line += f" <em>\u201c{_html.escape(str(t['quote']))}\u201d</em>"
                rows.append(line)
                src = t.get("source") if isinstance(t.get("source"), dict) else {}
                if str(src.get("url") or "").startswith("https://"):
                    extra_cites.append({"url": src["url"], "title": str(src.get("title") or "SEC filing"),
                                        "date": str(src.get("date") or "")})
            if rows:
                blocks.append(_block("Risk themes from the company's own annual filing (quotes are the filing's words)", rows))
        elif topic == "news":
            news = extras.get("news") if isinstance(extras.get("news"), dict) else {}
            articles = [a for a in news.get("articles") or [] if isinstance(a, dict)
                        and str(a.get("url") or "").startswith("https://") and a.get("title")]
            by_id = {str(a.get("id")): a for a in articles}
            rows = []
            for t in news.get("topics") or []:
                if not isinstance(t, dict) or not t.get("title"):
                    continue
                line = f"<strong>{_html.escape(str(t['title']))}</strong>"
                if str(t.get("summary_html") or "").strip():
                    line += f": {t['summary_html']}"
                rows.append(line)
            for a in articles[:6]:
                rows.append(f'{_html.escape(str(a.get("date_text") or a.get("date") or ""))} · '
                            f'{_html.escape(str(a.get("publisher") or "News"))}: '
                            f'<a href="{_html.escape(str(a["url"]), quote=True)}">{_html.escape(str(a["title"]))}</a>')
                extra_cites.append({"url": str(a["url"]), "title": str(a["title"]), "date": str(a.get("date") or "")})
            if rows and by_id:
                blocks.append(_block(f"Recent news on the web ({news.get('window_text') or 'recent'})", rows)
                              + "<p>News is third-party web coverage; it is not checked against the filings.</p>")
        elif topic == "release":
            release = extras.get("release") if isinstance(extras.get("release"), dict) else {}
            rows = []
            for st in release.get("statements") or []:
                if not isinstance(st, dict) or not str(st.get("quote") or "").strip():
                    continue
                line = f"<strong>{_html.escape(str(st.get('topic') or 'Statement'))}</strong>: "
                if str(st.get("summary_html") or "").strip():
                    line += f"{st['summary_html']} "
                line += f"<em>\u201c{_html.escape(str(st['quote']))}\u201d</em>"
                rows.append(line)
            if rows:
                blocks.append(_block("What the company said in its latest results release (its own words)", rows))
                if str(release.get("url") or "").startswith("https://"):
                    extra_cites.append({"url": str(release["url"]),
                                        "title": str(release.get("source_title") or "Results release"),
                                        "date": str(release.get("filed") or "")})
        elif topic == "valuation":
            valuation = extras.get("valuation") if isinstance(extras.get("valuation"), dict) else {}
            priced = [m for m in valuation.get("methods") or [] if isinstance(m, dict) and m.get("value_text")]
            if priced:
                lines = []
                for m in priced:
                    line = f"<strong>{_html.escape(str(m.get('label') or m.get('key')))}</strong>: {_html.escape(str(m['value_text']))} per share"
                    if m.get("range_text"):
                        line += f" (range {_html.escape(str(m['range_text']))})"
                    if m.get("share_text"):
                        line += f", blend share {_html.escape(str(m['share_text']))}"
                    lines.append(line)
                tail = ""
                blend = valuation.get("blend") if isinstance(valuation.get("blend"), dict) else {}
                if blend.get("value_text"):
                    tail = f"<p>Model value: {_html.escape(str(blend['value_text']))} per share"
                    if blend.get("vs_price_text") and valuation.get("price_text"):
                        tail += (f" ({_html.escape(str(blend['vs_price_text']))} against the last close of "
                                 f"{_html.escape(str(valuation['price_text']))})")
                    tail += ".</p>"
                blocks.append(_block("Valuation methods (model arithmetic)", lines) + tail
                              + "<p>Model arithmetic under stated assumptions. It informs; it is not a recommendation.</p>")
            rows = []
            for m in extras.get("multiples") or []:
                if not isinstance(m, dict) or not m.get("label"):
                    continue
                inputs = ", ".join(str(h) for h in m.get("inputs_html") or [] if isinstance(h, str))
                line = f"<strong>{_html.escape(str(m['label']))}</strong>: {_html.escape(str(m.get('text') or ''))}"
                if inputs:
                    line += f" (from {inputs})"
                rows.append(line)
            if rows:
                note = next((str(m.get("price_note")) for m in extras.get("multiples") or []
                             if isinstance(m, dict) and m.get("price_note")), "")
                blocks.append(_block("Multiples at the last close", rows)
                              + (f"<p>{_html.escape(note)}.</p>" if note else ""))
        elif topic == "checks":
            lines = ["Every figure comes from the company's SEC filings or from arithmetic done in code on "
                     "those figures, and each one links to its filing or its calculation.",
                     "The model never types a number: it writes a placeholder and code fills in the value. "
                     "A sentence with a typed number, an unknown placeholder or advice is removed."]
            review = extras.get("review") if isinstance(extras.get("review"), dict) else {}
            if int(review.get("reviewers_answered") or 0) > 0:
                lines.append(_html.escape(
                    f"Two independent reviewers read {_count(review.get('sentences'), 'sentence')} of this "
                    f"report and removed {_count(review.get('rejected'), 'sentence')}."))
            blocks.append(_block("How this report was checked", lines))
    if not blocks:
        msg = f"{DONT_KNOW} {NO_SUCH_PART}"
        return Answer(html=_html.escape(msg), text=msg, kind="dont_know")
    if points:
        blocks.append(f"<p>{_html.escape(NOT_A_RECOMMENDATION)}</p>")
    out = "".join(blocks)
    by_url: dict[str, dict] = {}
    for src in ledger.sources():
        by_url.setdefault(src.url, src.as_dict())       # the filing itself, not a later note on one of its items
    named = {c["url"]: c for c in extra_cites}          # the part's own title for its link
    cites, seen = [], set()
    for href in re.findall(r'href="(https://[^"]+)"', out):
        url = _html.unescape(href)
        if url not in seen:
            seen.add(url)
            cites.append(by_url.get(url) or named.get(url) or {"url": url, "title": "Source"})
    for c in extra_cites:
        if c["url"] not in seen:
            seen.add(c["url"])
            cites.append(c)
    return Answer(html=out, text=_plain(out), citations=cites, kind="answer")


def _count(value, noun: str) -> str:
    n = int(value or 0)
    return f"{_NUMBER_WORDS.get(n, str(n))} {noun}{'' if n == 1 else 's'}"


_NUMBER_WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
                 8: "eight", 9: "nine", 10: "ten"}


def answer(question: str, ledger: Ledger, company: dict, *, session_id: str,
           checks: bool = True, extras: dict | None = None) -> Answer:
    """Answer one question from the ledger. `checks=True` is the real path (the HTTP route);
    `checks=False` is the unaudited baseline kept only for the before/after demonstration.
    `extras` are the report's other saved parts (see `load_report`)."""
    company = company or {}
    if not checks:
        return _naive(question, ledger, company, session_id)

    r = resolve(question, ledger)
    facts: list[Fact] = []
    for key, period in r["pairs"]:
        f = _held(ledger, key, period)
        if f is not None and f not in facts:
            facts.append(f)

    if r["advice"]:
        if facts:
            h, t = _built(facts, ledger, lead=NO_ADVICE)
            return Answer(html=h, text=t, citations=_citations(facts, ledger), kind="no_advice")
        return Answer(html=_html.escape(NO_ADVICE), text=NO_ADVICE, kind="no_advice")

    if not facts:
        topical = _topical(r.get("topics") or [], extras or {}, ledger)
        if topical is not None:
            return topical
        msg = f"{DONT_KNOW} {covered(ledger, r.get('metrics'))}"
        return Answer(html=_html.escape(msg), text=msg, kind="dont_know")

    packet = _packet(facts, ledger)
    name = company.get("name") or company.get("ticker") or "the company"
    user = (f"Company: {name}\nQuestion: {question}\n\nTokens you may use:\n"
            + "\n".join(_token_line(f) for f in packet))
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]

    withheld: list[str] = []
    out_html = ""
    raw = ""
    try:
        raw = (model.ask(messages, session_id=session_id, agent_id=AGENT) or "").strip()
    except llm.LLMError:
        raw = ""
    if raw and NOT_COVERED not in raw.upper():
        from backend.verify import audit
        try:
            out_html, withheld = audit.apply(raw, ledger)
        except Exception:  # an audit failure never lets unchecked text through
            out_html, withheld = "", [raw]

    # a reply that is only the figure (no words around it) reads worse than the code-built sentence
    wordless = len(re.findall(r"[A-Za-z]{2,}", re.sub(r"<a\b.*?</a>", " ", out_html, flags=re.S))) < 3
    if out_html.strip() and not wordless:
        shown = []
        for key, period in _TOKEN_RE.findall(raw):
            f = _held(ledger, key, period)
            if f is not None and f not in shown and fmt.cited(f, ledger) in out_html:
                shown.append(f)
        if shown:
            return Answer(html=out_html, text=_plain(out_html), withheld=list(withheld),
                          citations=_citations(shown, ledger), kind="answer")
        if not _DIGIT_RE.search(_plain(out_html)):
            # prose with no figure at all: add the figures it is about, built in code
            h, t = _built(facts, ledger)
            return Answer(html=f"{out_html} {h}", text=f"{_plain(out_html)} {t}",
                          withheld=list(withheld), citations=_citations(facts, ledger), kind="answer")
    h, t = _built(facts, ledger)
    return Answer(html=h, text=t, withheld=list(withheld), citations=_citations(facts, ledger),
                  kind="answer")


# ---- HTTP side ------------------------------------------------------------------------------
_ANCHOR_RE = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.S)


def to_markdown(reply: "Answer") -> str:
    """The answer as Markdown, which is what the interface renders (it does not render HTML).

    A figure's link to its filing becomes a Markdown link. A calculated figure's in-page link has
    no target in the chat, so it becomes plain text, and the filings behind it are listed under
    "Sources" with every other source: each number can still be opened at its origin.
    """
    import html as _html

    def link(match: "re.Match") -> str:
        href, label = _html.unescape(match.group(1)), _html.unescape(re.sub(r"<[^>]+>", "", match.group(2)))
        return f"[{label}]({href})" if href.startswith("https://") else label

    text = _ANCHOR_RE.sub(link, reply.html)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.S)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.S)
    text = re.sub(r"\s*<li>", "\n- ", text)
    text = re.sub(r"</ul>\s*|</p>\s*(?=<p>|<ul>)", "\n\n", text)
    text = _html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    lines, seen = [], set()
    for source in reply.citations[:6]:
        url, title = str(source.get("url") or ""), str(source.get("title") or "Source")
        title = re.sub(r"<[^>]*>|[<>\[\]]", "", title).strip() or "Source"     # a title is text, never markup
        if url.startswith("https://") and url not in seen:
            seen.add(url)
            lines.append(f"- [{title}]({url})")
    if lines:
        text += "\n\nSources:\n" + "\n".join(lines)
    return text


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _message_text(msg) -> str:
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content", msg.get("text"))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content
                        if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def stream(payload: dict) -> Iterator[str]:
    """Server-sent events for POST /api/report-chat: keepalives while the answer is built, ONE
    `text` event with the answer as Markdown, and always `done` last (after `error` on a failure)."""
    try:
        if not isinstance(payload, dict):
            raise ValueError("The request is not valid.")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("A question is required.")
        users = [m for m in messages if isinstance(m, dict) and m.get("role", "user") == "user"]
        question = _message_text(users[-1]).strip() if users else ""
        if not question:
            raise ValueError("A question is required.")
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(f"The question is longer than {MAX_QUESTION_CHARS} characters.")
        loaded = load_report(payload)
        if loaded is None:
            raise ValueError("That report is not available.")
    except ValueError as exc:
        yield _event("error", {"message": str(exc)})
        yield _event("done", {})
        return

    ledger, company, extras = loaded
    if not company and isinstance(payload.get("company"), dict):
        company = {k: str(v) for k, v in payload["company"].items() if k in ("name", "ticker")}
    job = payload.get("job_id") if isinstance(payload.get("job_id"), str) else None
    token = job[:8] if job else str(payload.get("file", "")).rsplit("_", 1)[-1].split(".")[0]
    session_id = f"chat-{job or token}"

    box: queue.Queue = queue.Queue(maxsize=1)

    def work() -> None:
        try:
            box.put(("ok", answer(question, ledger, company, session_id=session_id, extras=extras)))
        except Exception:  # noqa: BLE001 - reported to the user as a plain error
            box.put(("error", None))

    threading.Thread(target=work, daemon=True, name=session_id).start()
    while True:
        try:
            status, result = box.get(timeout=KEEPALIVE_SECONDS)
            break
        except queue.Empty:
            yield ": keepalive\n\n"
    if status == "ok":
        yield _event("text", {"text": to_markdown(result)})
    else:
        yield _event("error", {"message": "The answer could not be built. Please try again."})
    yield _event("done", {})
