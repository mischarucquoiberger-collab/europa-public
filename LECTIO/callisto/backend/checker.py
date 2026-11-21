"""Number and quote checker. Fails closed: anything we can't prove is blocked.

Statuses (CHECKER-SPEC.md): VERIFIED (show) · MISMATCH / NOT_FOUND (block).
Every number written in the answer must match an SEC fact, within the rounding the writer used.
"""
import re
from datetime import date

from backend.facts import FACTS, FILING_TEXT_FILES, filing_text

_MULT = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
# ASCII digits only: fullwidth or other Unicode digits are never read as a number (the gate sweep then cuts them)
NUM = r"([0-9][0-9,]*(?:\.[0-9]+)?|(?<!\d)\.[0-9]+)"  # ".5" is 0.5, never a bare "5"
PATTERNS = [  # (regex, kind, scale)
    (re.compile(r"\$\s?" + NUM + r"\s*(trillion|billion|million|thousand|bn|b|m|k)?\b", re.I), "usd", 1.0),
    (re.compile(NUM + r"\s*(trillion|billion|million)\b", re.I), "usd", 1.0),  # "478,834 million"
    (re.compile(NUM + r"\s*(?:bps|bp|basis points?)\b", re.I), "pts", 0.01),  # 188 bps = 1.88 points
    (re.compile(NUM + r"\s*(?:percentage points?|percent points|points|pts|pp)\b", re.I), "pts", 1.0),
    (re.compile(NUM + r"\s*(?:%|percent\b|per cent\b)", re.I), "pct", 1.0),
]


def find_numbers(text: str) -> list[dict]:
    """Every money / percent / points number in the text, with how precisely it was written."""
    found, taken = [], []
    for rx, kind, scale in PATTERNS:
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            raw = m.group(1).replace(",", "")
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            mult = scale * (_MULT.get((m.group(2) or "").lower(), 1.0) if kind == "usd" and m.lastindex >= 2 else 1.0)
            value = float(raw) * mult
            tol = 0.5 * (10 ** -decimals) * mult + 1e-9  # half of the last digit written
            txt = m.group(0).strip()
            found.append(dict(text=txt, value=value, tol=tol, kind=kind, start=m.start(), end=m.end(), raw=raw,
                              dollar=txt.startswith("$")))
            taken.append((m.start(), m.end()))
    return sorted(found, key=lambda n: n["start"])


def _kind_ok(num_kind: str, fact_kind: str, dollar: bool = True) -> bool:
    if num_kind == "usd":
        if fact_kind == "count":  # "52.3 million shares" yes, "$52.3 million" never
            return not dollar
        return fact_kind in ("usd", "usd_per_share")
    return num_kind == fact_kind  # a percent is never a percentage-point fact (1.9% is not 1.9 points)


# ---- direction: "rose 4.8%" must not pass against a fact of -4.76%
_UP = (r"rose|rise[sn]?|rising|increas\w*|up|grew|grow\w*|gain\w*|higher|climb\w*|jump\w*|more|above|larger|greater|"
       r"bigger|surg\w*|soar\w*|rall(?:y|ied|ies)|advanc\w*|expand\w*|improv\w*|added|rais\w*|boost\w*|positive")
_DOWN = (r"fell|fall\w*|decreas\w*|down|declin\w*|drop\w*|lower|less|lost|loss(?:es)?|slid|slipped|shr[au]nk|"
         r"reduc\w*|below|cuts?|cutting|smaller|fewer|sank|sunk|sink\w*|tumbl\w*|plung\w*|dip(?:s|ped|ping)?|"
         r"slump\w*|contract(?:ed|ion|ing)|trimm?\w*|shed|negative|weaker|crater\w*|plummet\w*|collaps\w*|"
         r"sag(?:s|ged|ging)?|erod\w*|slipp?\w*|slid(?:e|es|ing)?|shrink\w*|weaken\w*|retreat\w*|slower|worse|deteriorat\w*|off(?=\s+[$0-9])")
_DIR = re.compile(rf"\b(?:(?P<up>{_UP})|(?P<down>{_DOWN}))\b", re.I)
_SENT_GAP = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
_MINUS, _PLUS = "-\u2212\u2013\u2012\u2014\u2015\u2010\u2011\ufe63\uff0d\ufe58", "+\uff0b"
# "not lower", "did not grow", "didn't fall": the direction word means the opposite ("not only" is not a negation)
_NEG = re.compile(r"(?:\b(?:not|never)\s+(?!only\b)|n['’]t\s+)(?:\w+\s+){0,2}$|\bno\s+$", re.I)


def is_change_fact(fid: str) -> bool:
    """Facts that can be negative and carry a direction: year-over-year changes and price returns."""
    return "_change_" in fid or fid.startswith("ret_")


