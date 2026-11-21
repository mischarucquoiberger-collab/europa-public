# Europa / Callisto: integration guide (for merging into the main site)

Europa is a **feature**: ask a question about a company's SEC filings and get an answer where every number
was checked against the SEC source before it is shown. It runs as a small HTTP service (Python, FastAPI).
The main site calls it over HTTP, so the main site can be in any language.

Written 2026-11-21. Response example below is a real reply from the running service (trimmed).

## 1. Run it (5 minutes)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in your own keys (never commit .env)
.venv/bin/uvicorn backend.app:app --port 8000
```
- Required in `.env`: `NICRRON_API_KEY`, your own Nicrron key (all model calls go through Nicrron; `NICRRON_BASE_URL` has a default). Without it the service still starts, but every real question answers "I couldn't produce a checked answer to that." If you see that sentence, check the key first.
- Optional: `PRISMTRACE_*` (traces to PRISM; without them it runs and says tracing is off),
  `MASSIVE_API_KEY` (stock price, market data, news; without it those parts say "unavailable").
- Every other line in `.env.example` (`MODEL_*`, `EUROPA_*`, `SEC_USER_AGENT`) can stay as it is.
- Port 8000 is only an example: change `--port` if the main site already uses it.
- Tested on a fresh clone with Python 3.14.4 on macOS (2026-11-21). Tests: `.venv/bin/python -m pytest -q` passed, no key needed.
- Health check: `GET /api/health` → `{"ok": true}`. Switches on: `GET /api/status` → `{"pipeline": "multi", "massive": false, "prism": false}` (no key values; it does not show whether the Nicrron key is set).
- CORS is open (`*`), so a browser front end on another address can call it directly.
- Quick test with no model call: `curl -s -X POST http://127.0.0.1:8000/api/ask -H "Content-Type: application/json" -d '{"ticker":"AAPL","question":"Should I buy Apple stock?"}'` → `"status": "DECLINED_ADVICE"`. Then ask a real question to test the key.

## 2. The one call the main site needs
`POST /api/ask` with JSON `{"ticker": "AAPL", "question": "How much did R&D spending grow?"}`. Both fields are required (a missing one returns http 422).

Optional third field for chat memory: `"last_question"`, the previous question the user asked in this chat (send `""` or leave it out at the start). With it, a follow-up such as "and Microsoft?" or "what about over 5 years?" is rewritten by code into a full question before it is answered. Also send the `ticker` from the last reply, so "what about last year?" stays on the same stock.

Reply (trimmed):
```json
{
  "status": "ANSWERED",
  "answer": "Research and development expense rose to $45.8 billion in fiscal 2026 from $34.6 billion in fiscal 2025. That is an increase of $11.2 billion, or +32.5%.",
  "claims": [
    {"text": "$45.8 billion", "status": "VERIFIED",
     "source": "Apple 10-K FY2026 (SEC XBRL): Research and development expense, fiscal 2026",
     "sec_value": 45765000000.0, "fact_id": "rnd_fy2026"}
  ],
  "blocked": [],
  "company": "Apple Inc.",
  "checker": "on",
  "seconds": 2.47,
  "data_note": "Data: Apple 10-K fiscal 2026 vs fiscal 2025, public SEC filings.",
  "disclaimer": "Research aid, not investment advice.",
  "agents": [{"name": "guard_advice", "kind": "code", "model": null, "status": "ok", "note": "passed", "seconds": 0.0}],
  "models": ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "openai/gpt-5.4-mini"],
  "sources": [{"name": "SEC EDGAR 10-K (XBRL facts and filing text)", "status": "ok"}],
  "news": [], "unavailable": [], "prism_session_id": "ask-<session-id>"
}
```

