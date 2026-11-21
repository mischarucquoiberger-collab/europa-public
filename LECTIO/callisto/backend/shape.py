"""Display layout for answers: inserts line breaks and bullet marks only. Never changes a word."""
import re

NOTE_RX = re.compile(
    r"^(Market data: |Filing figures \(|For .{1,60}, ask about the share price|Recent headlines are listed|"
    r"Recent headlines are listed|The annual figures were confirmed|The second source|Two sources disagreed|"
    r"The council models|(?:Europa|Callisto)'s headlines follow|Here are recent headlines|(?:Europa|Callisto) has not verified them)")
WAY_RX = re.compile(
    r"^(How to judge the price:|How to gauge risk:|Things to weigh before deciding:|Things to weigh|To weigh:|"
    r"Analyst ratings and price targets are not|Price data shows how much|For a long-term view|"
    r"If you already own the shares|(?:Europa|Callisto)'s data does not include the earnings calendar|"
    r"A bear case and a bull case are two readings|For .{1,60}'s sales, profit and risks)")
KEY_RX = re.compile(r"^(What it means:|Deeper read:|Bear case:|Bull case:|Pros:|Cons:)")

_SPLIT_RX = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(“‘])")
_ABBR = {"inc", "corp", "co", "ltd", "vs", "etc", "no", "mr", "mrs", "ms", "dr", "st", "jr", "sr", "e.g", "i.e",
         "approx", "u.s", "u.k", "est", "fig", "mt", "vol", "ave", "p.m", "a.m", "cos", "plc", "llc", "bros"}


def _ends_abbrev(s: str) -> bool:
    last = s.split()[-1] if s.split() else ""
    if not last.endswith("."):
        return False
    w = last[:-1].lstrip("($\"'“").lower()
    return w in _ABBR or bool(re.fullmatch(r"[a-z]", w)) or bool(re.fullmatch(r"(?:[a-z]\.)+[a-z]", w))


def _unbalanced(s: str) -> bool:
    return s.count('"') % 2 == 1 or s.count("“") > s.count("”")


def _sentences(text: str) -> list:
    out = []
    for piece in _SPLIT_RX.split(text.strip()):
        if out and (_ends_abbrev(out[-1]) or _unbalanced(out[-1])):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return [s.strip() for s in out if s.strip()]


def layout(answer):
    try:
        if not isinstance(answer, str) or "\n" in answer or not answer.strip():
            return answer if isinstance(answer, str) else ""
        body, labels, ways, notes = [], [], [], []  # items: body/label tagged in order
        order = []  # ("body"|"label", text)
        mode = "body"
        for s in _sentences(answer):
            if NOTE_RX.match(s):
                mode = "note"; notes.append(s); continue
            if WAY_RX.match(s):
                mode = "way"; ways.append(s); continue
            is_label = bool(KEY_RX.match(s))
            if mode == "way" and not is_label:
                ways.append(s); continue
            if mode == "note" and not is_label:
                notes.append(s); continue
            mode = "body"
            order.append(("label" if is_label else "body", s))
        n_body = sum(1 for k, _ in order if k == "body")
        has_label = any(k == "label" for k, _ in order)
        lines = []
        if n_body < 3 and not has_label:
            if order:
                lines.append(" ".join(t for _, t in order))
        else:
            first = True
            prev_kind = None
            for kind, t in order:
                if kind == "label":
                    lines.append(t)
                elif prev_kind == "label":
                    lines[-1] += " " + t
                elif first or (t.startswith(("So ", "So, ")) and not re.search(r"\d", t)):
                    lines.append(t)   # the lead, or a closing "So ..." line: its own line, no bullet
                else:
                    lines.append("\u2022 " + t)
                if kind == "body" and prev_kind != "label":
                    first = False
                prev_kind = kind
        if ways:
            lines.append(" ".join(ways))
        if notes:
            lines.append(" ".join(notes))
        return "\n".join(lines)
    except Exception:
        return answer


def plain(text):
    try:
        if not text:
            return ""
        return " ".join(str(text).replace("\u2022 ", "").split())
    except Exception:
        return text or ""
