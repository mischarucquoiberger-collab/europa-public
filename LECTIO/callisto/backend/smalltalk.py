"""Fixed chat replies for greetings, 'what are you', trust, off-topic and the like.

Pure code: no model, no data, no digits in any reply. Patterns are tight on purpose so real stock
questions still reach the desk. reply(q) -> (kind, text) or None. PREDICT_LEAD is put in front of a
normal checked market answer by the caller."""
from __future__ import annotations

import re

EXAMPLES = ('Try: "What happened to Nvidia yesterday?", "Bear case for Tesla", '
            '"Does Apple pay a dividend?" or "Show me a chart of Microsoft this year".')
PREDICT_LEAD = "Nobody can reliably predict a stock's price, and Callisto doesn't try. Here is what is known now: "
_TAIL = r"( there| europa| callisto| guys| all| team| everyone)?\W*$"

_RULES = [
    ("injection", r"\b(ignore|disregard|forget) (all |your |the |any )?(previous|prior|above|earlier)?\s*(instructions|rules|prompt)\b|"
                  r"\b(system|hidden|secret) prompt\b|\b(print|show|reveal|repeat) (me )?your (prompt|instructions|rules)\b|\bjailbreak\b",
     "I keep my setup private. I can explain a company's results, price moves and risks in plain English. "
     "What would you like to know?"),
    ("greeting", r"^\W*(hi+|hello+|hey+|yo|sup|hiya|howdy|good (morning|afternoon|evening)|what'?s up|how are you( doing)?|how'?s it going)" + _TAIL,
     "Hi, I'm Callisto, Europa's research agent. Ask me about any stock and I'll give you the latest numbers, "
     "what they mean, and what to weigh, with every number checked before you see it. " + EXAMPLES),
    ("advice_q", r"\bis (this|that|it) (financial|investment|investing) advice\b|\bare you (a |my )?(financial|investment) advis[eo]r\b",
     "No. Callisto explains data and doesn't give personal advice; the buy or sell decision stays with you. "
     "For a decision about your own money, talk to a licensed adviser."),
    ("trust", r"\bhow (do|does|did) (you|it|this|callisto|europa) (check|verify|confirm|know)\b|\bcan i trust (you|this|these|those|the|your|it|callisto|europa)( numbers?| data| answers?| figures?| info\w*)?\W*$|"
              r"\b(are|is) (these|the|your|this) (numbers?|data|figures?|answers?) (accurate|correct|real|right|reliable|true)\b|"
              r"\bwhere (does|do|did) (your|the|this|you) (data|numbers?|info\w*|figures?)( come| get)?\b|"
              r"\bwhat (are|is) your (sources?|data sources?)\b|^\W*sources?\W*$|\bdo you (make|made) (things|stuff|numbers) up\b|\bhallucinat",
     "Every number is compared with its source before you see it. Company figures come from Apple's annual report, "
     "the form the company files with the SEC each year; prices and returns come from Massive end-of-day market data. "
     "If a sentence has a number that can't be matched to the source, it is removed. "
     "Headlines are shown as published and are not checked."),
    ("about", r"\b(who|what) (are|r) (you|u)\b|\bwhat (is|'s) (this|europa|callisto)\b|\bwhat (do|can) you do\b|"
              r"\bhow (does|do) (this|you|it) work\b|^\W*help( me)?\W*$|\bhow (do|can) i use\b|\bintroduce yourself\b|"
              r"\bare you (an? )?(ai|bot|robot|human|real person|chatgpt|gpt|claude)\b|\bwho (built|made|created) (you|this)\b",
     "I'm Callisto, Europa's AI research agent for everyday investors. I explain Apple's annual report and daily "
     "market data for listed companies in plain English: what happened, what it means, and what to weigh. "
     "A separate checker confirms every number against its source before you see it. "
     "I'm not a person and not a financial adviser, so I don't tell you to buy or sell. " + EXAMPLES),
    ("why_apple", r"\bwhy (do|did|does|are|is) (you|it|this|europa|callisto) (always |only |just |keep )?"
                  r"(go|default|start|pick|show|use|jump|talk|answer|assum|switch)\w*\b.*\b(apple|aapl)\b|\bwhy (always|only|just) apple\b",
     "Apple is the company whose full annual report is loaded and checked here, so I use it when a "
     "question doesn't name a stock. Name any company or ticker, like Nvidia or TSLA, and I'll switch to it."),
    ("picks", r"\b(best|top|hot|which|what) (stocks?|shares?|compan(y|ies)|etfs?|funds?) (to|should i|can i|do i) (buy|invest|own|get)\b|"
              r"\bwhat (stocks?|should i) (should i )?(buy|invest in)\W*$|\bstocks? that will (double|triple|moon|explode|go up)\b|"
              r"\b(what|which) stocks? (are|is) (going|about to go) up\b|\bnext (nvidia|apple|tesla|amazon|big thing)\b|\bstock (tips?|picks?)\b",
     "Callisto doesn't pick stocks or predict winners. Name a company or ticker and I'll show how it has moved, "
     "what its numbers say and what to weigh."),
    ("crypto", r"\b(bitcoin|btc|ethereum|ether|eth|crypto\w*|dogecoin|doge|solana|xrp|ripple|altcoins?|stablecoins?)\b",
     "Callisto covers stocks and funds, not coins directly. A coin like Bitcoin isn't a stock; funds that hold it "
     "trade under their own tickers, such as IBIT. Type a fund ticker and I'll show its price moves."),
    ("thanks", r"^\W*(thanks|thank you|thx|ty|ok|okay|cool|nice|great|got it|awesome|perfect)( you| so much| a lot| europa| callisto)?\W*$",
     "Anytime. Ask about another stock, or ask for a chart."),
    ("bye", r"^\W*(bye|goodbye|see you|cya)\b.{0,20}$", "Bye! Come back any time you want a stock explained."),
    ("rude", r"\b(you('re| are)? (suck|stupid|dumb|useless|trash|garbage|terrible|bad)|this (sucks|is (stupid|dumb|useless|trash|garbage))|"
             r"f+u+c+k|shit|wtf|stfu)\b",
     "Sorry that wasn't helpful. Tell me what you were looking for and I'll try again."),
    ("offtopic", r"\b(weather|forecast for (today|tomorrow)|poem|joke|recipe|song|lyrics|homework|essay|"
                 r"who won|super bowl|world cup|nba|nfl|movie|girlfriend|boyfriend|meaning of life|translate|pizza|"
                 r"restaurants?|where (?:to|can i|should i) eat|vacation|horoscope)\b|"
                 r"^\W*what(?:'s| is) \d+ ?[-+x*/] ?\d+\W*$",
     "That's outside what I cover. I help with stocks: price moves, company reports and plain-English explanations."),
]
_RULES = [(k, re.compile(rx, re.I), text) for k, rx, text in _RULES]
_FINANCE = re.compile(r"\b(stock|share|price|revenue|sales|profit|earnings|dividend|market|10-?k|filing|ticker|invest|"
                      r"buy|sell|chart|graph|eps|margin|cash|debt|risk|valu|bear|bull)\w*", re.I)