def _bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Start and end of the sentence that holds text[start:end]."""
    lo, hi = 0, len(text)
    for m in _SENT_GAP.finditer(text):
        if m.end() <= start:
            lo = m.end()
        elif m.start() >= end:
            hi = m.start()
            break
    return lo, hi


def _dir_sign(chunk: str, m) -> int:
    sign = 1 if m.group("up") else -1
    return -sign if _NEG.search(chunk[:m.start()]) else sign


def _sign_pos(text: str, start: int) -> int:
    """Index of a sign written on the number at `start` ("-$8.98", "\u2212 $8.98", "- 4.8%"), or -1."""
    i = start - 1
    while i >= 0 and text[i] in " \t\u00a0\u2009\u202f":
        i -= 1
    if i >= 0 and text[i] in _MINUS + _PLUS and (i < 1 or not text[i - 1].isalnum()):
        return i
    return -1


def _sign_prefix(text: str, start: int) -> int:
    i = _sign_pos(text, start)
    if i < 0:
        return 0
    return 1 if text[i] in _PLUS else -1


def _in_parentheses(text: str, start: int, end: int) -> bool:
    return text[start - 1:start] == "(" and text[end:end + 1] == ")"


def stated_direction(text: str, num: dict, prev_end: int = 0) -> tuple[int, bool]:
    """(+1 up / -1 down / 0 not said) for one number, and whether its sentence has any 'down' word.
    A sign written on the number wins; then the nearest direction word between the previous number and
    this one; then the first word after it ("4.8% lower"); then accounting brackets, "(15.1%)" = minus.
    A negated word counts as its opposite ("not lower" is not a fall)."""
    start, end = num["start"], num.get("end", num["start"] + len(num["text"]))
    lo, hi = _bounds(text, start, end)
    sentence = text[lo:hi]
    signs = [_dir_sign(sentence, m) for m in _DIR.finditer(sentence)]
    any_down = any(s < 0 for s in signs)
    if sign := _sign_prefix(text, start):
        return sign, any_down
    gap_lo = max(lo, min(prev_end, start))
    before = list(_DIR.finditer(text[lo:start]))
    before = [m for m in before if lo + m.start() >= gap_lo]
    if before:
        return _dir_sign(text[lo:start], before[-1]), any_down
    after = re.match(r"\s*([A-Za-z]+)", text[end:hi])
    m = _DIR.fullmatch(after.group(1)) if after else None
    if m:
        return (1 if m.group("up") else -1), any_down
    if _in_parentheses(text, start, end) and not any(s > 0 for s in signs):
        return -1, any_down
    # Red-team #1: a direction word anywhere in the sentence ("saw a 15.1% decline") counts; nearest wins.
    near = min(_DIR.finditer(sentence), default=None,
               key=lambda m: min(abs(lo + m.start() - end), abs(lo + m.end() - start)))
    if near:
        return _dir_sign(sentence, near), any_down
    return 0, any_down


def direction_ok(fid: str, fact: dict, stated: tuple[int, bool] | None) -> bool:
    if stated is None or not is_change_fact(fid) or fact["value"] == 0:
        return True
    sign, any_down = stated
    if fact["value"] > 0:
        return sign >= 0
    return sign < 0 or (sign == 0 and any_down)  # a fall must be written as a fall


# ---- binding: a number must belong to the metric, year, period and date its sentence names
# Without this, "$478.8 billion" (revenue) passed as net income, as fiscal 2025, or as any other line.
_FAMILY_RX = {name: re.compile(rx, re.I) for name, rx in {
    "revenue": r"\brevenues?\b|\bsales\b|\btop[- ]line\b",
    "gross_margin": r"\bgross (?:margin|profit)s?\b",
    "rnd": r"\br\s?&\s?d\b|\bresearch (?:and|&) development\b",
    "operating_income": r"\boperating (?:income|profit|earnings|loss)\b",
    "net_income": r"\bnet (?:income|profit|earnings|loss)\b|\bbottom[- ]line\b|(?<!gross )(?<!operating )\bprofits?\b|"
                  r"\bearnings\b(?! per)",
    "eps_diluted": r"\beps\b|\bearnings\b|\bper diluted share\b",
    "cash": r"\bcash\b",
    "buybacks": r"\bbuy-?backs?\b|\brepurchas\w*|\b(?:bought|buying|buy) back\b|\bshareholders?\b",
    "px_close": r"\bclos(?:e|ed|es|ing)\b|\bprices?\b|\bstock\b|\bshares\b(?! (?:outstanding|traded|were traded))|"
                r"\btrad(?:es|ed|ing) at\b",
    "px_open": r"\bopen(?:ed|ing|s)?\b",
    "px_high": r"\bhighs?\b|\bhighest\b|\brang(?:e|ed|ing)\b|\bbetween\s*(?:\$|\Z)",
    "px_low": r"\blows?\b|\blowest\b|\brang(?:e|ed|ing)\b|\bbetween\s*(?:\$|\Z)",
    "volume": r"\bvolume\b|\bshares (?:were )?traded\b|\bchanged hands\b",
    "market_cap": r"\bmarket cap(?:itali[sz]ation)?\b|\bmarket value\b|\bvaluation\b",
    "shares_outstanding": r"\bshares outstanding\b|\boutstanding shares\b|\bshare count\b",
    "ret": r"\breturn(?:s|ed)?\b|\bstock\b|\bshares\b(?! (?:outstanding|traded|were traded))|\bprices?\b|"
           r"\bperformance\b|\bon the day\b",
}.items()}
_PERIOD_RX = {name: re.compile(rx, re.I) for name, rx in {
    "1d": r"\b(?:one|1|a|single|past|last|previous|prior|latest)[- ]day\b|\bdaily\b|\bday before\b|\btrading day\b|"
          r"\bsession\b|\byesterday\b|\bon the day\b|\btoday\b",
    "1w": r"(?<!52[- ])\bweek\b|\bweekly\b|\b(?:five|5)[- ](?:trading[- ])?days?\b",
    "1m": r"(?<!three[- ])(?<!3[- ])(?<!six[- ])(?<!6[- ])\bmonth\b|\bmonthly\b",
    "3m": r"\b(?:three|3)[- ]months?\b|\bquarter(?:ly)?\b",
    "6m": r"\b(?:six|6)[- ]months?\b|\bhalf[- ]year\b|\bhalf a year\b",
    "ytd": r"\byear[- ]to[- ]date\b|\bytd\b|\b(?:start|beginning) of (?:the|this) year\b|\bthis year\b|\bso far in\b",
    "1y": r"\b(?:one|1|a|past|last|previous|prior|trailing)[- ]year\b|\b(?:12|twelve)[- ]months?\b|"
          r"\b52[- ]weeks?\b(?! (?:high|low|range))",
}.items()}
_YEAR_AFTER = re.compile(r"\s*(?:per (?:diluted )?share)?,?\s*(?:(?:in|for|during|at the end of|as of)\s+)?(?:the\s+)?"
                         r"(?:(?:fiscal(?:\s+year)?|fy)\s*)?((?:19|20)[0-9]{2})\b", re.I)
_YEAR_ANY = re.compile(r"\b(?:fy\s?)?((?:19|20)[0-9]{2})\b", re.I)
_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
           r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
_DATE_RX = re.compile(rf"\b[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\b|\b(?:{_MONTHS})\.?\s+[0-9]{{1,2}}(?:,\s*[0-9]{{4}})?(?![0-9])|"
                      r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}\b", re.I)
_LEVEL_DIR = re.compile(rf"\b(?:(?P<up>{_UP})|(?P<down>{_DOWN}))\s+(?P<prep>to|from)\s+"
                        r"(?:(?:about|roughly|nearly|approximately|around|almost|just|only|a record)\s+)*$", re.I)
# Red-team #3: "$8.98 the year before" puts the number in the prior year.
_PRIOR_AFTER = re.compile(r"\s*,?\s*(?:in\s+|for\s+)?(?:the\s+year\s+before|the\s+(?:prior|previous|preceding)\s+(?:fiscal\s+)?year|"
                          r"(?:a|one)\s+year\s+(?:earlier|before|ago|prior)|last\s+(?:fiscal\s+)?year|"
                          r"(?:prior|previous)\s+(?:fiscal\s+)?year)\b", re.I)
# "$226.10 the day before": the number is the prior session's close, whatever date the sentence names.
_DAY_BEFORE_AFTER = re.compile(r"\s*,?\s*(?:on\s+)?(?:the\s+(?:day|session|trading day)\s+before|the\s+(?:prior|previous)\s+"
                               r"(?:day|session|trading day|close)|a\s+day\s+earlier)\b", re.I)
# "$33.02 on the last trading day, down from $35.08 on 2026-11-19": the first number is the latest close even
# though the only date in the sentence belongs to the close before.
_LAST_DAY_AFTER = re.compile(r"\s*,?\s*(?:on|at|as of)\s+the\s+(?:last|latest|most recent)\s+"
                             r"(?:trading day|trading session|session|close)\b", re.I)
_LAST_DAY_ANY = re.compile(r"\b(?:on|at|as of)\s+the\s+(?:last|latest|most recent)\s+(?:trading day|trading session|session|close)\b", re.I)
# "$478.8 billion in fiscal 2026 was lower than the year before": a level compared with the prior year.
_THAN_PRIOR = re.compile(r"[^.!?]*?\b(?:was|were|is|came in)\s+(?:(?P<up>higher|larger|greater|bigger|more)|"
                         r"(?P<down>lower|smaller|less|weaker))\s+than\s+(?:in\s+)?(?:the\s+year\s+before|"
                         r"(?:a|one)\s+year\s+(?:earlier|before|ago)|the\s+(?:prior|previous)\s+(?:fiscal\s+)?year|"
                         r"last\s+(?:fiscal\s+)?year)\b", re.I)
_LOSS = re.compile(r"\bloss(?:es)?\b", re.I)
# Fix C: profit written as a loss right before the number ("lost $X", "a negative $X", "in the red by $X")
_LOSS_TAIL = re.compile(r"(?:\blost|\bloss(?:es)? of|\bnegative|\bin the red(?:\s+(?:by|at))?|\bdeficit of)\s+"
                        r"(?:(?:about|roughly|nearly|approximately|around|almost|a|an)\s+)*$", re.I)
# Fix C: things we hold no fact for. Blocks a number only when the word sits in the same clause, before the number.
_CLAUSE_SPLIT = re.compile(r"[,;:()\u2014\u2013]|\b(?:but|while|whereas|although|though|however|and|so|since|because|"
                           r"instead|unlike|than|versus|vs)\b", re.I)
_COMPANIES = r"microsoft|samsung|google|alphabet|amazon|tesla|nvidia|meta|netflix|intel|huawei|xiaomi|sony"
_UNKNOWN_SCOPE = re.compile(
    r"\bdividends?\b|\bdebt\b|\bborrowings\b|\b(?:operating|net|profit|ebitda|pre-?tax)\s+margins?\b|"
    r"\b(?:iphone|mac|ipad|services|wearables|airpods)\s+(?:\w+\s+)?(?:revenue|sales|net sales)\b|"
    r"\b(?:q[1-4]|(?:first|second|third|fourth)[- ]quarter|quarterly)\b|"
    rf"\b(?:{_COMPANIES})(?:['\u2019]s)?\s+(?:\w+\s+){{0,3}}?(?:revenue|sales|net sales|income|profit|earnings|eps|"
    r"cash|buybacks?|margin)\b", re.I)
_UNKNOWN_AFTER = re.compile(r"\s*(?:in|for|during)\s+(?:the\s+)?(?:q[1-4]\b|(?:first|second|third|fourth)[- ]quarter\b)", re.I)
_MARGIN_RATE = re.compile(r"\bmargin\s+(?:percentage|rate|ratio)\b|\bmargin\s+(?:percent|%)", re.I)
_WHY = {"metric": "{label} is a different figure from the one this sentence names.",
        "year": "{label} is for a different fiscal year than this sentence says.",
        "period": "{label} covers a different time window than this sentence says.",
        "date": "{label} is from a different date than this sentence says.",
        "direction": "Direction does not match the source for {label}."}


def expand_dates(iso_dates) -> list[str]:
    """'2026-11-20' -> the ways a writer may print that date. Values that do not parse are skipped."""
    out = []
    for raw in iso_dates or ():
        try:
            d = date.fromisoformat(str(raw).strip()[:10])
        except (TypeError, ValueError):
            continue
        month, mon = d.strftime("%B"), d.strftime("%b")
        forms = [d.isoformat(), f"{month} {d.day}, {d.year}", f"{mon} {d.day}, {d.year}", f"{mon}. {d.day}, {d.year}",
                 f"{month} {d.day}", f"{mon} {d.day}", f"{d.month}/{d.day}/{d.year}",
                 f"{d.month:02d}/{d.day:02d}/{d.year}"]
        for f in forms:
            if f not in out:
                out.append(f)
    return out


def _date_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(".", "")).strip().lower()


def fact_tags(fid: str) -> dict:
    """What a fact id is about: metric family, fiscal year, return window. None where it has none."""
    family = year = period = None
    if m := re.fullmatch(r"(.+)_fy((?:19|20)[0-9]{2})", fid):
        family, year = m.group(1), int(m.group(2))
    elif m := re.fullmatch(r"(.+)_change_(?:pct|amount|pts)", fid):
        family = m.group(1)
    elif m := re.fullmatch(r"ret_(\w+)_pct", fid):
        family, period = "ret", m.group(1)
    elif fid.startswith("px_close"):
        family = "px_close"
    elif fid in ("px_open_last", "volume_last", "market_cap", "shares_outstanding"):
        family = fid.removesuffix("_last")
    elif fid in ("px_high_last", "px_52w_high"):
        family = "px_high"
    elif fid in ("px_low_last", "px_52w_low"):
        family = "px_low"
    if family == "gross_margin_pct":  # "gross margin" names both the dollar line and the percentage
        family = "gross_margin"
    return {"family": family if family in _FAMILY_RX else None, "year": year, "period": period}


_PRIOR_WORD = re.compile(r"\b(?:from|than|prior|previous|preceding|before|earlier|yesterday|versus|vs|compared)\b", re.I)
_PRIOR_TAIL = re.compile(r"\b(?:day|session) before\b|\b(?:previous|prior|preceding) (?:trading )?(?:day|session|close)\b|\byesterday\b", re.I)
_PRIOR_STRICT = re.compile(r"\b(?:prior|previous|preceding|yesterday)\b|\b(?:day|session) before\b", re.I)
# windows the market pack has no return or price for: "over two years", "a month ago", "since 2020"
_OTHER_WINDOW = re.compile(
    r"\b(?:two|2|three|3|four|4|five|5|ten|10)[- ]years?\b|\b(?:two|2|four|4|five|5|seven|7|eight|8|nine|9|ten|10|"
    r"eleven|11)[- ]months?\b|\b(?:two|2|three|3|four|4)[- ]weeks?\b|\bsince (?:19|20)[0-9]{2}\b|"
    r"\ball[- ]time\b|\bdecade\b|\bsince (?:inception|its ipo)\b", re.I)
_AGO_WINDOW = re.compile(r"\b(?:an?|one|two|three|four|five|six|[0-9]+)[- ](?:weeks?|months?|years?) ago\b|"
                         r"\blast (?:week|month|year|quarter)\b|\bearlier this (?:week|month|year)\b", re.I)
_CHANGE_WORD = re.compile(r"\b(?:change[ds]?|difference|growth|increase|decrease|swing|delta|year[- ]over[- ]year|yoy|"
                          r"y/y|compared|versus|vs)\b", re.I)
_CLOSE_WORD = re.compile(r"\bclos(?:e|ed|es|ing)\b|\btrad(?:es|ed|ing) at\b", re.I)


_FISCAL_FAMILIES = {"revenue", "gross_margin", "rnd", "operating_income", "net_income", "eps_diluted", "cash", "buybacks"}
_FISCAL_YEAR = r"(?:fiscal(?:\s+year)?\s+|fy\s*)((?:19|20)[0-9]{2})\b"
_FISCAL_SPAN = re.compile(rf"\bbetween\s+{_FISCAL_YEAR}\s+and\s+{_FISCAL_YEAR}", re.I)
_MARGIN_DOLLAR = re.compile(
    rf"^(?:apple\s+)?kept\s+{NUM}\s*%\s+of each sales dollar after the cost of making its products[.!?]?$", re.I)
_MARGIN_SHARE = re.compile(rf"^(?:it was|that is)\s+{NUM}\s*%\s+of net sales\b", re.I)


def _families(text: str) -> set:
    found = {name for name, rx in _FAMILY_RX.items() if rx.search(text)}
    # "the stock opened at $X": "stock" alone means the close only when no other price point is named
    if found & {"px_open", "px_high", "px_low"} and not _CLOSE_WORD.search(text):
        found.discard("px_close")
    return found


_COMPARE_WORD = re.compile(r"\b(?:last|prior|previous|preceding|before|earlier|ago|versus|vs|from|compared|than|"
                          r"year[- ](?:over|on)[- ]year|ytd|quarter|q[1-4])\b", re.I)
_LEAD_FISCAL = re.compile(r"\b(?:fiscal(?:\s+year)?|fy)\s*((?:19|20)[0-9]{2})\b", re.I)


def _lead_year(text: str, lo: int, sentence: str):
    """The one fiscal year the sentence just before names, when this sentence names no year or comparison."""
    if _YEAR_ANY.search(sentence) or _COMPARE_WORD.search(sentence):
        return None
    prev = _SENT_GAP.split(text[:lo].rstrip())[-1] if text[:lo].strip() else ""
    years = {int(y) for y in _LEAD_FISCAL.findall(prev)}
    return years.pop() if len(years) == 1 and not _COMPARE_WORD.search(prev) else None


def context(text: str, num: dict, prev_end: int = 0) -> dict:
    """What the words around one number say it is: metric, fiscal year, time window, date.
    The metric is read from the words between the previous number and this one; if there are none, from
    the whole sentence; if still none, from the nearest earlier sentence that names a metric."""
    start, end = num["start"], num.get("end", num["start"] + len(num["text"]))
    sign = _sign_prefix(text, start)
    if _in_parentheses(text, start, end):
        sign = -1
        end += 1
    if _sign_pos(text, start) >= 0:
        start = _sign_pos(text, start)
    lo, hi = _bounds(text, start, end)
    sentence, gap = text[lo:hi], text[max(lo, min(prev_end, start)):start]
    families = _families(gap) or _families(sentence)
    # "EPS was $8.98. That is up from $7.46 ..., which means more profit than the year before.": the sentence points
    # back ("That is") and names no metric before its first number, so the metric is the previous sentence's one,
    # not a word that trails after the numbers.
    if not _families(gap) and not _families(text[lo:start]) and re.match(r"\s*(?:that|this|it)(?:\s+is|\s+was|'s)\b", sentence, re.I):
        back = _families(_SENT_GAP.split(text[:lo].rstrip())[-1]) if text[:lo].strip() else set()
        if len(back) == 1:
            families = back
    year_start, inherited_year, margin_share = end, None, False
    if families & {"px_high", "px_low"} and (span := _FISCAL_SPAN.search(sentence)):
        fiscal = _families(_FISCAL_SPAN.sub("", gap)) or _families(_FISCAL_SPAN.sub("", sentence))
        if len(fiscal) == 1 and fiscal <= _FISCAL_FAMILIES:
            families = fiscal
            # A from/to comparison starts in the earlier fiscal year.
            if re.search(r"\bfrom\s*$", gap, re.I):
                inherited_year = min(map(int, span.groups()))
            elif gap.strip().lower() == "to":
                inherited_year = max(map(int, span.groups()))

    if _MARGIN_DOLLAR.fullmatch(sentence):
        families, margin_share = {"gross_margin"}, True
    elif num["kind"] in ("pct", "pts") and (share := _MARGIN_SHARE.match(sentence)):
        previous = _SENT_GAP.split(text[:lo].rstrip())[-1]
        # Treat "of net sales" as the denominator only with an explicit margin antecedent.
        if _families(previous) <= {"gross_margin"}:  # no other metric named just before
            tail = sentence[share.end():]
            if _families(tail) <= {"gross_margin"}:
                families, margin_share = {"gross_margin"}, num["kind"] == "pct"
                if start == lo + share.start(1):
                    year_start = lo + share.end()
                    years = set(_YEAR_ANY.findall(previous))
                    if len(years) == 1:
                        inherited_year = int(years.pop())
    if not families:
        for earlier in reversed(_SENT_GAP.split(text[:lo])):
            families = _families(earlier)
            if families:
                break
    after = _YEAR_AFTER.match(text[year_start:hi])
    prior = bool(_PRIOR_AFTER.match(text[year_start:hi]))
    year = inherited_year if not prior else None
    if after:
        year = int(after.group(1))
    clause = _CLAUSE_SPLIT.split(gap)[-1] if gap else ""
    unknown = bool(_UNKNOWN_SCOPE.search(clause) or _UNKNOWN_AFTER.match(text[end:hi]))
    return {"families": families, "gap": gap, "sentence": sentence, "sign": sign, "unknown": unknown,
            "margin_share": margin_share, "prior_after": prior,
            "than_prior": (lambda m: 0 if not m else (1 if m.group("up") else -1))(_THAN_PRIOR.match(text[end:hi])),
            "day_before": bool(_DAY_BEFORE_AFTER.match(text[end:hi])),
            "last_day_after": bool(_LAST_DAY_AFTER.match(text[end:hi])),
            "year": year, "year_end": year_start + after.end() if after else end,
            "gap_years": {int(y) for y in _YEAR_ANY.findall(gap)},
            "sent_years": {int(y) for y in _YEAR_ANY.findall(sentence)},
            "years_after": {int(y) for y in _YEAR_ANY.findall(text[end:hi])},
            "lead_year": _lead_year(text, lo, sentence), "compare": bool(_COMPARE_WORD.search(sentence)),
            "periods": {name for name, rx in _PERIOD_RX.items() if rx.search(sentence)},
            "dates": [_date_key(m.group(0)) for m in _DATE_RX.finditer(sentence)]}


def _level_problem(fid: str, f: dict, ctx: dict, facts: dict) -> bool:
    """"rose to $X" / "down from $X" on a level figure must agree with the figure it is compared with."""
    m = _LEVEL_DIR.search(ctx["gap"])
    if not m and ctx.get("than_prior") and fid.endswith("_fy2026") and not is_change_fact(fid):
        earlier = fid[:-4] + "2025"
        diff = f["value"] - facts[earlier]["value"] if earlier in facts else 0
        return diff != 0 and (diff > 0) != (ctx["than_prior"] > 0)
    if not m or is_change_fact(fid):
        return False
    want = 1 if m.group("up") else -1
    earlier = later = None
    if fid.endswith("_fy2026"):
        earlier = fid[:-4] + "2025"
    elif fid.endswith("_fy2025"):
        later = fid[:-4] + "2026"
    elif fid == "px_close_last":
        earlier = "px_close_prior"
    elif fid == "px_close_prior":
        later = "px_close_last"
    if m.group("prep").lower() == "to":
        diff = f["value"] - facts[earlier]["value"] if earlier in facts else 0
    elif fid.endswith("_fy2026"):
        return True  # nothing later than the latest fiscal year can be "up/down from" it
    else:
        diff = facts[later]["value"] - f["value"] if later in facts else 0
    return diff != 0 and (diff > 0) != (want > 0)


def problem(fid: str, f: dict, stated=None, ctx: dict | None = None, facts: dict | None = None) -> str | None:
    """Why this fact cannot back the number as written (a key of _WHY), or None if it can."""
    if ctx:
        tags = fact_tags(fid)
        div_fact = fid.startswith("div_")
        div_named = bool(re.search(r"\bdividends?\b|\byield\b", ctx["sentence"], re.I))
        if div_fact and not div_named:
            return "metric"  # a dividend fact only backs a number in a sentence that names the dividend or yield
        if ctx.get("unknown") and not (div_fact and div_named):
            return "metric"  # Fix C: the number is attached to a dividend, debt, segment, quarter or other company
        if "_change_" in fid and not ctx["sign"] and not (_DIR.search(ctx["sentence"]) or _CHANGE_WORD.search(ctx["sentence"])):
            return "metric"  # a change ($62.7 billion more) written as a level ("revenue was $62.7 billion")
        if fid == "gross_margin_change_pct" and _MARGIN_RATE.search(ctx["gap"]):
            return "metric"  # "gross margin percentage rose 19.7%": 19.7% is the dollar change; the rate moved in points
        if tags["family"] and ctx["families"] and tags["family"] not in ctx["families"]:
            # "closed at $X, down 2.8% from $Y the day before": the percent is the return for the window named
            if not (tags["family"] == "ret" and ctx["families"] <= {"px_close"}
                    and (tags["period"] in ctx["periods"] if ctx["periods"] else tags["period"] == "1d")):
                return "metric"
        prior_cue = bool(ctx.get("day_before") or _PRIOR_WORD.search(ctx["gap"]) or _PRIOR_TAIL.search(ctx["sentence"]))
        own_date = bool(ctx["dates"]) and any(
            d in {_date_key(x) for x in expand_dates(f.get("dates") or [f.get("as_of")])} for d in ctx["dates"])
        if fid == "px_close_prior" and not prior_cue and not own_date:
            return "date"  # the prior close is only the prior close when the sentence says "from / before / previous"
        if fid == "px_close_last" and _PRIOR_STRICT.search(_CLAUSE_SPLIT.split(ctx["gap"])[-1] if ctx["gap"] else ""):
            return "date"  # "the previous close was $X" with today's close as $X
        if ctx.get("margin_share") and not fid.startswith("gross_margin_pct_fy"):
            return "metric"
        low = ctx["sentence"].lower()
        if fid.startswith("px_52w") and "52" not in low and "year" not in low:
            return "metric"
        if fid in ("px_high_last", "px_low_last") and re.search(
                r"52[- ]week|\bin a year\b|\b(?:past|last|prior) (?:year|12 months)\b|\byear[- ](?:high|low)\b", low) and not re.search(
                r"intraday|\bday\b|session", low):
            return "metric"
        if not tags["year"] and "_change_" in fid and tags["family"]:
            # a year-over-year change belongs to the latest fiscal year of its metric (Codex #2)
            ys = [int(m.group(1)) for k in (facts or {}) if (m := re.fullmatch(
                re.escape(tags["family"]) + r"(?:_pct)?_fy((?:19|20)[0-9]{2})", k))]
            tags = {**tags, "year": max(ys) if ys else None}
        if tags["year"]:
            if ctx["year"]:
                if ctx["year"] != tags["year"]:
                    return "year"
            elif ctx["gap_years"] and tags["year"] not in ctx["gap_years"]:
                return "year"
            elif (is_change_fact(fid) and len(ctx["sent_years"]) == 1 and not ctx["gap_years"]
                  and not ctx["compare"]
                  and ctx.get("years_after") and tags["year"] not in ctx["years_after"]):  # year must follow the percent
                return "year"  # "rose 15.1% to $X in fiscal 2025": the change is for the one year named
            elif (not is_change_fact(fid) and ctx["lead_year"] and not ctx["gap_years"]
                  and tags["year"] != ctx["lead_year"]):
                return "year"  # "Fiscal 2026 was a record year. Revenue was $416.2 billion."
        if ctx.get("prior_after") and fid.endswith("_fy2026"):
            return "year"
        if tags["period"] and ctx["periods"] and tags["period"] not in ctx["periods"]:
            return "period"
        if tags["period"] and _OTHER_WINDOW.search(ctx["sentence"]):
            return "period"
        if fid in ("px_close_last", "px_close_prior", "px_open_last") and _AGO_WINDOW.search(ctx["sentence"]):
            return "period"
        if fid == "px_close_prior" and prior_cue:
            pass  # a sentence about today may name today's date next to "the close the day before"
        elif ctx.get("day_before") and fid.startswith("px_close"):
            if fid != "px_close_prior":
                return "date"
        elif (dates := f.get("dates") or ([f["as_of"]] if f.get("as_of") else [])) and ctx["dates"]:
            forms = {_date_key(x) for x in expand_dates(dates)}
            if not any(d in forms for d in ctx["dates"]):
                # "$X on the last trading day, down from $Y on <prior date>": allowed only when every date in the
                # sentence is the prior close's own date
                pr = (facts or {}).get("px_close_prior") or {}
                pr_forms = {_date_key(x) for x in expand_dates([pr["as_of"]])} if pr.get("as_of") else set()
                last_close = fid == "px_close_last" and ctx.get("last_day_after")
                # "... on the last trading day, down from $Y on <prior date>, and price return was -6.3% over one day"
                day_move = fid == "ret_1d_pct" and bool(_LAST_DAY_ANY.search(ctx["sentence"]))
                if not ((last_close or day_move) and pr_forms and all(d in pr_forms for d in ctx["dates"])):
                    return "date"
        if not is_change_fact(fid) and f["value"] != 0:
            sign = ctx["sign"]
            loss = tags["family"] in ("net_income", "operating_income") and bool(_LOSS.search(ctx["gap"]) or _LOSS_TAIL.search(ctx["gap"]))
            if (loss and sign > 0) or ((sign < 0 or loss) != (f["value"] < 0)):
                return "direction"
        if _level_problem(fid, f, ctx, facts or {}):
            return "direction"
    return None if direction_ok(fid, f, stated) else "direction"


def fact_pool(ticker: str, extra_facts: dict | None = None, exclude=None) -> dict:
    """SEC facts plus extra (e.g. market-data) facts, minus quarantined ids."""
    pool = {**FACTS.get(ticker, {}), **(extra_facts or {})}
    for fid in exclude or ():
        pool.pop(fid, None)
    return pool


def _value_ok(num: dict, f: dict) -> bool:
    if num["kind"] == "usd" and num["value"] == 0:  # "$0 trillion" has no digits to check against anything
        return False
    return (_kind_ok(num["kind"], f["kind"], num.get("dollar", True))
            and abs(abs(f["value"]) - num["value"]) <= num["tol"])


def match_fact(ticker: str, num: dict, prefer: str | None = None, extra_facts: dict | None = None, exclude=None,
               only=None, stated=None, ctx=None):
    """Return (fact_id, fact) the number matches, preferring the fact the model cited.
    `only`: fact ids the writer cited for this number; when given, no other fact may match.
    `stated`: stated_direction() for the number; a change or return fact must agree with it.
    `ctx`: context() for the number; the fact must be the metric, year, window and date the sentence names."""
    facts = fact_pool(ticker, extra_facts, exclude)
    if only is not None:
        order = [k for k in only if k in facts]
    else:
        order = ([prefer] if prefer in facts else []) + [k for k in facts if k != prefer]
    for fid in order:
        f = facts[fid]
        if _value_ok(num, f) and not problem(fid, f, stated, ctx, {**FACTS.get(ticker, {}), **facts}):
            return fid, f
    return None, None


def _claim_keys(value) -> list:
    """Keys for a claim value so "-1.9%", "\u22121.9%", "+1.9 %" and "1.9%" all map to the number "1.9%"."""
    v = str(value if value is not None else "").replace("\u2212", "-").replace("\u2013", "-")
    v = re.sub(r"\s+", " ", v).strip()
    nums = find_numbers(v)
    if nums:
        return [(n["kind"], n["value"], n["tol"]) for n in nums]
    m = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?|\.[0-9]+", v)
    return [m.group(0).replace(",", "")] if m else []


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def verify_quote(ticker: str, quote: str, year: str) -> bool:
    q = _norm(quote).strip(' ."')
    return len(q) >= 12 and q in _norm(filing_text(ticker, year))


_QUOTE_RX = re.compile(r'["\u201c]([^"\u201c\u201d]{12,})["\u201d]')
# Single-quoted words are held to the same rule: an opening quote follows a space or bracket, a closing one is
# followed by punctuation or a space, and an apostrophe inside a word ("Company's") stays part of the words.
_SQUOTE_RX = re.compile(r"(?<![\w'\u2019])['\u2018]((?:[^'\u2018\u2019\n]|['\u2019](?=\w)){12,}?)['\u2019](?!\w)")


def quoted_spans(text: str) -> list[str]:
    """Text inside double quotes, 12 characters or more: the answer presents it as someone's exact words."""
    return [m.group(1) for m in _QUOTE_RX.finditer(text or "")] + [m.group(1) for m in _SQUOTE_RX.finditer(text or "")]


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text.strip()) if s]


