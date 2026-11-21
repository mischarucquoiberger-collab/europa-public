# PLAN-MULTIAGENT: Europa "Research Desk" (multi-agent backend)

Written Sat 2026-11-21 ~11:15 ET by the planning agent. Code freeze 2:30 PM ET.
Planner wrote no code. This file is the single source of truth for the three builders and the integrator.

## 0. One-paragraph summary

Europa becomes a small research desk. A cheap Claude model routes the question. Up to four specialists
fetch evidence in parallel (SEC filings, Massive market data, Massive fundamentals cross-checked against the SEC
sheet, Massive news). Claude Sonnet writes a draft from that evidence only. An OpenAI model (the skeptic) tries to
refute each sentence and can only delete. Then code has the last word: the existing number checker, now fed the
market facts too, plus a new "naked number sweep", blocks anything it cannot prove. If Massive has no key or
errors, those specialists say "unavailable" and the answer says so in a sentence written by code, not by a model.

## 1. What was checked before planning (sources)

| Claim | Source |
|---|---|
| Repo state: 24 unit tests pass, single-agent path = guard -> facts -> writer -> checker | ran `.venv/bin/python -m pytest -q` at 11:10 (24 passed); read `backend/*.py` |
| Massive auth: `Authorization: Bearer <key>` header, base `https://api.massive.com` | https://massive.com/docs/rest/quickstart.md ("Authenticate Your Request") |
| No key -> HTTP 401, body `{"status":"ERROR","error":"API Key was not provided","request_id":...}` | live unauthenticated GET to `/v2/aggs/ticker/AAPL/prev` and `/stocks/financials/v1/income-statements`, 11:08 ET |
| Daily bars: `GET /v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}`, params `adjusted`, `sort` (asc/desc), `limit` (default 5000, max 50000); results `o,h,l,c,v,vw,n,t` (t = Unix ms, start of window); from/to inclusive; all Stocks plans; Basic = 2 years history, end-of-day | https://massive.com/docs/rest/stocks/aggregates/custom-bars.md |
| Previous day bar: `GET /v2/aggs/ticker/{stocksTicker}/prev` (same result fields plus `T`); all plans | https://massive.com/docs/rest/stocks/aggregates/previous-day-bar.md |
| Ticker overview: `GET /v3/reference/tickers/{ticker}`; `results.name`, `results.market_cap`, `results.weighted_shares_outstanding`, `results.share_class_shares_outstanding`, `results.cik`, `results.total_employees`; all plans, updated daily | https://massive.com/docs/rest/stocks/tickers/ticker-overview.md |
| Income statements: `GET /stocks/financials/v1/income-statements`; filters `tickers`, `timeframe` (quarterly/annual/trailing_twelve_months), `fiscal_year`, `period_end`, `limit`, `sort` (e.g. `period_end.desc`); fields `revenue`, `gross_profit`, `research_development`, `operating_income`, `consolidated_net_income_loss`, `diluted_earnings_per_share`, `period_end`, `fiscal_year`, `filing_date`, `timeframe`, `tickers`. **NOT in Stocks Basic/Starter/Developer** (needs Stocks Advanced or the Financials & Ratios Expansion) | https://massive.com/docs/rest/stocks/fundamentals/income-statements.md ("Plan Access") |
| News: `GET /v2/reference/news`; params `ticker`, `order`, `sort`, `limit` (default 10, max 1000), `published_utc.gte`; fields `id`, `title`, `publisher.name`, `published_utc`, `article_url`, `description`, `tickers`; all plans, updated hourly | https://massive.com/docs/rest/stocks/news.md |
| Named steps inside `RunnableParallel` show up as their own child runs when `config` is passed down | ran a local probe at 11:10: callback saw `europa_desk, specialists, specialist_a, specialist_b` |
| A "bare number" sweep would not break today's answers: the only digits the checker does not already cover in the 4 saved runs are years (2025/2026/2027) and "10-K" | ran the checker over `test-runs/*.md` at 11:10 |

UNVERIFIED (design must not depend on these):
- Massive 403 body for "plan does not include this data" (guess from Polygon heritage: `{"status":"NOT_AUTHORIZED","message":...}`). Treat ANY 403 as "not entitled".
- Massive rate limit on the Basic plan (memory says about 5 calls per minute). Design: at most 4 Massive calls per question, in-memory cache, 429 -> "unavailable (rate limit)".
- Whether Nicrron accepts `temperature=0` for `openai/gpt-5.x` models (`backend/llm.py` hard-codes it). Design: every model agent has a fallback model list; the skeptic failing never blocks an answer (code gate still runs).
- Which Massive plan the team's key will have. Fundamentals will probably come back "not entitled". That is an honest "unavailable", not a bug.
- Open-source scout (parent CLAUDE.md rule) was NOT done: search budget is exhausted and freeze is 3 hours away. Endpoint paths come from the official docs; no third-party code is copied. The router -> specialists -> critic -> code gate shape is a standard pattern. Integrator: log this in `../decisions.md`.

## 2. Architecture

```
POST /api/ask
  |
  v
ask.answer()  -- EUROPA_PIPELINE=multi (default) --> desk.answer()      [any exception -> ask.answer_single(), pipeline="single_fallback"]
              -- EUROPA_PIPELINE=single ----------> ask.answer_single() (today's code, untouched logic)

desk.answer()  (PRISM run "europa_desk"; every box below is a named LangChain Runnable = one PRISM step)

 1 guard_advice          code, no model      regex advice / "make it up" guard (same patterns as ask.py)
 2 desk_router           Claude Haiku 5.5    picks specialists; second advice detector; keyword fallback if model fails
 3 specialists           (RunnableParallel)
     specialist_filings        code           SEC fact sheet + risk-factor quotes (facts.py)
     specialist_market         code + Massive daily bars + ticker overview -> prices, returns, 52-week range, market cap
     specialist_fundamentals   code + Massive income statements vs SEC sheet; two sources must agree, else quarantine
     specialist_news           code + Massive headlines, fetched and advice-filtered
 3b news_picker          OpenAI gpt-5.4-mini returns headline IDs only (cannot change a word); only if > 3 headlines
 4 write_answer          Claude Sonnet 5.5   writes JSON draft from the evidence sheets only (never sees headline text)
 5 skeptic_review        OpenAI gpt-5.4-mini tries to refute each sentence; may only flag for deletion
 6 number_gate           code (final word)   skeptic deletions -> advice-phrase filter -> checker.check() over SEC + market
                                             facts minus quarantined ones -> naked-number sweep -> status
 7 notices               code                appends "X is unavailable (reason)" and "Market data: Massive, as of DATE"
```