_PREDICT = re.compile(r"\b(predict\w*|forecast\w*|price target|where will|will (it|the stock|the price|\w+) "
                      r"(go|be|hit|reach|rise|fall|drop|crash|recover|double)|going to (go up|go down|crash|moon|rise|fall))\b", re.I)
_GIBBERISH = "I didn't catch that. Try asking how a stock has moved, or what a term like dividend yield means."

# ---- added 2026-11-21: glossary ("define"), non-English, judge tricks, worried holders ----------------------
_G = [  # (regex that must match the whole term the user typed, definition)
    (r"p/?e( ratio)?|price[- ]to[- ]earnings( ratio)?",
     "The P/E ratio is a stock's price divided by the company's profit per share. It is like asking how many dollars "
     "you pay for each dollar the company earns in a year; a higher ratio means investors expect more growth."),
    (r"etfs?|exchange[- ]traded funds?",
     "An ETF is a basket of many stocks (or other assets) that you buy in one go, and it trades on the market like a single stock. "
     "It is like buying a sampler box instead of one piece of fruit."),
    (r"index funds?",
     "An index fund is a fund that simply copies a list of companies, such as the S&P 500, instead of having someone pick winners. "
     "You get a small slice of every company on the list."),
    (r"dividends?",
     "A dividend is a payment some companies make to their shareholders out of profit, usually every three months. "
     "Think of it as a thank-you check for owning the stock; many companies pay none."),
    (r"dividend yields?",
     "Dividend yield is the yearly dividend divided by the share price, shown as a percent. "
     "It tells you how much cash a stock pays you each year for every dollar you put in."),
    (r"market ?caps?|market capitalization",
     "Market cap is the share price times the number of shares, so it is the price tag of the whole company. "
     "It shows how big a company is, not how good it is."),
    (r"eps|earnings per share",
     "EPS, or earnings per share, is a company's profit divided by its number of shares. "
     "It is your slice of the profit for each share you own."),
    (r"revenues?|sales",
     "Revenue is all the money a company brings in from selling its products, before any costs are taken out. "
     "It is the top line of the income statement."),
    (r"net income|profits?|net profits?|earnings",
     "Net income, or profit, is what is left of revenue after all costs, interest and taxes. "
     "It is what the company actually keeps."),
    (r"gross margins?",
     "Gross margin is the share of each sales dollar left after paying the direct cost of making the product. "
     "A higher margin means the company keeps more from each sale."),
    (r"buybacks?|share buybacks?|stock buybacks?",
     "A buyback is when a company buys its own shares from the market. "
     "That leaves fewer shares outstanding, so each remaining share owns a bigger slice of the company."),
    (r"10-?k|10-?k filing|10-?k report",
     "A 10-K is the long yearly report a public company files with the SEC, the US market regulator. "
     "It covers the business, results, risks and the audited financial statements."),
    (r"52[- ]?week (high|low|high and low|range|highs? and lows?)|52[- ]?week",
     "The 52-week high and low are the highest and lowest prices a stock has traded at over the past year. "
     "They show where today's price sits within its recent range."),
    (r"volatility|volatile",
     "Volatility is how much and how fast a price jumps around. "
     "A volatile stock swings a lot, like a bumpy road; a calm one moves in small steps."),
    (r"(a )?(bear|bull) markets?|bear and bull markets?|bulls? and bears?|bear markets? and bull markets?",
     "A bull market is a long stretch of rising prices; a bear market is a long stretch of falling prices, usually a drop of about a fifth or more. "
     "The names come from how each animal attacks: a bull thrusts up, a bear swipes down."),
    (r"short sell(ing)?|shorting|short selling|short positions?",
     "Short selling is betting that a price will fall: you borrow shares, sell them, and hope to buy them back cheaper. "
     "It can lose a lot, because a price can rise without a limit."),
    (r"stocks?|shares?|a stock|a share",
     "A stock, or share, is a small piece of ownership in a company. "
     "If the company does well, the value of your piece can rise, and it can fall if the company does badly."),
]
_G = [(re.compile(r"(?:%s)" % rx, re.I), text) for rx, text in _G]
_DEF_TRY = {
    "dividend": 'Try: "Does Apple pay a dividend?"',
    "eps": 'Try: "What was Apple\'s earnings per share last year?"',
    "market": 'Try: "How has Nvidia done this year?"',
    "default": 'Try: "What happened to Nvidia yesterday?" or "Bear case for Tesla".',
}
_DEF_LEAD = re.compile(r"^\W*(?:(?:hey|hi|ok|okay|so|quick question|just|also|please)[ ,]+)*"
                       r"(?:what(?:'s| is| are|s)|what does|what do you mean by|whats|define|explain|"
                       r"meaning of|can you explain|could you explain|tell me about|what is the meaning of|what's the meaning of)\s+", re.I)
