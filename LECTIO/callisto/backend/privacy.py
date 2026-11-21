"""A user may paste personal or account data into a question. This app never needs it.

`scan(text)` finds it in code (no model), returns what KIND of thing was found (never the value)
and the text with those values taken out, so they never reach the model or a trace. The chat then
opens its answer with `notice(kinds)`: it says plainly that the data was not needed, was not used
and was left out. A review of the chat flagged the earlier behaviour: it took such a message and
simply carried on, without a word about what happens to the data.

Kept narrow on purpose: an ordinary question about figures ("revenue of 391,035 in 2024") must
never be read as personal data."""
from __future__ import annotations

import re

REMOVED = "[removed]"

_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_SSN = re.compile(r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])")
_SECRET = re.compile(
    r"(?i)\b(?:password|passcode|passwd|pin(?:\s+code)?|secret(?:\s+key)?|api[ _-]?key|access[ _-]?token|"
    r"security\s+code|cvv|cvc)\b\s*(?:is|was|:|=)\s*['\"]?[^\s'\",;]{3,}")
_ACCOUNT = re.compile(
    r"(?i)\b(?:(?:bank\s+)?account|routing|iban|sort\s+code|swift)\b(?:\s*(?:number|no\.?|#|code))?\s*(?:is|:|=)?\s*"
    r"(?:[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\s?[A-Z0-9]{1,4}|\d(?:[ -]?\d){6,19})")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# a phone number needs a separator, a country code or brackets: ten bare digits may be a figure
_PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?\d{3}[ .-]\d{4}|\d{3}[ .-]\d{3}[ .-]\d{4}|\+\d{9,14})(?![\w])")
_BIRTH = re.compile(r"(?i)\b(?:date\s+of\s+birth|d\.?o\.?b\.?|born\s+on)\b\s*(?:is|was|:)?\s*"
                    r"(?:\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})")


def _luhn(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if double:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
        double = not double
    return total % 10 == 0


def _cards(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and len(set(digits)) > 1 and _luhn(digits):
            spans.append(m.span())
    return spans


# in this order: the most specific first, so one value is named once
_FINDERS = (
    ("a payment card number", _cards),
    ("a Social Security number", lambda t: [m.span() for m in _SSN.finditer(t)]),
    ("a password or access code", lambda t: [m.span() for m in _SECRET.finditer(t)]),
    ("a bank account number", lambda t: [m.span() for m in _ACCOUNT.finditer(t)]),
    ("an email address", lambda t: [m.span() for m in _EMAIL.finditer(t)]),
    ("a phone number", lambda t: [m.span() for m in _PHONE.finditer(t)]),
    ("a date of birth", lambda t: [m.span() for m in _BIRTH.finditer(t)]),
)


def scan(text: str) -> tuple[list[str], str]:
    """(the kinds of personal or account data found, the text with those values removed).
    Never raises; ([], text) when nothing is found."""
    if not isinstance(text, str) or not text:
        return [], text if isinstance(text, str) else ""
    try:
        taken: list[tuple[int, int]] = []
        kinds: list[str] = []
        for kind, find in _FINDERS:
            for start, end in find(text):
                if any(start < e and s < end for s, e in taken):
                    continue
                taken.append((start, end))
                if kind not in kinds:
                    kinds.append(kind)
        if not taken:
            return [], text
        out, at = [], 0
        for start, end in sorted(taken):
            out.append(text[at:start])
            out.append(REMOVED)
            at = end
        out.append(text[at:])
        return kinds, "".join(out)
    except Exception:
        return [], text


def has_question(cleaned: str) -> bool:
    """Whether anything is left to answer once the removed values are gone."""
    rest = re.sub(r"(?i)\b(?:my|is|the|and|here|it|this|that|please|number|address|email|phone)\b", " ",
                  cleaned.replace(REMOVED, " "))
    return len(re.findall(r"[A-Za-z]{3,}", rest)) >= 2


def notice(kinds: list[str]) -> str:
    """What the chat says first when a message carried personal or account data."""
    listed = kinds[0] if len(kinds) == 1 else ", ".join(kinds[:-1]) + " and " + kinds[-1]
    return (f"Please don't share personal or account details here. Your message included {listed}. "
            "I don't need it, I have not used or stored it, and it was removed before your question went "
            "any further. I only work from public company filings and market data.")