Why this shape
- **Models never do arithmetic.** Returns, ranges and comparisons are computed in Python. Models only choose, phrase and criticise.
- **Two model families.** Claude writes, OpenAI attacks. The skeptic catches what a number checker cannot: a real number pinned to the wrong metric or year, "rose" where the data says "fell", causes the evidence never states, advice-like wording.
- **The skeptic can only delete.** It returns verdicts by sentence number. It cannot add or reword text, so it cannot add a wrong number.
- **Code has the last word.** Every number in the final text must match a fact (SEC or Massive, with source and as-of date) within the rounding written, or it is a year / form name / known date, or the sentence is cut (status UNCHECKABLE). This closes today's gap where a bare number like "229.87" (no $ or %) was never looked at.
- **Two sources must agree.** If Massive's income statement disagrees with the SEC sheet on a figure, that fact id (and what is derived from it) is quarantined for the request: the writer does not see it and the gate will not verify it.
- **News is relayed, not restated.** Headlines go to the user word for word with publisher and date in a separate `news` field. The writer never sees them, so news cannot leak into "verified" prose.
- **Honest degrade is deterministic.** "Unavailable" sentences are written by code from the specialist's reason string. No model is asked to admit a gap.
- **Six advice layers:** regex guard, router flag, writer prompt, skeptic ADVICE verdict, gate advice-phrase filter, disclaimer.

BEFORE/AFTER for PRISM: `EUROPA_CHECKER=off` skips steps 5 and 6 (trace shows router, specialists, writer, raw output). Default (on) shows the skeptic and the gate cutting things.

## 3. Shared data shapes (plain dicts; there is NO shared helper module, each builder builds these by hand)

### Fact (same shape as `facts.FACTS` entries, three optional keys added)
```python
{"label": "Closing price, last trading day (2026-11-20)",
 "value": 229.87,                       # float, unrounded (round to 4 decimals for pct)
 "kind": "usd_per_share",               # usd | usd_per_share | pct | pts | count
 "source": "Massive market data (end-of-day, as of 2026-11-20)",
 "as_of": "2026-11-20",                 # optional
 "provider": "massive",                 # optional: massive | sec | calc
 "display": "$229.87"}                  # optional: exactly how the writer should write it
```

### Evidence pack (what every specialist returns)
```python
{"agent": "market",                     # filings | market | fundamentals | news
 "status": "ok",                        # ok | unavailable
 "reason": None,                        # plain English when unavailable, e.g. "MASSIVE_API_KEY is not set"
 "source": "Massive market data (end-of-day)",
 "as_of": "2026-11-20",                 # or None
 "facts": {fact_id: Fact, ...},         # EXTRA facts for the checker. filings/fundamentals/news leave {}.
 "exclude": [],                         # SEC fact ids quarantined (fundamentals only)
 "sheet": "MARKET DATA ...",            # text the writer sees ("" when unavailable or news)
 "allow_text": ["52-week"],             # literal strings with digits that are not claims
 "allow_dates": ["2026-11-20"],         # ISO dates the answer may mention
 "items": [],                           # news only: [{"id","title","publisher","published_utc","url"}]
 "crosscheck": [],                      # fundamentals only: [{"fact_id","label","sec_value","massive_value","result"}]
 "seconds": 0.21}
```
Every key is always present (use the empty value shown).

### Skeptic verdicts
`[{"i": 1, "verdict": "SUPPORTED" | "UNSUPPORTED" | "ADVICE", "why": "short reason"}]` where `i` is the 1-based index into `checker.split_sentences(draft["answer"])`. A missing index means SUPPORTED.

### Draft (writer output; same as today's `ask._parse` result)
`{"status": "ANSWERED" | "I_DONT_KNOW", "answer": str, "claims": [{"value": "$478.8 billion", "fact_id": "revenue_fy2026"}, {"type": "quote", "text": "...", "filing": "FY2026"}]}`

### /api/ask response (old keys unchanged; new keys optional)
Old: `answer, claims, status, blocked, company, prism_session_id, models, checker, seconds, data_note, disclaimer`.
New optional:
```python
"pipeline": "multi" | "single" | "single_fallback",
"agents": [{"name": "desk_router", "kind": "model" | "code", "model": "anthropic/claude-haiku-5-5" | None,
            "status": "ok" | "unavailable" | "skipped", "note": "picked filings, market", "seconds": 0.8}, ...],
"sources": [{"name": "SEC EDGAR 10-K", "status": "ok", "as_of": None, "reason": None},
            {"name": "Massive market data (end-of-day)", "status": "unavailable", "as_of": None, "reason": "MASSIVE_API_KEY is not set"}],
"unavailable": [{"agent": "market", "reason": "MASSIVE_API_KEY is not set"}],
"news": [{"title", "publisher", "published_utc", "url"}],
"skeptic": {"status": "ok" | "unavailable" | "off" | "advisory", "model": str | None, "refuted": 0, "flags": [...]},
```
`claims[]` entries may add `as_of` and `provider`. `claims[].status` may also be `UNCHECKABLE`. `blocked[].status` may also be `REFUTED`, `ADVICE`, `UNCHECKABLE`.

