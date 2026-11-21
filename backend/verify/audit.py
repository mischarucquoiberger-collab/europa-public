"""The audit between the model and the page. The model never writes a figure: it writes
placeholders `[[F:key|period]]` and this module swaps each for the ledger's value and its link.

A sentence is WITHHELD (removed from the page and listed) when:
- a placeholder does not resolve to a ledger fact with a value, or is broken or cut off
  (`[[F:net_margin|FY2024` with no closing brackets, `[F:...]`, `F:key|...]]`);
- after the placeholders are taken out, it still holds a digit that is not on the allow-list
  (years 1990-2100, Q1-Q4, form names 10-K/10-Q/8-K/20-F, "Item 1A"-style item numbers), or a
  figure spelled in words ("percent", "billion", ...);
- it uses advice wording (buy, sell, should, price target, undervalued, ...): this system informs
  and never advises.

Withheld sentences are returned READABLE (see `readable`): a complete placeholder shows as
"[figure]", a cut-off one as "[figure, cut off]", and nothing of the `[[F:` syntax is left.
"""
from __future__ import annotations

import html
import re

from backend import format as fmt

PLACEHOLDER = re.compile(r"\[\[F:([a-z_]+)\|([A-Za-z0-9-]+)\]\]")
FIGURE = "[figure]"
CUT_OFF = "[figure, cut off]"

# placeholder debris, most specific first (see `readable`)
_CLOSED_MALFORMED = re.compile(r"\[\[[^\[\]\n]{0,80}\]\]")        # [[F:Revenue|FY2024]], [[revenue]]
_CUT_PLACEHOLDER = re.compile(r"\[\[[^\[\]\s]*\]?")                # [[F:net_margin|FY2024 (cut off)
_SINGLE_BRACKET = re.compile(r"\[F:[^\[\]\s]*\]")                   # [F:revenue|FY2024]
_SINGLE_CUT = re.compile(r"\[F:[^\[\]\s]*")                          # [F:revenue|FY2
_BARE = re.compile(r"(?<![\w\[])F:[a-z_]+\|[A-Za-z0-9-]*\]{0,2}")     # F:revenue|FY2024]]
_LEFTOVER = re.compile(r"\[\[|\]\]")
_MALFORMED = re.compile(r"\[F:|(?<![\w\[])F:[a-z_]+\|")

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# A full stop after one of these does not end a sentence ("Orchard Devices Inc. reported ...").
_ABBREVIATION_END = re.compile(
    r"\b(?:Inc|Corp|Co|Ltd|LLC|PLC|L\.P|N\.A|S\.A|N\.V|U\.S|U\.K|No|vs|Mr|Ms|Mrs|Dr|St|Jr|Sr|e\.g|i\.e|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")

_ALLOWED_DIGITS = re.compile(
    r"\b(?:199\d|20\d\d|2100)\b"                      # a year
    r"|\bQ[1-4]\b"                                    # a quarter label
    r"|\b(?:10-K|10-Q|8-K|20-F)\b"                    # a form name
    r"|\bItem\s+\d{1,2}[A-C]?\b",                     # an item number
    re.IGNORECASE,
)
_SPELLED_FIGURE = re.compile(
    r"\b(?:percent|per\s+cent|percentage\s+points?|basis\s+points?|hundred|thousand|million|"
    r"billion|trillion)\b", re.IGNORECASE)
_ADVICE = re.compile(
    r"\b(?:buy|buying|sell|selling|should|recommend\w*|undervalued|overvalued|upside|"
    r"downside\s+target|price\s+target|target\s+price|cheap(?:er|est|ly)?|expensive|"
    r"attractive(?:ly)?|opportunit(?:y|ies)|worth\s+considering|bullish|bearish|"
    r"outperform\w*|underperform\w*)\b"
    r"|\bhold(?:s|ing)?\s+(?:the|its|their|your|our|a|this|these)?\s*(?:stock|shares|position)\b",
    re.IGNORECASE)


def find_placeholders(text: str) -> list[tuple[str, str]]:
    """Every (key, period) placeholder in the text, in order."""
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(text or "")]