_DEF_TAIL = re.compile(r"\s*(?:\bmean(?:s|ing)?\b|\bto me\b|\bplease\b|\bin simple terms\b|\bin plain english\b)?[\W]*$", re.I)
_ACRO_OK = {"ETF", "ETFS", "EPS", "PE", "P", "E", "SEC", "IPO", "ROI", "CEO", "CFO", "US", "USA", "AI", "I", "A", "K", "S", "SP"}


def _names_company(s: str) -> bool:
    """True when the message names a company or ticker (no network)."""
    try:
        from backend import tickers
    except Exception:
        return False
    if tickers._NAME_RX.search(s) or re.search(r"\$[A-Za-z]{1,6}\b", s):
        return True
    for tok in re.findall(r"\b[A-Z]{2,5}\b", s):
        if tok not in _ACRO_OK and tok not in tickers._STOP:
            return True
    known = set(tickers._KNOWN)
    for tok in re.findall(r"\b[a-z]{3,5}\b", s):
        if tok.upper() in known and tok.upper() not in {"COST", "SNOW", "SPOT", "SHOP", "COIN", "HOOD", "DIS"}:
            return True
    return False


def _define(s: str):
    if len(s.split()) > 10:
        return None
    m = _DEF_LEAD.match(s)
    if not m:
        return None
    rest = _DEF_TAIL.sub("", s[m.end():]).strip()
    rest = re.sub(r"^(?:an?|the)\s+", "", rest, flags=re.I)
    if not rest or _names_company(s):
        return None
    for rx, text in _G:
        if rx.fullmatch(rest):
            low = rest.lower()
            key = "dividend" if "dividend" in low else "eps" if ("eps" in low or "earnings per" in low) else \
                  "market" if ("market" in low or "bull" in low or "bear" in low) else "default"
            return "define", text + " " + _DEF_TRY[key]
    return None