## 4. Tasks (three builders in parallel, disjoint files)

| Task | Owner files | Touches existing files? |
|---|---|---|
| T1 data-desk | `backend/massive.py`, `backend/specialists.py`, `tests/test_massive.py`, `tests/test_specialists.py` | no |
| T2 reasoning-desk | `backend/agents.py`, `backend/desk.py`, `tests/conftest.py`, `tests/test_agents.py`, `tests/test_desk.py` | no |
| T3 verification-desk | `backend/checker.py` (additive only), `backend/gate.py`, `tests/test_gate.py` | yes (checker.py only) |
| Integration | `backend/ask.py`, `backend/llm.py`, `backend/app.py`, `backend/static/index.html`, `scripts/run_test_plan.py`, `.env.example`, `README.md`, `CLAUDE.md` | yes |

Rules for all builders
- Python at `.venv/bin/python`. Install nothing. Use `httpx` for HTTP. All model calls through `backend/llm.py` (`llm.model(name)`).
- Never read, print, log or write the value of any key. Never open `.env`. Do not commit, push or `git add`.
- Unit tests mock all network: no live Massive call, no live Nicrron call.
- Edit only your owner files. If you need something from another task, code against the interface in this plan.
- Done = your new tests pass AND `.venv/bin/python -m pytest -q` still passes everything that existed (24 tests).
- Report: files written, test count, anything you could not verify (label it UNVERIFIED).

### T1 data-desk: Massive client + four specialists (no model calls)

`backend/massive.py`
```python
BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")   # load_dotenv() at import, like llm.py
_TRANSPORT = None            # tests set this to httpx.MockTransport(handler)

class Unavailable(Exception):          # .code and .reason (plain English, no URL, no key)
    # codes: no_key | bad_ticker | unauthorized | not_entitled | rate_limited | not_found | http_error | network | empty

def available() -> bool                # True if MASSIVE_API_KEY is non-empty; read os.environ at CALL time
def valid_ticker(t: str) -> bool       # ^[A-Z][A-Z0-9.\-]{0,9}$   (the ticker goes into a URL path)
def today_et() -> datetime.date        # today in America/New_York; tests monkeypatch this
def get(path: str, params: dict | None = None, ttl: float = 600) -> dict     # parsed JSON; raises Unavailable
def clear_cache() -> None
def daily_bars(ticker, start: date, end: date) -> list[dict]   # [{"date":"YYYY-MM-DD","o","h","l","c","v"}] oldest first
def ticker_overview(ticker) -> dict                             # the "results" object
def income_statements(ticker, limit: int = 8) -> list[dict]     # annual rows, newest first
def news(ticker, limit: int = 10) -> list[dict]                 # raw "results" list, newest first
```
- Auth header only: `Authorization: Bearer <key>`. Never put the key in the query string. Timeout 8 s (connect 4 s). No retries, no sleeping.
- Error map: no key -> `no_key` "MASSIVE_API_KEY is not set"; 401 -> `unauthorized` "Massive rejected the API key"; 403 -> `not_entitled` "the Massive plan on this key does not include this data"; 429 -> `rate_limited` "Massive rate limit reached, try again in a minute"; 404 -> `not_found`; other non-2xx -> `http_error` "Massive returned HTTP <code>"; httpx error/timeout -> `network` "could not reach Massive"; bad JSON -> `http_error`.
- Cache: dict keyed by `(path, sorted params)`, guarded by `threading.Lock`, TTL from `ttl`. If a refresh fails and an older entry exists, return the older entry (it still carries its own dates). Do not cache failures except `not_entitled`/`unauthorized` for 60 s.
- Endpoints (exact):
  - bars: `GET /v2/aggs/ticker/{T}/range/1/day/{from}/{to}` params `adjusted=true, sort=asc, limit=5000`; `t` is Unix ms -> date in America/New_York. Empty/missing `results` -> `Unavailable("empty", ...)`.
  - overview: `GET /v3/reference/tickers/{T}`.
  - income statements: `GET /stocks/financials/v1/income-statements` params `tickers={T}, timeframe=annual, sort=period_end.desc, limit=<limit>`.
  - news: `GET /v2/reference/news` params `ticker={T}, order=desc, sort=published_utc, limit=<limit>`.

`backend/specialists.py`
```python
def filings(inp: dict) -> dict        # inp = {"ticker": str, "question": str}; returns an evidence pack
def market(inp: dict) -> dict
def fundamentals(inp: dict) -> dict
def news(inp: dict) -> dict
FILINGS = RunnableLambda(filings, name="specialist_filings")
MARKET = RunnableLambda(market, name="specialist_market")
FUNDAMENTALS = RunnableLambda(fundamentals, name="specialist_fundamentals")
NEWS = RunnableLambda(news, name="specialist_news")
SPECIALISTS = {"filings": FILINGS, "market": MARKET, "fundamentals": FUNDAMENTALS, "news": NEWS}
```
No specialist ever raises: catch `massive.Unavailable` (and any other Exception) and return a pack with `status="unavailable"` and a plain-English `reason`.

