"""Pick the stock a question is about from its words ("what happened to nvidia yesterday" -> NVDA), so a caller
does not have to send the right ticker. Order: $TICKER, a known company name, an upper-case ticker Massive knows,
a Massive company-name search, then the fallback the caller sent. Ported from the local chat (2026-11-21)."""
from __future__ import annotations

import re

from backend import massive

NAMES = {
    "the stock market": "SPY", "stock market": "SPY", "the market": "SPY", "the markets": "SPY", "dow jones": "DIA",
    "the dow": "DIA", "nasdaq": "QQQ", "aple": "AAPL", "appl": "AAPL", "amazon": "AMZN",
    "nvidea": "NVDA", "invidia": "NVDA", "mircosoft": "MSFT", "microsft": "MSFT", "micro soft": "MSFT", "telsa": "TSLA",
    "amazn": "AMZN", "gogle": "GOOGL", "palentir": "PLTR", "target": "TGT", "s&p 500": "SPY", "s&p": "SPY",
    "apple": "AAPL", "iphone": "AAPL", "nvidia": "NVDA", "tesla": "TSLA", "microsoft": "MSFT", "amazon": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "meta": "META", "facebook": "META", "netflix": "NFLX", "amd": "AMD",
    "intel": "INTC", "broadcom": "AVGO", "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE", "ibm": "IBM",
    "qualcomm": "QCOM", "palantir": "PLTR", "costco": "COST", "walmart": "WMT", "disney": "DIS",
    "nike": "NKE", "starbucks": "SBUX", "mcdonald's": "MCD", "mcdonalds": "MCD", "coca-cola": "KO", "coke": "KO",
    "pepsi": "PEP", "pepsico": "PEP", "jpmorgan": "JPM", "jp morgan": "JPM", "goldman": "GS", "goldman sachs": "GS",
    "bank of america": "BAC", "visa": "V", "mastercard": "MA", "paypal": "PYPL", "berkshire": "BRK.B",
    "exxon": "XOM", "chevron": "CVX", "pfizer": "PFE", "johnson & johnson": "JNJ", "uber": "UBER", "airbnb": "ABNB",
    "spotify": "SPOT", "shopify": "SHOP", "coinbase": "COIN", "robinhood": "HOOD", "gamestop": "GME", "amc": "AMC",
    "boeing": "BA", "ford": "F", "gm": "GM", "general motors": "GM", "rivian": "RIVN", "snowflake": "SNOW",
    "micron": "MU", "tsmc": "TSM", "taiwan semiconductor": "TSM", "home depot": "HD", "verizon": "VZ", "at&t": "T",
    "comcast": "CMCSA", "sofi": "SOFI", "super micro": "SMCI", "supermicro": "SMCI",
}
_KNOWN = set(NAMES.values())
_STOP = {"I", "A", "AI", "EPS", "CEO", "CFO", "US", "USA", "ETF", "IPO", "PE", "P", "E", "SEC", "Q", "FY", "YOY", "OK",
         "IS", "IT", "AM", "AN", "AND", "OR", "THE", "TO", "DO", "BE", "ON", "IN", "OF", "MY", "ME", "NOW", "BUY", "SELL",
         "GDP", "CPI", "FED", "API", "R", "D", "EBITDA", "TTM", "K", "M", "B", "NYSE", "LLC", "INC", "VS", "HOW", "WHAT"}
_NAME_RX = re.compile(r"(?<![\w$])(" + "|".join(re.escape(n) for n in sorted(NAMES, key=len, reverse=True)) + r")(?!\w)", re.I)


def _real_ticker(t: str) -> bool:
    if t in _KNOWN:
        return True
    if not massive.available() or not massive.valid_ticker(t):
        return False
    try:
        massive.ticker_overview(t)   # cached by massive.get
        return True
    except Exception:
        return False