_LANG_WORDS = set("""hola que qué tal cómo como cuál cuanto cuánto donde dónde porque precio accion acción acciones comprar vender el la los las
un una es esta está por para de del
bonjour quel quelle quels comment pourquoi combien prix action actions acheter les des est le une
hallo wie viel warum aktie aktien kurs kaufen der die das ist und ich nicht""".split())
_LANG_WORDS -= {"die", "de", "es", "la", "tal", "una", "un", "como", "wie", "est", "le", "las", "los", "el", "por", "para", "del", "que", "ist"}
_LANG_WEAK = {"como", "que", "ist", "est", "el", "la", "le", "los", "las", "es", "de", "del", "por", "para", "un", "una", "die", "der", "das", "wie", "und", "tal"}
_LANG_REPLY = ("For now Callisto answers in English only. Ask me in English, for example: "
               '"How has Nvidia done this year?" or "Does Apple pay a dividend?"')


def _non_english(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    if sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.3:
        return True
    toks = re.findall(r"[^\W\d_]+", s.lower())
    if not toks:
        return False
    strong = sum(1 for t in toks if t in _LANG_WORDS)
    weak = sum(1 for t in toks if t in _LANG_WEAK)
    return strong >= 1 and strong + weak >= 2 and (strong + weak) / len(toks) >= 0.3


_ADVICE_WORD = re.compile(r"\b(buy|sell|hold|pick|choose|invest\w*|recommend\w*|stocks?|shares?|tip|should i|advice)\b", re.I)
_TRICK = re.compile(
    r"\b(pretend|imagine|act|behave|roleplay|role-play|play the role|you are now|you're now)\b.{0,40}\b(advis[eo]r|broker|analyst|trader|fund manager|guru|wolf)\b|"
    r"\b(you are|you're|be) my (own )?(financial|personal|investment)?\s*(advis[eo]r|broker|analyst)\b|"
    r"\bact as (a |an |my )?(financial |stock |investment )?(advis[eo]r|broker|analyst|trader)\b|"
    r"\banswer (only |just )?(with )?(yes or no|yes/no|yes or no only|buy or sell|buy, sell)\b|"
    r"\b(just|only|simply) (say|tell me|answer) (buy|sell|hold|yes|no)\b|"
    r"\b(my (job|life|career|family|boss) depends|i('ll| will) (be fired|lose my job)|i beg you|please just say)\b", re.I)
_SOFT_TRICK = re.compile(
    r"\bhypothetical(ly)?\b|\bif you (had|have|were forced|must|absolutely had) to (pick|choose|buy|recommend|say)\b|"
    r"\bjust between (us|you and me)\b|\bbetween you and me\b|\boff the record\b|\bi won'?t tell (anyone|anybody|a soul)\b|"
    r"\bnobody (will )?(know|find out|has to know)\b|\bno one (will )?(know|find out)\b|\bnot (legal )?advice,? just\b", re.I)
_ROLEPLAY_REPLY = ("I can't play an adviser or pick a stock for you, even off the record or as a what-if. "
                   "What I can do is show the checked facts for any company and what to weigh on each side; just name one.")


def _roleplay(s: str):
    if _TRICK.search(s):
        return "roleplay", _ROLEPLAY_REPLY
    if _SOFT_TRICK.search(s) and _ADVICE_WORD.search(s):
        return "roleplay", _ROLEPLAY_REPLY
    return None


WORRY_LEAD = ("A big drop is stressful, and it is normal to want to act fast. "
              "Here is what the checked data shows, so you can decide with a clear head: ")
_WORRY = re.compile(
    r"\bshould i (be )?(worried|scared|concerned|nervous|panick?ing|freaking)\b|\bpanick?ing\b|\bfreaking out\b|"
    r"\bi('m| am) (down|losing|scared|worried|nervous|terrified|so worried)\b|\blosing money (on|in|with)\b|"
    r"\bdown \d+ ?%|\b(scared|terrified|worried|nervous) (about|of|that)\b|\bi (own|hold|bought|have|am holding) .{0,40}\b(dropped|fell|crashed|tanked|plunged|down)\b|"
    r"\bwhy (is|did) my .{0,25}\b(drop|fall|fell|crash|tank)\w*\b|\bmy (stock|shares|portfolio) (is|are|keeps?|keep) (dropping|falling|crashing|tanking)\b", re.I)


def wants_reassurance(q: str) -> bool:
    return bool(_WORRY.search(q or ""))


def reply(q: str):
    s = (q or "").strip()
    try:  # product questions, beginner questions and bare definitions (fixed text, same contract as this file)
        from backend import smalltalk_more
        more = smalltalk_more.reply(s)
        if more:
            return {"definition": "define", "spanish": "language"}.get(more[0], more[0]), more[1]
    except Exception:
        pass
    if _non_english(s):
        return "language", _LANG_REPLY
    if not re.search(r"[A-Za-z]{2}", s):
        return "unclear", _GIBBERISH
    d = _define(s)
    if d:
        return d
    for kind, rx, text in _RULES:
        if rx.search(s):
            if kind in ("offtopic", "rude") and _FINANCE.search(s):
                continue
            if kind in ("trust", "crypto", "offtopic") and _names_company(s):
                continue  # "how do you check Apple's numbers against last year" is a data question
            return kind, text
    rp = _roleplay(s)
    if rp:
        return rp
    words = re.findall(r"[A-Za-z]+", s)
    if len(words) == 1 and len(s) >= 5 and not re.search(r"[aeiouy]", s, re.I):
        return "unclear", _GIBBERISH
    if len(words) == 1 and re.fullmatch(r"[asdfghjklqwertzxcvbnm]{5,}", s.lower()) and len(set(s.lower())) <= 6:
        return "unclear", _GIBBERISH
    return None


def wants_prediction(q: str) -> bool:
    return bool(_PREDICT.search(q or ""))