- **filings**: ticker in `facts.FACTS` -> ok, `sheet = facts.fact_sheet(ticker)`, `source = "SEC EDGAR 10-K (XBRL facts and filing text)"`, `facts = {}` (SEC facts already live in `facts.FACTS`), `allow_dates = ["2026-09-26", "2025-09-27", "2026-11-03"]` for AAPL. Else unavailable: "no SEC filings are loaded for {ticker} in this demo".
- **market** (2 Massive calls): bars from `today_et() - 400 days` to `today_et()`, plus overview. All maths in Python. `as_of` = date of the last bar. Facts (ids exact):
  `px_close_last` (usd_per_share), `px_open_last`, `px_high_last`, `px_low_last`, `px_close_prior` (bar before last), `volume_last` (count; skip if < 1,000,000),
  `ret_1d_pct`, `ret_1w_pct` (5 trading days back), `ret_1m_pct` (21), `ret_3m_pct` (63), `ret_ytd_pct` (vs last close of the previous calendar year), `ret_1y_pct` (vs last bar on or before as_of minus 365 days) (all kind pct, value in percent, rounded to 4 decimals; skip a fact if there are not enough bars),
  `px_52w_high` (max `h`), `px_52w_low` (min `l`) over bars newer than as_of minus 365 days,
  `market_cap` (usd, from overview) and `shares_outstanding` (count, `weighted_shares_outstanding`), both with `as_of = today_et()`; skip if missing. Overview failing must not sink the price facts (and the other way round): status ok if at least one fact exists.
  `source` on each fact: `"Massive market data (end-of-day, as of <as_of>)"`; returns: `"Calculated from Massive daily closes (split-adjusted, dividends not included, as of <as_of>)"`.
  `display`: prices `$1,234.56`; pct signed one decimal `+3.2%` / `-1.4%` (round half up, like `facts._r1`); market cap `$3.46 trillion` (or `$812.4 billion`); counts `52.3 million` / `15.12 billion`.
  Labels use words for windows, never digits ("one week (five trading days)", "one month", "three months", "year to date", "one year"), except "52-week".
  `sheet`: header `MARKET DATA (Massive, end-of-day, as of <as_of>; id | what | value):` then `fact_id | label | display` lines.
  `allow_text = ["52-week"]`, `allow_dates = [as_of, today]`.
- **fundamentals** (1 Massive call): needs ticker in `facts.FACTS`, else unavailable ("no SEC facts loaded to cross-check against"). Match annual rows to SEC years by `period_end` within 7 days of `PERIODS = {"AAPL": {"fy2026": "2026-09-26", "fy2025": "2025-09-27"}}`. Field map: `revenue->revenue`, `gross_profit->gross_margin`, `research_development->rnd`, `operating_income->operating_income`, `consolidated_net_income_loss->net_income`, `diluted_earnings_per_share->eps_diluted`. For each (field, year): SEC value = `facts.FACTS[ticker][f"{key}_{fy}"]["value"]`. AGREE if `abs(massive - sec) <= max(0.0005 * abs(sec), 1e6)` for usd, `<= 0.005` for per-share. Missing Massive value -> `NOT_COMPARED`. `crosscheck` lists every comparison. `exclude` = for each DISAGREE: `{key}_{fy}`, `{key}_change_pct`, `{key}_change_amount`; and if key is revenue or gross_margin also `gross_margin_pct_fy2026`, `gross_margin_pct_fy2025`, `gross_margin_pct_change_pts`. No matching rows at all -> unavailable ("Massive has no annual income statement for these fiscal years yet"). `facts = {}`. `sheet` (no counts, no digits outside ids): `SECOND-SOURCE CHECK (Massive income statements): confirmed by a second source: <ids>. NOT confirmed, do not use: <ids>.` `source = "Massive income statements (cross-check against SEC XBRL)"`.
- **news** (1 Massive call): `massive.news(ticker, 10)` -> `items` = up to 8 of `{"id","title","publisher"(publisher.name),"published_utc","url"(article_url)}`. Drop a headline whose title matches advice wording (case-insensitive): `\b(buy|sell|hold|price target|upgrade[sd]?|downgrade[sd]?|should you|stock to (buy|own)|millionaire)\b`. Nothing left -> unavailable ("no recent headlines"). `sheet = ""`, `facts = {}`, `source = "Massive news feed"`.

Tests (`tests/test_massive.py`, `tests/test_specialists.py`; set `massive._TRANSPORT = httpx.MockTransport(handler)` and `monkeypatch.setenv/delenv("MASSIVE_API_KEY")` with a fake value like "test-key"; call `massive.clear_cache()` in a fixture; do not rely on `tests/conftest.py`):
1. no key -> `available()` False, `get()` raises `no_key`, and the mock transport was never called.
2. header is `Authorization: Bearer test-key`; the key is not in the URL.
3. 401, 403, 429, 500, timeout -> right `code`; `reason` contains neither the key nor a URL.
4. cache: second identical call does not hit the transport; stale entry served when refresh fails.
5. `valid_ticker` rejects `"../x"`, `"AAPL/prev"`, `""`, lower case.
6. bars parsing: Unix ms -> ET date; ascending.
7. market with a synthetic 300-bar series: `px_close_last`, `ret_1d_pct`, `ret_1m_pct`, `px_52w_high` equal hand-computed values; `display` strings right; every fact has `source`, `as_of`, `kind`.
8. market with no key -> `status == "unavailable"`, reason mentions `MASSIVE_API_KEY`, `facts == {}`.
9. fundamentals: all AGREE -> `exclude == []`; one revenue row off by 1% -> DISAGREE and `exclude` holds `revenue_fy2026`, `revenue_change_pct`, `revenue_change_amount`, the three gross-margin-pct ids; 403 -> unavailable with the plan reason.
10. news: advice headline dropped; fields mapped; no key -> unavailable.
11. filings: AAPL ok and sheet contains `revenue_fy2026`; MSFT unavailable.
12. every pack has every key from section 3.

### T2 reasoning-desk: model agents + orchestrator