def readable(text: str) -> str:
    """Text a reader may see: each complete placeholder as "[figure]", a cut-off or broken one as
    "[figure, cut off]", and no `[[F:` syntax left over. Everything else is unchanged."""
    out = PLACEHOLDER.sub(FIGURE, text or "")
    out = _CLOSED_MALFORMED.sub(FIGURE, out)
    out = _CUT_PLACEHOLDER.sub(CUT_OFF, out)
    out = _SINGLE_BRACKET.sub(FIGURE, out)
    out = _SINGLE_CUT.sub(CUT_OFF, out)
    out = _BARE.sub(FIGURE, out)
    return _LEFTOVER.sub("", out)


def _plain(sentence: str) -> str:
    return readable(sentence).strip()


def _sentences(paragraph: str) -> list[str]:
    """Sentences of one paragraph. A piece that follows an abbreviation's full stop, or that starts
    in lower case or with a digit, belongs to the sentence before it: a company name such as "Inc." must not cut a
    sentence in two (the first half would then be judged, and removed, on its own)."""
    out: list[str] = []
    for piece in _SENTENCE_SPLIT.split(" ".join(paragraph.split())):
        piece = piece.strip()
        if not piece:
            continue
        if out and (_ABBREVIATION_END.search(out[-1]) or piece[:1].islower() or piece[:1].isdigit()):
            out[-1] = out[-1] + " " + piece
        else:
            out.append(piece)
    return out


def sentences(paragraph: str) -> list[str]:
    """The sentences of one paragraph, exactly as the audit splits and judges them."""
    return _sentences(paragraph)


def _ledger_dates(ledger) -> list[str]:
    """Every way a date the ledger itself holds may be written out (a balance-sheet date, a fiscal
    year end). Such a date in the text is the ledger's own, not a figure the model made up."""
    dates = set()
    for f in ledger.facts():
        for candidate in (f.period, ledger.period_end(f.period)):
            match = _ISO_DATE.match(candidate or "")
            if match:
                dates.add(tuple(int(part) for part in match.groups()))
    forms: list[str] = []
    for year, month, day in dates:
        name = _MONTHS[month - 1]
        for month_text in {name, name[:3], name[:3] + ".", name[:4] + "."}:
            forms += [f"{month_text} {day}, {year}", f"{day} {month_text} {year}", f"{month_text} {day:02d}, {year}",
                      f"{day:02d} {month_text} {year}"]
        forms.append(f"{year}-{month:02d}-{day:02d}")
    return sorted(forms, key=len, reverse=True)


def _check(sentence: str, ledger) -> bool:
    """True when the sentence may be shown."""
    for key, period in find_placeholders(sentence):
        f = ledger.get(key, period)
        if f is None or f.value is None:
            return False
    rest = PLACEHOLDER.sub(" ", sentence)
    if "[[" in rest or "]]" in rest or _MALFORMED.search(rest):   # a broken or cut-off placeholder
        return False
    for written in _ledger_dates(ledger):
        rest = rest.replace(written, " ")
    if re.search(r"\d", _ALLOWED_DIGITS.sub(" ", rest)):
        return False
    if _SPELLED_FIGURE.search(rest):
        return False
    if _ADVICE.search(rest):
        return False
    return True


def _render(sentence: str, ledger) -> str:
    out, pos = [], 0
    for m in PLACEHOLDER.finditer(sentence):
        out.append(html.escape(sentence[pos:m.start()]))
        out.append(fmt.cited(ledger.get(m.group(1), m.group(2)), ledger))
        pos = m.end()
    out.append(html.escape(sentence[pos:]))
    return "".join(out)


def apply(text: str, ledger) -> tuple[str, list[str]]:
    """(HTML with one `<p>` per paragraph of kept sentences, withheld sentences as plain text
    with `[figure]` in place of each placeholder). The HTML is "" when nothing was kept."""
    paragraphs: list[str] = []
    withheld: list[str] = []
    for para in _PARAGRAPH_SPLIT.split(text or ""):
        kept = []
        for sentence in _sentences(para):
            if _check(sentence, ledger):
                kept.append(_render(sentence, ledger))
            else:
                withheld.append(_plain(sentence))
        if kept:
            paragraphs.append("<p>" + " ".join(kept) + "</p>")
    return "\n".join(paragraphs), withheld
