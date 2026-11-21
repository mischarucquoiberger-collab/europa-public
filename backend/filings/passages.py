"""The items of an annual filing and the risk-factor passages inside Item 1A.

    items = split_items(text)            # {"1": ..., "1A": ..., "7": ..., "7A": ..., "8": ...}
    found = risk_passages(text)          # [Passage(id="P1", item="1A", heading=..., text=..., start, end)]
    hits  = search(found, "tariffs on components")
    span  = find_span(found[0].text, quote)

`text` is the plain text `backend.sources.sec.filing_text` returns: paragraphs separated by blank
lines. The source's bold or italic risk captions do not survive as markup, so a risk heading is
recognised by its shape (a short standalone line followed by a longer paragraph). Every passage
is a contiguous slice of the filing text, `text[p.start:p.end] == p.text`, so any span found
inside a passage is the filing's own characters.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from backend.verify import audit

PASSAGE_CHAR_CAP = 1_500
HEAD_LINE_MAX = 160            # an item heading is a short line; a cross-reference is mid-paragraph
TITLE_LINE_MAX = 120
RISK_HEADING_MAX = 400
RISK_HEADING_MIN = 8
SUBHEADING_MAX = 100           # a heading with no full stop ("Business model competition") is short
NO_CHANGE_STUB_MAX = 1_500     # a 10-Q's "no material changes" Item 1A is a short stub

TEN_K_ITEMS = ("1", "1A", "7", "7A", "8")
# Form 20-F: item number -> the 10-K item it plays (Item 3.D is "1A", handled apart)
TWENTY_F_ITEMS = {"4": "1", "5": "7", "11": "7A", "18": "8", "17": "8"}


@dataclass(frozen=True)
class Passage:
    id: str            # "P1", "P2", ... in filing order
    item: str          # "1A", "7", ...
    heading: str       # the filing's own caption
    text: str          # heading + its paragraphs, a slice of the filing text
    start: int         # character offsets into the filing text
    end: int


# --- items --------------------------------------------------------------------------------

_DASHES = "‐‑‒–—―"
_ITEM_HEAD = re.compile(
    r"^[ \t\xa0]*item[ \t\xa0]*(\d{1,2})([A-Da-d])?(?![A-Za-z0-9])"
    r"[ \t\xa0]*[.:\-" + _DASHES + r"]*[ \t\xa0]*(.*?)[ \t\xa0]*$",
    re.IGNORECASE | re.MULTILINE)
_NEXT_LINE = re.compile(r"\s*([^\n]*)")
_LEADER_AND_PAGE = re.compile(r"[\s.…_]*\d{0,4}\s*$")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_RISK_FACTORS_LINE = re.compile(
    r"^[ \t\xa0]*(?:D[ \t]*[.:)\-" + _DASHES + r"][ \t\xa0]*)?Risk[ \t\xa0]+Factors[ \t\xa0.]*$",
    re.IGNORECASE | re.MULTILINE)


def _title_like(line: str) -> bool:
    """A caption such as "Risk Factors", "RISKS RELATED TO OUR BUSINESS": short, no sentence end,
    most longer words capitalised."""
    line = line.strip()
    if not line or len(line) > TITLE_LINE_MAX or line.endswith((".", ":", ";", ",")):
        return False
    words = _WORD.findall(line)
    if not words or len(words) > 15:
        return False
    longer = [w for w in words if len(w) > 3] or words
    return sum(1 for w in longer if w[0].isupper()) >= 0.6 * len(longer)


def _headings(text: str) -> list[tuple[int, int, str, str]]:
    """(line start, body start, key, title) for every line that reads as an item heading.
    The title is on the heading line or, when that line holds only "Item 1A.", the next line."""
    found = []
    for m in _ITEM_HEAD.finditer(text):
        if len(m.group(0).strip()) > HEAD_LINE_MAX:
            continue
        key = str(int(m.group(1))) + (m.group(2) or "").upper()
        title = _LEADER_AND_PAGE.sub("", m.group(3) or "").strip()
        body_start = m.end()
        if not title:
            nxt = _NEXT_LINE.match(text, m.end())
            line = (nxt.group(1) or "").strip() if nxt else ""
            if line and _title_like(line) and not _ITEM_HEAD.match(line):
                title = _LEADER_AND_PAGE.sub("", line).strip()
                body_start = nxt.end()
        found.append((m.start(), body_start, key, title))
    return found


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


_PART_LINE = re.compile(
    r"^[ \t\xa0]*part[ \t\xa0]+[ivx]+(?:[ \t\xa0]*(?:,|and|&)[ \t\xa0]*[ivx]+)*[ \t\xa0.]*$", re.IGNORECASE)
_PAGE_FURNITURE = re.compile(
    r"^(?:table\s+of\s+contents|index|page\s+\d{1,3}|[-–—\s]*\d{1,3}[-–—\s]*|[ivx]{1,4})$",
    re.IGNORECASE)


_RUNNING_FOOTER = re.compile(r"^(?:\d{1,3}\s+(?P<a>[^\d\n]{2,60})|(?P<b>[^\d\n]{2,60})\s+\d{1,3})$")
_LONE_BULLET = re.compile(r"^[•·▪◦●○■□‣⁃*\-–—]$")


def is_furniture(line: str) -> bool:
    """A page header or footer that the text extraction left between paragraphs: "Table of
    Contents", a page number, "PART I", a running item header such as "Item 1A" (many filers
    repeat the item at the top of every page), a running footer such as "Bank of America 8", or
    a bullet sign alone on its line."""
    line = (line or "").strip()
    if not line:
        return True
    if _PAGE_FURNITURE.match(line) or _PART_LINE.match(line) or _LONE_BULLET.match(line):
        return True
    footer = _RUNNING_FOOTER.match(line)
    if footer and _title_like(footer.group("a") or footer.group("b") or ""):
        return True
    return len(line) <= HEAD_LINE_MAX and bool(_ITEM_HEAD.match(line))


def _only_furniture(text: str) -> bool:
    return all(is_furniture(line) for line in text.split("\n"))


def _trim_furniture_tail(text: str, start: int, end: int) -> int:
    """`end` moved back over trailing page furniture (a "PART II" line before the next item)."""
    while end > start:
        cut = text.rfind("\n", start, end)
        line = text[cut + 1 if cut >= 0 else start:end]
        if not line.strip() or not is_furniture(line):
            break
        end = cut if cut >= start else start
    return _strip_span(text, start, end)[1]


def _spans(text: str) -> dict[str, tuple[int, int]]:
    """Body span (after the heading line) of each wanted item.

    Headings of the same item that follow one another make ONE span: a running page header
    ("PART I / Item 1A" on every page) does not cut the item into pages. Of the spans that head
    the same item (the table of contents lists every item too), the longest wins; on a tie the
    later one."""
    text = text or ""
    heads = _headings(text)
    best: dict[str, tuple[int, int, str]] = {}
    i = 0
    while i < len(heads):
        _line, body_start, key, title = heads[i]
        titles = [title]
        j = i
        while j + 1 < len(heads) and heads[j + 1][2] == key:
            nxt_line, nxt_body, _, nxt_title = heads[j + 1]
            if _only_furniture(text[body_start:nxt_line]):
                body_start = max(body_start, nxt_body)  # "Item 1A" header, then "ITEM 1A. RISK FACTORS"
            titles.append(nxt_title)
            j += 1
        end = heads[j + 1][0] if j + 1 < len(heads) else len(text)
        start, end = _strip_span(text, min(body_start, end), end)
        end = _trim_furniture_tail(text, start, end)
        old = best.get(key)
        if old is None or (end - start) >= (old[1] - old[0]):
            best[key] = (start, end, " | ".join(t for t in titles if t))
        i = j + 1

    def titled(key: str, pattern: str) -> bool:
        return bool(key in best and re.search(pattern, best[key][2], re.IGNORECASE))

    twenty_f = titled("3", r"key\s+information") or titled("5", r"operating\s+and\s+financial\s+review")
    out: dict[str, tuple[int, int]] = {}
    if not twenty_f:
        for key in TEN_K_ITEMS:
            if key in best and best[key][1] > best[key][0]:
                out[key] = best[key][:2]
        return out
    if "3" in best:
        start, end, _ = best["3"]
        m = _RISK_FACTORS_LINE.search(text, start, end)
        if m:
            start, end = _strip_span(text, m.end(), end)
        if end > start:
            out["1A"] = (start, end)
    for key, plays in TWENTY_F_ITEMS.items():
        if key in best and plays not in out and best[key][1] > best[key][0]:
            out[plays] = best[key][:2]
    return {k: out[k] for k in TEN_K_ITEMS if k in out}


def split_items(text: str) -> dict[str, str]:
    """The body text of Items 1, 1A, 7, 7A and 8 of a 10-K (for a 20-F: Item 4 as "1", Item 3.D
    Risk Factors as "1A", Item 5 as "7", Item 11 as "7A", Item 18 as "8"). A missing item is
    absent from the result."""
    return {key: text[s:e] for key, (s, e) in _spans(text).items()}


# --- risk passages ------------------------------------------------------------------------

_LINE = re.compile(r"[^\n]+")
_BULLET = re.compile(r"^(?:[•·▪◦●○■□‣⁃*>\-–—]|o\s|\(?[a-z0-9]{1,3}\)\s)")
_SENTENCE_BREAK = re.compile(r"[.!?][\"”’)]*\s+(?=[\"“‘(]?[A-Z])")
_NOT_A_RISK = re.compile(
    r"^(?:summary\b.*|.*\brisk\s+factors?\s+summary\b.*|(?:item\s+1a\.?\s*)?risk\s+factors\.?)$",
    re.IGNORECASE)
_NO_CHANGE = re.compile(r"\bno\s+material\s+changes?\b", re.IGNORECASE)
# a sentence that leans on what came before it: not a heading, and no quote on its own
_REFERS_BACK = re.compile(
    r"^(?:this|these|those|such|it|its|they|their|them|that|for\s+example|for\s+instance|"
    r"as\s+a\s+result|in\s+addition|additionally|also|accordingly|consequently|similarly|"
    r"furthermore|moreover|further|thus|therefore|hence|in\s+particular|likewise|otherwise|"
    r"for\s+all\s+of\s+these\s+reasons|for\s+these\s+reasons|in\s+that\s+case|if\s+so|"
    r"see|for\s+more|for\s+a\s+(?:further\s+|more\s+detailed\s+)?discussion|refer\s+to|"
    r"more\s+(?:broadly|generally|specifically)|any\s+such|"
    r"(?:any|all|each|both|none|some|many|most|one|either|neither)\s+(?:of\s+)?(?:these|those|such|the\s+foregoing))\b"
    r"|\b(?:above|foregoing|aforementioned|(?:described|set\s+forth|discussed|listed|outlined)\s+below)\b",
    re.IGNORECASE)
# the words a risk statement is made of
_RISK_WORDING = re.compile(
    r"\b(?:could|may|might|cannot|adverse\w*|harm\w*|risk\w*|fail\w*|unable|inability|"
    r"depend\w*|subject\s+to|affect\w*|loss(?:es)?|lose|losing|declin\w*|disrupt\w*|"
    r"uncertain\w*|volatil\w*|expos\w*|impair\w*|limit\w*|reduc\w*|challeng\w*|compet\w*|"
    r"liabilit\w*|litigation|threat\w*|breach\w*|damag\w*|penalt\w*|negative\w*)\b",
    re.IGNORECASE)


def refers_back(sentence: str) -> bool:
    """True when the sentence opens with a back reference ("These initiatives ...", "For
    example, ...", "As a result, ...") or points elsewhere ("described above"), so it does not
    stand on its own."""
    return bool(_REFERS_BACK.search((sentence or "").lstrip("\"'“‘(").strip()[:200]))


def _units(text: str, start: int, end: int) -> tuple[list[tuple[int, int]], set[int]]:
    """(start, end) of each non-empty line in the span, page furniture left out, and the indices
    of the lines that are bullet items (their bullet sign alone on the line before)."""
    out: list[tuple[int, int]] = []
    bulleted: set[int] = set()
    after_bullet = False
    for m in _LINE.finditer(text, start, end):
        s, e = _strip_span(text, m.start(), m.end())
        if e <= s:
            continue
        line = text[s:e]
        if _LONE_BULLET.match(line):
            after_bullet = True
            continue
        if is_furniture(line):
            continue
        if after_bullet:
            bulleted.add(len(out))
        after_bullet = False
        out.append((s, e))
    return out, bulleted


_NOT_A_HEADING_START = re.compile(
    r"(?:however|while|although|though|during|when|whereas|because|since)\b", re.IGNORECASE)
_DEMONSTRATIVE = re.compile(r"\bthese\b", re.IGNORECASE)
_ENDS_SENTENCE = re.compile(r"[.!?][\"”’)]*$")
_ENDS_CLAUSE = re.compile(r"[.!?:;][\"”’)]*$")


def _all_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and sum(1 for c in letters if c.isupper()) >= 0.8 * len(letters)


def _heading_shaped(line: str) -> bool:
    if not (RISK_HEADING_MIN <= len(line) <= RISK_HEADING_MAX):
        return False
    if _BULLET.match(line) or line.endswith((":", ";", ",")) or re.search(r"\s(?:and|or)$", line):
        return False
    first = line[:1]
    if not (first.isupper() or first.isdigit()) or _ITEM_HEAD.match(line):
        return False                       # a quotation mark first: a definition, not a heading
    if refers_back(line) or _NOT_A_HEADING_START.match(line) or _DEMONSTRATIVE.search(line[:80]):
        return False
    if not _ENDS_SENTENCE.search(line) and (len(line) > SUBHEADING_MAX or _SENTENCE_BREAK.search(line)):
        return False                       # a long line with no full stop: a sentence cut by a page break
    return len(_SENTENCE_BREAK.findall(line)) <= 2


def _states_risk(line: str) -> bool:
    """One sentence, ending with a full stop, in the words of a risk statement."""
    return (line.rstrip("\"”’)").endswith(".") and not _SENTENCE_BREAK.search(line)
            and bool(_RISK_WORDING.search(line)))


def _inline_heading(line: str) -> str:
    """The first sentence of a paragraph that opens a risk factor in-line (the bold caption and
    its text in one paragraph), when it reads as a heading; "" otherwise."""
    m = _SENTENCE_BREAK.search(line)
    if not m:
        return ""
    head = line[:m.end()].rstrip()
    return head if _heading_shaped(head) and _states_risk(head) else ""


_SENTENCE_STOP = re.compile(r"[.!?][\"”’)]*(?=\s+[\"“‘(]?[A-Z0-9]|\s*$)")


def _trim_end(text: str, start: int, end: int) -> int:
    """`end`, or for a passage over PASSAGE_CHAR_CAP the end of its last whole sentence inside
    the cap (a full stop after "Inc." or "U.S." is not a sentence end), else the last space."""
    if end - start > PASSAGE_CHAR_CAP:
        limit = start + PASSAGE_CHAR_CAP
        cut = None
        for m in _SENTENCE_STOP.finditer(text, start, min(limit + 1, len(text))):
            if m.end() > limit:
                break
            if not audit._ABBREVIATION_END.search(text[start:m.start() + 1]):
                cut = m.end()
        if cut is not None and cut - start >= PASSAGE_CHAR_CAP // 3:
            end = cut
        else:
            window = text[start:limit]
            space = max(window.rfind(" "), window.rfind("\n"))
            end = start + (space if space > 0 else PASSAGE_CHAR_CAP)
    return _strip_span(text, start, end)[1]


def _kinds(lines: list[str], bulleted: set[int] = frozenset()) -> list[str]:
    """"heading", "caption" or "body" for each line.

    - A caption ("Risks Related to ...", "STRATEGIC AND COMPETITIVE RISKS", "Market") is a short
      title-cased line: always when in capitals, else when a heading-shaped line follows it.
    - A heading is a heading-shaped line that does not follow another heading and is followed by
      a longer paragraph, or that is one risk-worded sentence (its first paragraph may be shorter).
    - Everything else is body."""
    n = len(lines)
    shaped = [i not in bulleted and _heading_shaped(line) for i, line in enumerate(lines)]
    titled = [i not in bulleted and _title_like(line) for i, line in enumerate(lines)]
    caption = [titled[i] and (_all_caps(line) or i + 1 >= n or shaped[i + 1] or titled[i + 1])
               for i, line in enumerate(lines)]
    kinds = ["body"] * n
    for i, line in enumerate(lines):
        has_next = i + 1 < n
        if i and kinds[i - 1] == "body" and not _ENDS_CLAUSE.search(lines[i - 1]):
            continue                       # the rest of a paragraph cut by a page break
        if caption[i]:
            kinds[i] = "caption"
        elif (shaped[i] and has_next and not caption[i + 1] and not (i and kinds[i - 1] == "heading")
              and (len(lines[i + 1]) > len(line) or _states_risk(line))):
            kinds[i] = "heading"           # (a heading needs a paragraph under it, not a caption)
    return kinds


def risk_passages(text: str, max_passages: int = 40) -> list[Passage]:
    """Item 1A split at its risk headings: each passage is a heading and the paragraphs under it,
    trimmed to PASSAGE_CHAR_CAP characters. The preamble before the first heading, a summary
    block and the group captions ("Risks Related to ...") are not passages. A paragraph right
    after a caption that opens with its own risk sentence (an in-line caption) is a passage
    headed by that sentence. A short "no material changes" Item 1A (the 10-Q stub) gives []."""
    text = text or ""
    span = _spans(text).get("1A")
    if not span or max_passages <= 0:
        return []
    start, end = span
    if end - start < NO_CHANGE_STUB_MAX and _NO_CHANGE.search(text[start:end]):
        return []
    units, bulleted = _units(text, start, end)
    lines = [text[s:e] for s, e in units]
    kinds = _kinds(lines, bulleted)

    found: list[tuple[int, int, str]] = []
    current: list | None = None
    mode = "preamble"                    # preamble | open | after-caption | skip

    def close() -> None:
        if current and current[1] > current[3]:          # a heading with a body under it
            found.append((current[0], current[1], current[2]))

    for i, (s, e) in enumerate(units):
        line = lines[i]
        if kinds[i] in ("heading", "caption"):
            close()
            current = None
            if _NOT_A_RISK.match(line):
                mode = "skip"                             # a summary list: nothing until a heading
            elif kinds[i] == "heading":
                current, mode = [s, e, line, e], "open"
            else:
                mode = "after-caption"
            continue
        if current is not None:
            current[1] = e
        elif mode == "after-caption":
            head = _inline_heading(line)
            if head:
                current, mode = [s, e, head, s + len(head)], "open"
    close()
    if not found and units:                               # no headings: the section is one passage
        found = [(units[0][0], units[-1][1], "")]
    out = []
    for n_, (s, e, head) in enumerate(found[:max_passages], 1):
        e = _trim_end(text, s, e)
        out.append(Passage(id=f"P{n_}", item="1A", heading=head, text=text[s:e], start=s, end=e))
    return out


# --- search -------------------------------------------------------------------------------

_STOP = frozenset((
    "a an and are as at be been but by can could do does for from had has have if in into is it "
    "its may might more most not of on or other our such than that the their them there these they "
    "this those to was we were what which while will with would you your us any all also"
).split())
_TERM = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> list[str]:
    out = []
    for word in _TERM.findall((text or "").lower()):
        if len(word) < 2 or word in _STOP:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]                                # tariffs ~ tariff
        out.append(word)
    return out


def search(passages: list[Passage], query: str, k: int = 5) -> list[Passage]:
    """The passages that best match the query's keywords: most distinct query terms first, then
    term frequency (a heading word counts twice), then filing order."""
    wanted = list(dict.fromkeys(_terms(query)))
    if not wanted or k <= 0:
        return []
    scored = []
    for pos, p in enumerate(passages or []):
        body, head = Counter(_terms(p.text)), Counter(_terms(p.heading))
        distinct = sum(1 for t in wanted if body[t] or head[t])
        if not distinct:
            continue
        freq = sum(body[t] + head[t] for t in wanted)
        scored.append((-distinct, -freq, pos, p))
    scored.sort(key=lambda row: row[:3])
    return [row[3] for row in scored[:k]]


# --- exact spans --------------------------------------------------------------------------

_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    "­": "",
}


def _normalise(text: str) -> tuple[str, list[int]]:
    """Text with whitespace runs collapsed to one space, typographic quotes and dashes folded and
    NFKC applied, plus the original index of every character kept."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
                index.append(i)
            continue
        folded = _FOLD.get(ch)
        if folded is None:
            folded = unicodedata.normalize("NFKC", ch) if ord(ch) > 127 else ch
        for c in folded:
            if c.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    index.append(i)
                continue
            chars.append(c)
            index.append(i)
    if chars and chars[-1] == " ":
        chars.pop()
        index.pop()
    return "".join(chars), index


def find_span(passage_text: str, quote: str) -> tuple[int, int] | None:
    """The exact (start, end) of `quote` in `passage_text`, comparing after whitespace, curly
    quotes and dashes are normalised on both sides; None when the quote is not literally there.
    `passage_text[start:end]` is the filing's own characters."""
    if not passage_text or not quote:
        return None
    hay, index = _normalise(passage_text)
    needle, _ = _normalise(quote)
    if not needle:
        return None
    at = hay.find(needle)
    if at < 0:
        return None
    return index[at], index[at + len(needle) - 1] + 1