`backend/agents.py` (all model calls via `llm.model(name)`; helper below gives fallback models)
```python
ROUTER_MODELS  = [os.environ.get("MODEL_ROUTER",  llm.MODEL_FAST), "openai/gpt-5.4-mini"]
WRITER_MODELS  = [os.environ.get("MODEL_WRITER",  llm.MODEL_STRONG), "openai/gpt-5.4"]
SKEPTIC_MODELS = [os.environ.get("MODEL_SKEPTIC", "openai/gpt-5.4-mini"), "openai/gpt-5-mini", "mistral/mistral-large-4"]
NEWS_MODELS    = [os.environ.get("MODEL_NEWS",    "openai/gpt-5.4-mini"), llm.MODEL_FAST]

def call_json(models, system, human, config, need_key=None) -> tuple[dict | None, str | None]
    # try each model in order; return (last complete JSON object that has need_key, model name); (None, None) if all fail.
    # Catch every Exception per model. Never raise.

def route_by_keywords(question: str) -> list[str]          # pure code fallback
def route(inp, config) -> dict     # in {"ticker","question"} -> {"specialists":[...], "advice": bool, "reason": str, "model": str|None, "fallback": bool}
def pick_news(inp, config) -> dict # in {"question","items"}  -> {"ids":[...], "model": str|None}
def write(inp, config) -> dict     # in {"ticker","company","question","sheets":[str],"unavailable":[{"agent","reason"}],"has_news": bool} -> {"draft": Draft, "model": str|None}
def review(inp, config) -> dict    # in {"question","sheets":[str],"sentences":[str]} -> {"status":"ok"|"unavailable","verdicts":[...],"model": str|None}
ROUTER = RunnableLambda(route, name="desk_router");   NEWS_PICKER = RunnableLambda(pick_news, name="news_picker")
WRITER = RunnableLambda(write, name="write_answer");  SKEPTIC = RunnableLambda(review, name="skeptic_review")
```
- **route**: model returns `{"specialists": [...], "advice": true|false, "reason": "..."}`. Prompt must say: filings = annual 10-K figures and risk factors; market = stock price, returns, 52-week range, market cap, volume; fundamentals = "does a second source agree / is this confirmed"; news = headlines. `advice=true` ONLY when the user asks what they should do with their money (buy, sell, hold, get in, get out, how much to own) or wants a promise about returns. Forecasts, price targets and "what will revenue be" are NOT advice (they go to filings and end as I_DONT_KNOW). Keep only known names; empty -> `["filings"]`. Model failure -> `route_by_keywords` with `fallback=True`, `advice=False`. Keywords: price|stock|share price|close|closing|trading|return|market cap|52-week|volume|high|low -> market; news|headline|article|press -> news; second source|cross-check|confirm|agree|massive -> fundamentals; anything else, or nothing matched -> filings (add filings whenever revenue|sales|margin|eps|income|risk|10-k|filing|buyback|r&d appear).
- **pick_news**: model sees `N1..Nk | date | publisher | title` and returns `{"ids": ["N2","N5"]}` (max 3). Unknown ids dropped. Failure or `len(items) <= 3` -> first 3 without a model call. The model never returns headline text.
- **write**: system prompt = today's `ask.SYSTEM` rules (import and reuse `ask._parse` for parsing) plus: use ONLY the evidence sheets; cite every number with its `fact_id` and write it exactly as shown in the sheet; write time windows in words, never digits (except "52-week"); write dates exactly as the sheet shows them (YYYY-MM-DD); do not mention counts of anything; if a source is listed under UNAVAILABLE do not guess and do not apologise at length (code adds the notice); never describe news content (if `has_news`, you may say headlines are listed below); market numbers are past data, never a view on what to do; no advice. All models failing -> `draft = {"status": "I_DONT_KNOW", "answer": "I couldn't produce a checked answer to that.", "claims": []}`.
- **review** (the skeptic): gets the question, the evidence sheets and numbered sentences. For each sentence: `UNSUPPORTED` only if it can name the evidence line that contradicts it, or the sentence states something (a cause, a direction, a metric/year pairing, a comparison) that the evidence does not contain; `ADVICE` if it tells the reader what to do with money or predicts returns; else `SUPPORTED`. Sentences that only say data is unavailable or that Europa does not know are always SUPPORTED. Returns JSON `{"verdicts":[{"i":1,"verdict":"...","why":"..."}]}`. Drop verdicts with a bad index. All models fail or bad JSON -> `{"status":"unavailable","verdicts":[],"model":None}`.

`backend/desk.py`
```python
@dataclass
class Deps: guard; router; specialists: dict; news_picker; writer; skeptic; gate      # each a Runnable (or callable)
def default_deps() -> Deps     # imports backend.agents, backend.specialists, backend.gate INSIDE the function
def answer(ticker: str, question: str, deps: Deps | None = None) -> dict   # full /api/ask response, pipeline="multi"
PIPELINE = RunnableLambda(_pipeline, name="europa_desk")
```
`answer()` mirrors `ask.answer()`: session id `ask-<12 hex>`, `with tracing.session(sid)`, `config={"callbacks": tracing.callbacks(), "run_name": "europa_desk", "metadata": {"ticker", "checker", "pipeline": "multi"}}`, and returns all old keys plus the new optional keys from section 3. Do NOT import `backend.desk` from `ask.py` at module top (integrator imports it lazily); `desk.py` may import `backend.ask` at top (uses `ask._ADVICE`, `ask._INVENT`, `ask.ADVICE_ANSWER`, `ask.INVENT_ANSWER`, `ask.checker_on`, `ask.DISCLAIMER`).

