"""Next-round fixed chat replies (2026-11-21 crowd sweep): product questions, beginner questions, plain definitions.

NOT WIRED IN YET. To switch on, call `smalltalk_more.reply(q)` at the top of `smalltalk.reply` and return its
result when it is not None. Same contract as smalltalk.py: pure code, no model, no data, no digits in any reply,
and patterns tight enough that a question naming a company or asking for a figure still reaches the desk."""
from __future__ import annotations

import re

_ASK = r"^\W*(?:ok(?:ay)?,?\s+|so,?\s+|hey,?\s+|and\s+)?"
_END = r"\W*$"

_RULES = [
    ("vs_chatbots", r"\b(?:different|differ|better|worse|compare[ds]?)\b.{0,40}\b(?:chat ?gpt|gpt|claude|gemini|copilot|grok|other (?:ai|chat ?bots?|assistants?))\b|"
                    r"\bwhy (?:not|should i not) (?:just )?(?:use|ask) (?:chat ?gpt|gpt|claude|gemini|google)\b|\bwhy (?:use|should i use) (?:you|this|callisto|europa)\b",
     "A general chatbot writes an answer and you have to trust it. Callisto writes an answer, then a separate "
     "checker compares every number with its source, and any sentence that fails is removed before you see it. "
     "It also shows where each number came from, says so when the data doesn't cover something, and never tells "
     "you to buy or sell."),
    ("who_checks", r"\bwho (?:checks?|verif\w+|confirms?|reviews?) (?:the|your|these|those) (?:numbers?|figures?|data|answers?|facts?)\b|"
                   r"\bwhat (?:checks?|verif\w+) (?:the|your) (?:numbers?|answers?)\b|\bis (?:a|there a) (?:human|person) (?:check|review)\w*\b",
     "Two checks run on every answer, and neither is a person. A second AI model reads the draft against the "
     "source data and flags anything it can't support. Then plain code, with no AI in it, compares each number "
     "with the source value and removes any sentence that doesn't match. Company figures come from the annual "
     "report filed with the SEC; prices come from Massive end-of-day market data."),
    ("can_be_wrong", r"\b(?:can|could|do|are) (?:you|callisto|europa|it) (?:ever )?(?:be |get (?:things |it |stuff )?)?(?:wrong|mistaken|incorrect|make mistakes?|lie|lying)\b|"
                     r"\bhow (?:accurate|reliable) (?:are|is) (?:you|callisto|europa|this)\b|\bwhat (?:are|is) your (?:limits?|limitations?|weakness\w*)\b",
     "Yes. The wording comes from an AI model, so a sentence can be clumsy or miss the point. What the checker "
     "protects is the numbers: each one is compared with its source, and a sentence with a number that doesn't "
     "match is removed. Known limits: full company reports are loaded for Apple only, prices are end-of-day and "
     "come from a single provider, and headlines are shown as published without being checked."),
    ("privacy", r"\b(?:is|are|do|does|will|where)\b.{0,40}\b(?:my|our|the|user|personal) (?:data|questions?|chats?|info\w*|conversations?|history)\b.{0,30}\b(?:stor\w+|sav\w+|kept|keep|track\w*|record\w*|log\w*|shar\w+|sold|sell|private|safe|secure|go(?:es)?)\b|"
                r"\bdo you (?:store|save|keep|track|record|log|sell|share|remember) (?:my|our|user|any|what i)\b|\b(?:privacy|private) (?:policy|mode)?\W*$",
     "Callisto has no accounts and builds no profile of you: it doesn't ask who you are and keeps no personal "
     "details. To answer, your question is sent to the AI models that write the reply, and each step of the "
     "answer is logged so the number checks can be audited. Don't type anything personal, like account numbers."),
    ("private_co", r"\b(?:openai|open ai|spacex|space x|anthropic|stripe|chatgpt(?:'s)? (?:stock|shares?)|xai|databricks|"
                   r"bytedance|tiktok|shein|discord|epic games|valve|ikea|lego|rolex|publix|cargill|koch)\b",
     "That company is private, so it has no shares on the stock market and no public price for Callisto to "
     "check. Callisto covers companies and funds that trade on American exchanges. Try a listed company "
     "in the same field, such as Microsoft, Nvidia or Alphabet."),
    ("spanish", r"\b(?:c[oó]mo|qu[eé]|cu[aá]l|cu[aá]nto|d[oó]nde|por ?qu[eé]|acciones|acci[oó]n|precio|comprar|vender|invertir|"
                r"ganancias|hola|gracias)\b",
     "Por ahora Callisto responde en inglés. Escribe el nombre de una empresa o su símbolo, por ejemplo Apple o "
     "NVDA, y verás sus cifras comprobadas. / Callisto answers in English for now. Type a company name or "
     "ticker, like Apple or NVDA, and it will show its checked numbers."),
    ("guaranteed", r"\b(?:guaranteed?|sure thing|can'?t lose|cannot lose|risk[- ]free|no[- ]risk|safe bet|will definitely|certain to)\b.{0,40}\b(?:stock|share|invest\w*|go up|rise|win\w*|return|profit|money)\b|"
                   r"\b(?:stock|share|invest\w*)\b.{0,40}\b(?:guaranteed?|can'?t lose|cannot lose|risk[- ]free|sure thing)\b",
     "No stock is guaranteed to go up, and anyone who promises one is a warning sign. Callisto doesn't pick "
     "winners. Name a company and I'll show how it has moved, what its numbers say and what to weigh."),
    ("beginner", r"\bhow (?:do|can|should|would) (?:i|we|you|someone|a beginner) (?:even )?(?:start|begin|get started|get into|learn)\b.{0,30}\b(?:invest\w*|stocks?|trading|the (?:stock )?market)\b|"
                 r"\b(?:i'?m|i am|as) (?:a |an )?(?:new|beginner|newbie|total beginner)\b.{0,30}\b(?:invest\w*|stocks?|trading)\b|\binvesting for (?:beginners|dummies)\b|"
                 r"\bwhere (?:do|should) i (?:start|begin)\b",
     "Callisto doesn't give personal advice, but here is how people usually begin. Learn what you would be buying: "
     "a stock is a small piece of one company, and a fund holds many companies at once, which spreads the risk. "
     "Only use money you won't need soon, because prices can fall hard. Then look at real numbers before trusting "
     "a tip. Name a company or a fund like SPY and I'll show how it has moved and what to weigh."),
]