def pick_ticker(question: str, last: str | None = None) -> str:
    m = re.search(r"\$([A-Za-z][A-Za-z.]{0,5})\b", question)
    if m and _real_ticker(m.group(1).upper()):
        return m.group(1).upper()
    m = _NAME_RX.search(question)
    if m:
        return NAMES[m.group(1).lower()]
    for tok in re.findall(r"\b[A-Z]{2,5}\b", question):
        if tok not in _STOP and _real_ticker(tok):
            return tok
    for tok in re.findall(r"\b[a-z]{3,5}\b", question):   # "how is nvda doing"
        if tok.upper() in _KNOWN:
            return tok.upper()
    found = massive_search(question)                      # any listed company, by name, via Massive
    if found:
        return found
    return (last or "AAPL").upper()


# Words that are never a company name, so Massive is not asked about them.
_COMMON = set("""big bigger biggest large small sell sells sold make makes made worth much many money company companies business explain tell show a about above after again all also am an and any are as at be been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers how i if
in into is it its itself just me more most my no nor not now of off on once only or other our out over own same she
should so some such than that the their them then there these they this those through to too under until up very was we
were what when where which while who whom why will with would you your yours tell show give explain compare versus vs
stock stocks share shares price prices company companies doing done going today right now recent recently lately latest
news headline headlines year years month months week weeks day days quarter fiscal annual report filing filings revenue
revenues sales profit profits income earnings margin margins growth grow growing buy sell invest investing investment
worth good bad time idea should market cap value valuation dividend dividends risk risks outlook forecast happen happened
think know like look looking much many high low range performance perform performed trading trade traded close closed
open opened up down fall fell rise rose drop dropped gain gained lost loss losses what's how's it's i'm should've
current currently last next past since ago per eps ceo cfo ai us usa okay ok please thanks hey hi hello""".split())
_SEARCH_CACHE: dict = {}


def _search_one(phrase: str):
    if phrase in _SEARCH_CACHE:
        return _SEARCH_CACHE[phrase]
    hit = None
    try:
        res = massive.get("/v3/reference/tickers",
                          {"search": phrase, "market": "stocks", "active": "true", "limit": 10}).get("results") or []
        cs = [r for r in res if r.get("type") in ("CS", "ADRC")]
        whole = re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])")   # "start" must not match "Upstart"
        starts = [r for r in cs if whole.match((r.get("name") or "").lower())]
        if starts:
            hit = starts[0]["ticker"]
        elif len(cs) == 1 and whole.search((cs[0].get("name") or "").lower()):
            hit = cs[0]["ticker"]
    except Exception:
        hit = None
    _SEARCH_CACHE[phrase] = hit
    return hit


def _load_words() -> frozenset:
    """Ordinary English words (the system word list, lower-case entries only). Empty when the file is missing."""
    try:
        with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as fh:
            return frozenset(w.strip() for w in fh if w.strip().islower())
    except OSError:
        return frozenset()


_WORDS = _load_words()


def _ordinary(phrase: str, question: str) -> bool:
    """True when the phrase is made of everyday words and the question does not write it as a name (a capital
    letter that is not at the start of a sentence). "is my data stored" must not become a company called Data."""
    parts = phrase.split()
    if _WORDS:
        if not all(w in _WORDS or (w.endswith("s") and w[:-1] in _WORDS) or (w.endswith("es") and w[:-2] in _WORDS)
                   or (w.endswith("d") and w[:-1] in _WORDS) or (w.endswith("ed") and w[:-2] in _WORDS)
                   or (w.endswith("ing") and w[:-3] in _WORDS) for w in parts):
            return False
    as_name = r"\s+".join(re.escape(w.capitalize()) for w in parts)
    return not re.search(rf"(?<=[a-z,;:] ){as_name}\b", question)


def massive_search(question: str):
    if not massive.available():
        return None
    words = re.findall(r"[a-z][a-z&'.\-]*", question.lower())
    runs, cur = [], []
    for w in words + [""]:
        w = w.strip(".'")
        if w and w not in _COMMON and len(w) >= 3:
            cur.append(w)
        else:
            if cur:
                runs.append(cur)
            cur = []
    phrases = []
    for run in runs:                      # longest phrases first: "eli lilly" before "lilly"
        for n in range(min(3, len(run)), 0, -1):
            for i in range(len(run) - n + 1):
                phrases.append(" ".join(run[i:i + n]))
    for p in [x for x in phrases if not _ordinary(x, question)][:6]:
        hit = _search_one(p)
        if hit:
            return hit
    return None