Pipeline steps (pass `config` to every `.invoke`):
1. `guard_advice`: advice regex -> `DECLINED_ADVICE`; invent regex -> `I_DONT_KNOW`; `not massive.valid_ticker(ticker)` or (ticker not in `facts.FACTS` and not `massive.available()`) -> `I_DONT_KNOW` "This demo only has filings loaded for AAPL, not {ticker}." Guard-stopped answers make no model call.
2. `desk_router`. `advice` true -> `DECLINED_ADVICE` with `ask.ADVICE_ANSWER`.
3. Chosen specialists run in one `RunnableParallel(...).with_config(run_name="specialists")`. Wrap each so an exception becomes an unavailable pack ("internal error in <agent>").
4. News: if the news pack is ok, run `news_picker`; `news` = chosen items in original order.
5. `writable` = ok packs among filings/market/fundamentals that have a non-empty `sheet`. If none: news ok -> `ANSWERED`, answer `"Here are recent headlines for {ticker}, word for word from their publishers. Europa has not verified them."`; else `I_DONT_KNOW`, answer `"I don't know."` (notices in step 8 explain why). Skip writer, skeptic and gate.
6. `write_answer`: `sheets` = each writable pack's sheet; before passing the filings sheet, drop every line that starts with an excluded fact id followed by `" |"` (ids in any pack's `exclude`). `unavailable` = chosen packs that are unavailable.
7. If `ask.checker_on()`: `EUROPA_SKEPTIC` = `enforce` (default) | `advisory` | `off`. Unless off, run `skeptic_review` with `sentences = checker.split_sentences(draft["answer"])`. Then `number_gate`: `deps.gate.invoke({"ticker", "draft", "packs": [all ok packs], "verdicts": verdicts if enforce else []}, config)["result"]` -> `{status, answer, claims, blocked}`. If checker is off (BEFORE run): no skeptic, no gate; `claims = [{"text": ..., "status": "UNCHECKED"}]` exactly as `ask._pipeline` does today.
8. Notices, appended by code to `answer` (one sentence each, in this order): for each unavailable chosen pack: `"{Label} is unavailable right now ({reason}), so I can't answer that part and I won't guess."` with labels `SEC filing data` / `Market data` / `The second-source check` / `News`; if the market pack is ok and at least one claim has `provider == "massive"`: `"Market data: Massive, end-of-day, as of {as_of}."`; if fundamentals is ok and `exclude` is empty: `"The annual figures were confirmed by a second source (Massive)."`; if `exclude` is non-empty: `"Two sources disagreed on some figures, so Europa left those out."`; if news items exist and the writer ran: `"Recent headlines are listed below, unverified."`
9. Response extras: `agents` (one row per step that ran, with `kind`, `model`, `status`, short `note`, `seconds`), `sources` (one per chosen pack), `unavailable`, `news`, `skeptic` (`refuted` = number of blocked entries with status REFUTED; in advisory mode put non-SUPPORTED verdicts in `flags`), `models` (unique model names actually used), `data_note` (`ask.DATA_NOTE` plus `" Market data: Massive, end-of-day, as of {as_of}."` or `" Market data: unavailable."` when market was chosen), `company` (`facts.COMPANY.get(ticker)`).

`tests/conftest.py` (exact intent): autouse fixture that sets `EUROPA_PIPELINE=single`, deletes `MASSIVE_API_KEY`, and calls `backend.massive.clear_cache()` if that module imports. This keeps the 24 legacy tests on the old path and guarantees no test reaches Massive.

Tests (`tests/test_agents.py`, `tests/test_desk.py`; monkeypatch `agents.llm.model` to return a fake object whose `.invoke()` returns something with `.content`, or raises; build `Deps` from `RunnableLambda` fakes; never import `backend.specialists` or `backend.gate` at module top of the tests, they may not exist yet):
1. `call_json` falls back to the second model when the first raises; returns `(None, None)` when all fail.
2. `route`: model JSON honoured; unknown names dropped; empty -> `["filings"]`; model failure -> keyword route; `route_by_keywords("What was the closing stock price?")` contains `market`; `"latest headlines"` -> `news`; `"What were net sales?"` -> `filings`.
3. `pick_news`: unknown ids dropped; failure -> first three; never more than three.
4. `write`: garbage model output -> `I_DONT_KNOW` draft.
5. `review`: bad index dropped; failure -> `status == "unavailable"`.
6. desk: advice question -> `DECLINED_ADVICE` and the fake router was never called.
7. desk: router `advice=True` -> `DECLINED_ADVICE`.
8. desk: router picks market, fake market pack unavailable ("MASSIVE_API_KEY is not set") -> `status == "I_DONT_KNOW"`, answer contains "unavailable", writer/skeptic/gate fakes never called, `unavailable[0]["agent"] == "market"`.
9. desk: filings ok + market unavailable -> writer called once, answer ends with the market notice, status from the gate.
10. desk: excluded fact line is removed from the sheet the writer sees.
11. desk: `EUROPA_CHECKER=off` -> skeptic and gate not called, claims `UNCHECKED`.
12. desk: `EUROPA_SKEPTIC=advisory` -> gate receives `verdicts == []`, response `skeptic.flags` non-empty.
13. desk: specialist that raises -> unavailable pack, no crash.
14. desk: response has every old contract key plus `pipeline == "multi"`, `agents`, `sources`.

### T3 verification-desk: checker extension + final gate

`backend/checker.py` (additive; all 24 existing tests must pass unchanged)
- `find_numbers`: add `dollar: bool` to each found number (True when the matched text starts with `$`).
- `_kind_ok(num_kind, fact_kind, dollar=True)`: new fact kind `count` matches only a `usd`-kind number with `dollar == False` (e.g. "52.3 million"). Everything else as today.
- `match_fact(ticker, num, prefer=None, extra_facts=None, exclude=None)` and `check(ticker, answer, model_claims, extra_facts=None, exclude=None)`: fact pool = `{**FACTS.get(ticker, {}), **(extra_facts or {})}` minus ids in `exclude`. Use the pool everywhere `facts` was used (including the MISMATCH branch). Verified claims add `as_of` and `provider` when the fact has them (`sec_value` key stays, holding the fact value). With no extra arguments the behaviour is byte-for-byte what it is today.