def check(ticker: str, answer: str, model_claims: list[dict], extra_facts: dict | None = None, exclude=None) -> dict:
    """Check the model's answer. Returns the safe answer, per-number claims, and what was blocked."""
    answer = answer.strip()
    facts = fact_pool(ticker, extra_facts, exclude)
    cited = {}  # number (kind, value, rounding) -> fact ids the model said it came from
    for c in model_claims or []:
        if isinstance(c, dict) and c.get("fact_id"):
            for key in _claim_keys(c.get("value")):
                ids = cited.setdefault(key, [])
                if str(c["fact_id"]) not in ids:
                    ids.append(str(c["fact_id"]))

    claims, blocked, bad_spans, prev_end = [], [], [], 0
    bad_sentences = set()
    for num in find_numbers(answer):
        # A number the writer cited a fact for must match THAT fact, not any fact with a close value.
        only = cited.get((num["kind"], num["value"], num["tol"])) or cited.get(num["raw"])
        prefer = next((k for k in only if k in facts), None) if only else None
        stated = stated_direction(answer, num, prev_end)
        ctx = context(answer, num, prev_end)
        prev_end = ctx["year_end"]  # a year written right after a number ("... in fiscal 2026") belongs to it
        fid, f = match_fact(ticker, num, prefer, extra_facts, exclude, only=only, stated=stated, ctx=ctx)
        if f:
            claim = dict(text=num["text"], status="VERIFIED", source=f"{f['source']}: {f['label']}",
                         sec_value=f["value"], fact_id=fid)
            for key in ("as_of", "provider"):
                if f.get(key):
                    claim[key] = f[key]
            claims.append(claim)
            continue
        # The model cited a real fact but wrote the wrong number -> MISMATCH, else NOT_FOUND.
        note = "No SEC or market-data fact matches this number." if extra_facts else "No SEC fact matches this number."
        status = "NOT_FOUND"
        near = next((k for k in (only if only is not None else facts)
                     if k in facts and _value_ok(num, facts[k])), None)
        if near:  # the value matches a fact, but not the metric, year, window, date or direction the sentence says
            status = "MISMATCH"
            why = problem(near, facts[near], stated, ctx, {**FACTS.get(ticker, {}), **facts}) or "direction"
            note = _WHY[why].format(label=facts[near]["label"])
        elif prefer in facts:
            status = "MISMATCH"
            note = f"SEC value for {facts[prefer]['label']} differs."
        elif only:
            note = "The fact cited for this number is not one Europa has."
        claims.append(dict(text=num["text"], status=status, source=None, sec_value=None, note=note))
        bad_sentences.add(_bounds(answer, num["start"], num["end"])[0])

    # Quotes the model says it took from the filing must really be there.
    for c in model_claims or []:
        if c.get("type") == "quote" and c.get("text"):
            ok = verify_quote(ticker, c["text"], c.get("filing", "FY2026"))
            claims.append(dict(text=c["text"], status="VERIFIED" if ok else "NOT_FOUND",
                               source=f"Apple 10-K {c.get('filing', 'FY2026')} text" if ok else None,
                               sec_value=None))
            if not ok:
                bad_spans += [c["text"], *split_sentences(c["text"])]
    # Words shown inside quote marks are checked the same way, even when the writer did not declare them.
    declared = {_norm(c["text"]).strip(' ."') for c in model_claims or []
                if isinstance(c, dict) and c.get("type") == "quote" and isinstance(c.get("text"), str)}
    for span in quoted_spans(answer):
        if _norm(span).strip(' ."') in declared:
            continue
        year = next((y for y in FILING_TEXT_FILES.get(ticker, {}) if verify_quote(ticker, span, y)), None)
        claims.append(dict(text=span, status="VERIFIED" if year else "NOT_FOUND",
                           source=f"Apple 10-K {year} text" if year else None, sec_value=None))
        if not year:
            bad_spans += [span, *split_sentences(span)]

    kept, offset = [], 0
    for s in split_sentences(answer):
        start = answer.index(s, offset)
        offset = start + len(s)
        if start in bad_sentences or any(b in s for b in bad_spans):
            blocked.append(dict(text=s, status="BLOCKED", note="Contains a number or quote the SEC data does not support."))
        else:
            kept.append(s)
    return dict(answer=" ".join(kept), claims=claims, blocked=blocked)
