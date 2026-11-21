"""Company names for display. The SEC lists many registrants in capitals ("MICROSOFT CORP",
"AMAZON COM INC", "G III APPAREL GROUP LTD /DE/"); a page reads better with ordinary case. Only
an all-capitals name is changed: a name that already has lower-case letters is the company's own
spelling and is left alone."""
from __future__ import annotations

import re

_SUFFIX = {"INC": "Inc.", "CORP": "Corp.", "CO": "Co.", "LTD": "Ltd.", "LLC": "LLC", "PLC": "plc",
           "LP": "LP", "NV": "N.V.", "SA": "S.A.", "AG": "AG", "SE": "SE", "USA": "USA", "US": "US"}
_SMALL = {"OF", "AND", "THE", "FOR", "DE", "LA"}
_STATE = re.compile(r"\s*/\s*[A-Z]{2,3}\s*/?\s*$")     # "/DE/", "/ DE", "/NEW/": the SEC's state or status tag
_KEEP_UPPER = re.compile(r"^(?:[A-Z]{1,3}&[A-Z]{1,3}|[A-Z]{1,3}\d+|[IVX]{2,4})$")   # AT&T, codes, roman numerals
# spellings a plain capital-first rule gets wrong
_SPECIAL = {"ASML": "ASML", "JPMORGAN": "JPMorgan", "NVIDIA": "NVIDIA", "PEPSICO": "PepsiCo", "ABBVIE": "AbbVie",
            "PAYPAL": "PayPal", "MCDONALDS": "McDonald's", "EBAY": "eBay", "CONOCOPHILLIPS": "ConocoPhillips",
            "UNITEDHEALTH": "UnitedHealth", "MASTERCARD": "Mastercard", "LULULEMON": "lululemon"}


def _shouting(name: str) -> bool:
    """Written in capitals: all of it, or nearly all with a mixed-case suffix ("ELI LILLY & Co")."""
    letters = [c for c in name if c.isalpha()]
    if not letters:
        return False
    if name == name.upper():
        return True
    share = sum(c.isupper() for c in letters) / len(letters)
    return share >= 0.75 and any(len(w) >= 4 and w.isupper() for w in re.findall(r"[A-Za-z]+", name))


def display_name(raw: str | None) -> str:
    """`MICROSOFT CORP` -> `Microsoft Corp.`; `AMAZON COM INC` -> `Amazon.com Inc.`; a name with
    lower-case letters is returned as it is (apart from the SEC's trailing state tag)."""
    name = _STATE.sub("", str(raw or "").strip())
    if not name or not _shouting(name):
        return name
    words = name.upper().replace(",", " ").split()
    out: list[str] = []
    for i, word in enumerate(words):
        bare = word.strip(".")
        if bare in _SUFFIX and i > 0:
            out.append(_SUFFIX[bare])
        elif bare == "COM" and out:
            out[-1] = out[-1] + ".com"
        elif bare in _SMALL and i > 0:
            out.append(bare.lower())
        elif bare in _SPECIAL:
            out.append(_SPECIAL[bare])
        elif _KEEP_UPPER.match(bare) or (len(bare) <= 3 and not re.search(r"[AEIOUY]", bare)):
            out.append(bare)                      # an initialism with no vowel: IBM, CVS, HP
        else:
            out.append("-".join(part.capitalize() for part in bare.split("-")))
    return " ".join(out).replace("Coca Cola", "Coca-Cola")