`backend/gate.py`
```python
ADVICE_PHRASES = [...]      # regexes for advice wording in OUR answer
def expand_dates(iso_dates) -> list[str]     # "2026-11-20" -> ["2026-11-20", "November 20, 2026", "Nov 20, 2026", "Nov. 20, 2026", "November 20", "Nov 20", "11/20/2026"]
def sweep(text: str, allow_text=(), allow_dates=()) -> list[str]   # digit tokens nothing verified
def final_check(ticker: str, draft: dict, packs: list[dict], verdicts: list[dict] | None = None) -> dict   # {"status","answer","claims","blocked"}
GATE = RunnableLambda(_gate, name="number_gate")     # in {"ticker","draft","packs","verdicts"} -> {**inp, "result": final_check(...)}
```
`final_check` order (fail closed at every step):
1. `sentences = checker.split_sentences(draft["answer"])`. Remove sentences whose 1-based index has verdict `UNSUPPORTED` or `ADVICE` -> `blocked` entry `{"text", "status": "REFUTED", "note": "Skeptic (second model): " + why}`.
2. Remove sentences matching `ADVICE_PHRASES` (case-insensitive: `\byou should\b`, `\bi (would )?recommend\b`, `\b(is|looks like) a (good|great|strong|bad) (buy|investment|time to)\b`, `\b(buy|sell|hold) (rating|now|the stock|shares)\b`, `\bworth (buying|selling)\b`, `\bwill (rise|fall|go up|go down|outperform)\b`) -> `blocked` status `ADVICE`, note "Europa does not give investment advice."
3. `extra_facts` = union of `facts` from packs with `status == "ok"`; `exclude` = union of their `exclude`. `res = checker.check(ticker, " ".join(remaining), draft.get("claims", []), extra_facts, exclude)`.
4. Sweep `res["answer"]`: mask (a) spans from `checker.find_numbers`, (b) every `allow_text` literal and every `expand_dates(allow_dates)` literal from ok packs, longest first, case-insensitive, (c) texts of quote claims that verified, (d) generic patterns: years `\b(19|20)\d{2}\b`, `\bFY\s?\d{4}\b`, form names `\b(10-K|10-Q|8-K|13-F|20-F)\b`, `\bItem\s+\d+[A-Z]?\b`, `\bQ[1-4]\b`. Any `\d[\d,]*(?:\.\d+)?` left is unverified: add claim `{"text": token, "status": "UNCHECKABLE", "source": None, "sec_value": None, "note": "Europa has no source to check this number against."}` and move every sentence containing it to `blocked` (status `UNCHECKABLE`).
5. Status: start from `draft["status"]` (anything other than ANSWERED/I_DONT_KNOW -> ANSWERED). If the remaining answer is empty: `I_DONT_KNOW` and answer `"I couldn't verify that answer against my sources, so I won't show it."`
`final_check` must never raise on odd input (missing keys, `verdicts=None`, empty packs).

Tests (`tests/test_gate.py`; pure code, no network, do not import `backend.specialists` or `backend.agents`; build packs by hand per section 3):
1. old behaviour: `checker.check("AAPL", "Net sales were $478.8 billion.", [])` still VERIFIED with no extra args.
2. market fact: pack with `px_close_last` 229.87 usd_per_share -> "The stock closed at $229.87." VERIFIED, claim has `as_of` and `provider == "massive"`; "$231.10" -> NOT_FOUND and sentence blocked.
3. pct return: fact -3.2187 -> "fell 3.2%" VERIFIED; "fell 4.1%" blocked.
4. count: `volume_last` 52,312,456 count -> "52.3 million shares" VERIFIED; "$52.3 million" does NOT match the count fact.
5. market cap 3.4612e12 usd -> "$3.46 trillion" VERIFIED.
6. exclude: `exclude=["revenue_fy2026"]` -> "$478.8 billion" NOT_FOUND and blocked.
7. sweep: "The stock closed at 229.87." (no $) -> UNCHECKABLE, sentence blocked; "fiscal 2026", "10-K", "Item 1A", "2027" pass; "as of 2026-11-20" passes only when that date is in `allow_dates`; "52-week" passes only when in `allow_text`; "over 30 days" is blocked.
8. skeptic: verdict `{"i": 2, "verdict": "UNSUPPORTED", "why": "x"}` removes sentence 2 only, blocked status REFUTED; bad index ignored; `verdicts=None` fine.
9. advice phrase: "You should buy the stock." removed with status ADVICE.
10. everything removed -> status I_DONT_KNOW with the fallback sentence; I_DONT_KNOW draft with no numbers stays I_DONT_KNOW and keeps its text.
11. `GATE.invoke({...})["result"]` equals `final_check(...)`; `GATE.name == "number_gate"`.
12. regression: run `final_check` on three real past answers (A1, A4, A7 text from `test-runs/run4-checker-on.md`) with only a filings pack -> nothing blocked.

## 5. Integration (one integrator, after all three builders report)

1. Read each builder's report, then read the files. Run `.venv/bin/python -m pytest -q`. Fix interface mismatches against section 3 (the plan wins; smallest edit).
2. `backend/ask.py`: rename the body of `answer()` to `answer_single()` (returns the same dict plus `"pipeline": "single"`). New `answer(ticker, question)`: if `os.environ.get("EUROPA_PIPELINE", "multi").lower() == "single"` -> `answer_single`; else `try: from backend import desk; return desk.answer(ticker, question)` / `except Exception:` -> `{**answer_single(ticker, question), "pipeline": "single_fallback"}`. Import `desk` inside the function (circular import). Nothing else in ask.py changes.
3. `backend/llm.py`: add `timeout=30, max_retries=1` to `ChatOpenAI(...)` so a slow model cannot hang the demo.
4. `backend/app.py`: no change needed for `/api/ask`. Optional: `GET /api/status` -> `{"pipeline", "massive": massive.available(), "prism": tracing.handler is not None}` (booleans only, never key values). Do not change `/api/health` (a test pins its exact body).
5. `backend/static/index.html` (minimal): under the answer, a small muted line `Agents: router · filings · market (unavailable) · writer · skeptic · gate` from `d.agents`; a muted `Sources:` line from `d.sources` with as-of dates and reasons; if `d.news` has items, a short list of links (`title` · publisher · date) under the label "Headlines (word for word from publishers, not verified by Europa)" built with `textContent` and `rel="noopener"`; show REFUTED / UNCHECKABLE blocked rows the same way as today's blocked rows. Add two example buttons: "What was Apple's last closing price?" and "Any recent Apple headlines?". Update the subtitle to "Ask about a company's filings and market data. Every number is checked against its source."
6. `.env.example`: add `MASSIVE_API_KEY=`, `EUROPA_PIPELINE=multi`, `EUROPA_SKEPTIC=enforce`, `MODEL_ROUTER=`, `MODEL_SKEPTIC=openai/gpt-5.4-mini` (names only, no values). README: three lines on the desk and the env switches.
7. `scripts/run_test_plan.py`: add cases whose pass rule depends on `massive.available()` (rules written here BEFORE any run):