# Plain definitions, only for a bare "what is X?" (a question that also names a company or asks for a figure
# goes to the desk, which gives the definition together with the checked number).
_TERMS = [
    (r"(?:a |the )?stocks?|(?:a |the )?shares?(?: of stock)?",
     "A stock, also called a share, is a small piece of ownership in a company. If the company does well the "
     "share usually becomes worth more, and if it does badly the share can lose value."),
    (r"(?:a |the )?dividends?(?: yield)?",
     "A dividend is cash a company pays its shareholders, usually a few times a year. The dividend yield is the "
     "yearly dividend as a percent of the share price. Ask \"Does Apple pay a dividend?\" to see a real one."),
    (r"(?:a |the )?market cap(?:itali[sz]ation)?",
     "Market cap, short for market capitalization, is what the whole company is worth on the stock market: the "
     "share price times the number of shares. It is the usual way to say how big a company is."),
    (r"(?:an? |the )?(?:etfs?|exchange[- ]traded funds?|index funds?|mutual funds?|funds?)",
     "A fund pools money from many investors and holds a basket of investments, often hundreds of companies at "
     "once. An index fund or ETF simply follows a list such as the largest American companies, so one purchase "
     "spreads the risk. Type a fund ticker like SPY to see how one has moved."),
    (r"(?:an? |the )?(?:p/?e|pe|price[- ]to[- ]earnings|price earnings)(?: ratio| multiple)?",
     "The P/E ratio is the share price divided by the profit per share over a year. It shows how much investors "
     "pay for each dollar of profit: a high figure means they expect strong growth, a low one means they expect "
     "less. It is only a starting point, not a verdict."),
    (r"(?:an? |the )?(?:eps|earnings per share)",
     "EPS means earnings per share: the company's profit divided by its number of shares. It tells you how much "
     "profit stands behind each share. Ask \"What was Apple's EPS?\" to see a checked figure."),
    (r"(?:an? |the )?(?:10-?k|ten-?k|annual report)(?: filing| form| report)?",
     "It is the annual report a public company must file with the SEC, the American market regulator. It holds "
     "the audited sales and profit figures and a list of the risks the company sees. Callisto reads Apple's and "
     "checks every number against it."),
    (r"(?:a |the )?(?:ticker|ticker symbol|stock symbol)",
     "A ticker is the short code a stock trades under, such as AAPL for Apple or NVDA for Nvidia. You can type "
     "either the company name or its ticker."),
    (r"(?:a |the )?(?:bear|bull)(?: case| market)?(?: and (?:a |the )?(?:bear|bull)(?: case| market)?)?",
     "A bull expects prices to rise and a bear expects them to fall. A bull case is the list of reasons a stock "
     "could do well; a bear case is the list of reasons it could do badly. Ask \"Bear case for Tesla\" to see one "
     "built from checked numbers."),
    (r"(?:the )?(?:52|fifty[- ]two)[- ]week (?:high|low|range)(?: and (?:low|high))?",
     "It is the highest and lowest price a stock traded at over the past year. It shows quickly whether today's "
     "price is near the top or the bottom of its recent range."),
    (r"(?:a |the )?(?:revenue|sales|net sales|net income|profit|gross margin|operating income)",
     "Revenue, also called sales, is all the money a company brings in. Profit, also called net income, is what "
     "is left after every cost and tax. Gross margin is the share of each sales dollar left after the cost of "
     "making the product. Ask about Apple to see the checked figures."),
]

_RULES = [(k, re.compile(rx, re.I), t) for k, rx, t in _RULES]
_TERMS = [(re.compile(_ASK + r"(?:what(?:'s| is| are| does)|define|explain|meaning of|what do you mean by)\s+(?:" + rx +
                      r")(?:\s+(?:mean|stand for|in (?:stocks|investing|finance)))?" + _END, re.I), t) for rx, t in _TERMS]
_COMPANY = re.compile(r"\b(?:apple|aapl|nvidia|tesla|microsoft|amazon|google|meta)\b|\$[A-Za-z]{1,5}\b|\b(?:19|20)\d\d\b", re.I)


def reply(q: str):
    s = (q or "").strip()
    if not s or len(s) > 160:
        return None
    for rx, text in _TERMS:
        if rx.match(s):
            return "definition", text
    named = bool(_COMPANY.search(s))
    for kind, rx, text in _RULES:
        if named and kind != "spanish":
            continue
        if rx.search(s):
            return kind, text
    return None