The real reply also has `pipeline` and `skeptic` (safe to ignore). What to show in the UI:
| Field | Show it as |
|---|---|
| `answer` | The main text. Already safe: anything unchecked was removed before this point. |
| `status` | `ANSWERED`; `I_DONT_KNOW` (no checked data for that question: the `answer` then says what to ask or where to look); `DECLINED_ADVICE` ("should I buy?": no buy or sell call, but the `answer` is a full checked summary plus things to weigh, so show it like any answer). |
| `claims[]` | Hover or footnote per number: `text`, `status` (`VERIFIED`), `source`. |
| `blocked[]` | Optional "removed because unverified" list (sentence `text`, `status`, `note`). Good for showing the checker works. |
| `disclaimer`, `data_note` | Small print under the answer. Keep the disclaimer visible. |
| `agents[]` | Optional "how this answer was made" steps (name, model, seconds). |
| `news[]` | Headlines (title, publisher, published_utc, url, summary), word for word, not verified. `summary` is the news feed's own article summary (may be empty). Show it under a clear label such as "As reported, not checked": its numbers are NOT checked. |
| `charts[]` | Present when the question asks for a chart or graph, and added automatically (a price line) for price-move questions such as "how has Tesla done this year" or "what happened to Nvidia yesterday". Each item: `type` (`line`, `bar` or `none`), `title`, `unit` (`usd_price`, `usd`, `usd_per_share`, `pct`), `points` (`[{x, y}]`), `source`; for `none`, a `note` instead of points. Data comes straight from SEC facts or Massive closes, never from a model. Reference drawing code (plain SVG, no library): `drawChart` in `backend/static/index.html`. |
| `ticker` | The stock Europa actually answered about. A company named in the question ("nvidia", "$TSLA", "eli lilly") wins over the `ticker` you sent, so the box is optional: send `AAPL` or the last ticker as a fallback, then show this field. |
| `stats[]` | Key-number tiles for the header, on `ANSWERED` and `DECLINED_ADVICE` replies when market data exists. Up to 6 items: `label` (Price, Day change, Past year, Market cap, 52-week range, Below 52-week high, Dividend yield), `value` (ready-to-show text), `note`, `fact_id`. Built by code from the same Massive facts the checker uses. May be missing: draw nothing then. |
| `followups[]` | Up to 3 suggested next questions (plain strings), built by code from what was just asked. Never an advice or prediction question. Draw them as buttons that send the text as the next question. May be missing. |
| `kind: "compare"` | "Compare Apple and Microsoft" returns `status: "ANSWERED"`, `kind: "compare"`, `tickers: [..]` and two blocks of source figures printed by code (no model). `claims` is empty on purpose: do not show a "numbers checked" badge on it; label it "source figures". |
| `status: "CHAT"` | New status. Greetings, "what are you", "how do you check numbers", plain term definitions ("what is an ETF?"), off-topic and similar get a fixed reply written in code (no model, no data figures). `answer` is the text, `kind` names the reply, `claims` and `blocked` are empty. Show it as a plain chat bubble with no checked badge. |

Answers take about 2 to 15 seconds (up to about 20 for a first-time "should I buy" on another ticker). Show a loading state.

Layout of `answer`: plain text with single line breaks (`\n`), the same shape for every data answer. Draw it line by line (or with CSS `white-space: pre-line`):
1. first line: the one-line lead;
2. lines starting with `• `: stat bullets;
3. lines starting with a label: `Strengths:`, `Watch-outs:`, `What it means:`, `Deeper read:`, `Bear case:`, `Bull case:`, `To weigh:`;
4. on "should I buy" answers, a line starting `In the news` followed by `• ` headline lines (publisher headlines, word for word, not checked);
5. last lines: fixed "how to decide" guidance and small source notes (`Market data: ...`).

Short replies (one or two sentences, and every `CHAT` reply) have no line breaks. `renderAnswer` in `backend/static/index.html` is a working reference (lead, bullet list, bold labels, "How to decide" box, small notes).

Questions the desk handles (any wording): filing figures and risk factors (Apple), price, returns, 52-week range and distance from it, market cap, dividends and yield, "what happened / why did it move" (checked move plus reported headlines), bear case / bull case / pros and cons, charts ("6 month chart", "graph revenue"), valuation, safety, analyst and earnings-date questions (checked facts plus where to look).

Other addresses: `POST /api/chat` accepts `{"message": "..."}` or OpenAI-style `{"messages": [...]}`
(ticker optional, default AAPL; same pipeline, adds `reply`). `GET /` serves a simple test chat page.
`POST /api/compare` still returns **FAKE placeholder data** (`fake_data: true`). Do not use it in the product.

## 3. Limits to know before the demo
- Filing figures (sales, profit, margins, risk factors) are loaded for **Apple (AAPL)** only, fiscal 2025 vs 2026 (`backend/facts.py`). Any other real ticker is answered from checked Massive market data (price, returns, 52-week range, market cap, dividends) and says so. An unknown ticker gets "could not find a stock with the ticker ...".
- Not on the current Massive plan: other companies' financial statements and analyst ratings. No P/E ratio yet.
- Prices come from one source (Massive) and are not cross-checked against a second one.
- Market data is end-of-day (Massive), not live.
- Not investment advice: the service refuses buy/sell questions on purpose.
- Synthetic test material is labeled SYNTHETIC (`scripts/demo_synthetic_wrong_number.py`).

## 4. Files that matter
| File | What it does |
|---|---|
| `backend/app.py` | The HTTP addresses above |
| `backend/desk.py` | The agent pipeline: guard → router → specialists → writer → skeptic → number gate → notices |
| `backend/checker.py`, `backend/gate.py` | The number checker (pure code, fails closed) |
| `backend/facts.py`, `backend/data/` | SEC facts and filing text |
| `backend/llm.py` | All model calls (Nicrron) |
| `backend/tracing.py` | PRISM traces |
| `tests/` | `.venv/bin/python -m pytest -q` |

## 5. Merging options (pick one with the team)
1. **Run it as its own service** (fastest, nothing to rewrite): deploy this folder, point the main site at its
   `/api/ask`. Recommended for today.
2. **Copy the folder into the main repo** as a sub-folder and run it next to the main backend.
3. **Port the logic** into the main backend's language: only worth it after the event.

Updates: newer versions (3-model council, more checker fixes) will be pushed to this same repo; this guide matches the commit that adds `last_question`, `followups` and the line layout (Nov 21, 2026). The `/api/ask`
request and the fields above stay the same; new fields may be added.