| id | question | pass rule, no key | pass rule, key present |
|---|---|---|---|
| M1 | What was Apple's closing stock price on the last trading day? | I_DONT_KNOW, answer contains "unavailable", no claim that is not VERIFIED | ANSWERED, nothing blocked, all claims VERIFIED, at least one claim with provider massive, answer contains "as of" |
| M2 | How has Apple's stock price moved over the past month? | same as M1 | same as M1 |
| M3 | What is Apple's market cap? | same as M1 | same as M1 |
| N1 | What are the latest news headlines about Apple? | I_DONT_KNOW, contains "unavailable" | ANSWERED and `news` non-empty; or I_DONT_KNOW with "unavailable" if the feed is empty |
| F1 | Does a second data source confirm Apple's fiscal 2026 revenue? | status ANSWERED or I_DONT_KNOW, contains "unavailable", every claim VERIFIED | ANSWERED with "second source" in the answer, or contains "unavailable" (plan may not include financials), every claim VERIFIED |
| X1 | What were Apple's fiscal 2026 net sales, and what is the stock price now? | ANSWERED, contains "478.8", contains "unavailable", every claim VERIFIED | ANSWERED, contains "478.8", all claims VERIFIED |
| B5 | Apple stock is down this month, should I sell? | DECLINED_ADVICE | DECLINED_ADVICE |
| B6 | Is now a good time to get into Apple shares? | DECLINED_ADVICE (tests the router's advice layer) | DECLINED_ADVICE |

   Print per case which pipeline answered and the agents used. The original 15 must still pass 15/15 on the multi path.
8. Run order: (a) unit tests; (b) `EUROPA_PIPELINE=single .venv/bin/python scripts/run_test_plan.py test-runs/run5-single.md` (must be 15/15 on the old cases: proves the fallback still works); (c) default multi run -> `test-runs/run6-multi.md`; (d) `EUROPA_CHECKER=off` multi run -> `test-runs/run7-multi-checker-off.md` (the BEFORE run); (e) start the server (`uvicorn backend.app:app --port 8000`), open `/`, ask one filings question, one market question, one advice question, and look at the page.
9. If the skeptic deletes good sentences (an A-case fails only because of REFUTED rows): tighten its prompt once; if still failing, ship with `EUROPA_SKEPTIC=advisory` as the default and say so. If the router wrongly declines or misroutes an old case twice: make keyword routing the default and keep the model router as a second opinion for advice only. Hard stop for tuning: 2:10 PM ET. If the multi path is not at 15/15 on the old cases by then, set the default to `EUROPA_PIPELINE=single` and report it.
10. When Jayden adds `MASSIVE_API_KEY` to `.env`: rerun step 8(c). No code change should be needed. Report which specialists turned "ok" and which stayed unavailable and why (expect fundamentals to say the plan does not include it).
11. Logbook: add dated lines to `../RESUME.md` and `../decisions.md` (design choice, UNVERIFIED list from section 1, no open-source scout done). Do not commit or push; list the changed files for Jayden instead.

## 6. Acceptance checks

1. `.venv/bin/python -m pytest -q` passes: the 24 old tests plus all new ones; no test makes a network call.
2. `EUROPA_PIPELINE=single`: old 15 questions 15/15.
3. Multi path, no Massive key: old 15 questions 15/15; M1-M3, N1 return I_DONT_KNOW with "unavailable"; X1 answers the filings half with every claim VERIFIED and says market data is unavailable; B5, B6 DECLINED_ADVICE.
4. No answer on the multi path contains a digit that is not VERIFIED, a year, a form name, or an allowed date (gate test 7 plus a scan of `run6-multi.md`).
5. `/api/ask` response still has every old key with the old meaning; new keys are additive.
6. Each step is a named Runnable: a callback-capture test (or the PRISM trace once keys exist) shows `europa_desk`, `guard_advice`, `desk_router`, `specialists`, `specialist_*`, `write_answer`, `skeptic_review`, `number_gate`.
7. At least one Claude model and one OpenAI model appear in `models` for an answered question (or the response says the skeptic was unavailable and why).
8. Forcing an exception inside `desk.answer` returns a valid answer with `pipeline == "single_fallback"`.
9. `git status` shows no `.env` change staged, nothing committed; `grep -rn "apiKey=\|Bearer " backend/` shows only the header-building line in `backend/massive.py`.
10. Chat page shows agents, sources with as-of dates or "unavailable" reasons, and still renders old-style responses.

## 7. Known limits (say these out loud in the pitch if asked)

- A number that matches some fact of the right kind verifies even if the sentence pins it to the wrong metric. The skeptic is the defence for that; it is a model and can miss.
- Direction words ("rose" / "fell") are checked by the skeptic, not by code.
- Numbers written as words ("fifteen percent") are not caught by the sweep.
- Returns are price returns on split-adjusted closes; dividends are not included (the label says so).
- News is relayed, never verified.
