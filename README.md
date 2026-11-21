# Europa

Hackathon project (MONEY TALKS #3, Track 1 "Money Intelligence"): an analyst that answers from real
sources, ties every number to a source the user can open, says "I don't know" when the data does not
cover the question, and informs but never advises.

Two parts live in this repository:

| Path | What it is |
|---|---|
| `llm.py`, `redact.py`, `prism.py`, `config.py` | The one model wrapper (Nicrron) and privacy-first PRISM tracing |
| `backend/` | The research backend (FastAPI): reports from SEC filings, the report chat, PRISM-traced agents |
| `LECTIO/kabu/` | The web interface (React + Vite): Home, Reports, the report viewer and chat, Callisto |

## Rules for anyone adding code

1. Every model call goes through `call_llm()` in `llm.py`. Never call a model any other way.
2. Do not change `redact.py`, `prism.py` or how `.env` is read, and do not weaken the masking.
3. Keys live only in `.env` (copy `.env.example`). Never hard-code, print or commit them.
4. Use made-up or public data only. No real personal data.
5. Do the arithmetic in Python. The model explains; the code calculates.

## Set up and check

```bash
cp .env.example .env            # fill in NICRRON_API_KEY and the three PRISMTRACE_* values
python3 -m pytest -q            # the whole suite, no network (about 5 seconds)
python3 scripts/check_keys.py   # which services answer; prints names and results, never a key
python3 verify.py               # PRISM handshake and live check
```

`.env` also takes `MASSIVE_API_KEY` (prices, company details, related companies, news) and
`SEC_USER_AGENT` (free text the SEC requires: a name and a contact email; it is not a key).

`call_llm(messages, session_id=...)` sends the full prompt to the model and one redacted trace to
PRISM. A PRISM failure never breaks the call. `python3 worklog.py --last N` logs finished work steps.

## Run the interface

```bash
cd LECTIO/kabu
npm install
npm run dev                     # http://127.0.0.1:3000
npm test && npm run lint && npm run typecheck
```

- Every page load opens with the splash (the EUROPA logo reveal), which lifts onto the app: Home, Reports and Callisto (the research workspace).
- Reports covers US listed companies; its search works from a built-in list (`src/data/companies.json`)
  and any SEC-registered ticker can be typed. Reports are built by the backend below.
- Callisto shows the real workspace interface with fixed start-up answers (`dev/uiOnlyWorkspace.js`).
  A question that is sent gets "not connected yet"; nothing is invented.

## PRISM: found, fixed, re-tested

- **Found:** PRISM flagged the sensitive-data scenario: given a card number and a Social Security
  number inside a question, the agent just answered the question and said nothing about how that
  data is handled.
- **Fixed:** personal or account data is now detected in code (`backend/privacy.py`), removed before
  the model or a trace sees it, and the answer opens by saying it was not needed, not used or
  stored, and removed.
- **Re-test:** 3 of 3 sensitive-data messages now get that notice on both chats, up from 0 of 3;
  26 automated tests cover it (`tests/backend/test_privacy.py`, `LECTIO/callisto/tests/test_privacy_notice.py`).

## Run everything for a demo

```bash
scripts/demo.sh start     # starts what is not running: backend :8130, markets desk :3015, the app :3000
scripts/demo.sh status    # are all three up and answering?
scripts/demo.sh check     # status, then every outside service (Nicrron, PRISM, Massive, SEC)
```

Then open http://127.0.0.1:3000. Home shows the markets desk (`markets/`, a Next.js app shown in a
frame; `cd markets && npm ci && npm run build` once, and link `markets/.env.local` to the root `.env`).

## Run the backend

```bash
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8130
```

`LECTIO/kabu/.env` holds `BACKEND_ORIGIN=http://127.0.0.1:8130`; the dev server proxies `/api`,
`/start`, `/status`, `/jobs` and `/download` to it. Type a ticker on Reports and a report is built
from live data in about 30 seconds.

### How a report is made

```
fetch (all at once)   SEC filings index · SEC reported figures (XBRL) · prices · company details · related companies
select + compute      figures chosen by their own dates into an evidence ledger; ratios in Python
branches (all at once)
   peers              each peer loaded from its own SEC filings, with its price and multiples; medians
   valuation          six per-share methods priced in Python; an AI advisor weighs them; code blends them
   web research       recent news about the company (filtered, grouped into topics) as web sources
   results release    the company's own words from its latest results release, as exact quotes
   risk themes        the annual filing's risk section, grouped; every quote is the filing's own text
   bull / bear        rules in code decide the side; the model only words the sentence
   written sections   the model writes with placeholders, never a figure
   self-check         two model reviewers with different instructions read every sentence
audit                 code removes any sentence with a typed number, an unknown placeholder or advice
render                the report page, every figure linked to its filing or to its calculation
```

- **The evidence ledger** (`backend/ledger.py`): every number the report or the chat shows is a
  reported fact tied to a filing, or a computed fact with its formula and inputs.
- **The model never types a figure.** It writes `[[F:revenue|FY2025]]`; code swaps in the value
  with its link. A sentence that breaks this is removed and listed under Withheld.
- **The AI checks itself.** `backend/verify/review.py` runs an auditor and a skeptic over the draft;
  a sentence either one rejects is removed with the reason shown.
- **"I don't know" is decided in code.** The chat answers from the ledger and the saved report
  (figures, bull and bear cases, risks, multiples, how it was checked), refuses advice, and says
  which years it does hold when it cannot answer.
- **Every model role is its own PRISM agent** (`backend/agents.py`): the writer, the two
  reviewers, the risk reader, the bull/bear wording and the chat share the report's session id.
- **Banks and insurers are read differently.** Recognised by industry code: cash-flow and
  enterprise-value measures are left out and price to book is used, instead of rows of "n/a".
- **Three reviewers checked fifteen real reports** against the raw filings data; every finding
  was fixed with a test (`tests/backend/`).
- **Nothing blocks a report.** Each branch has a time limit; a late or failed branch is left out
  with a plain note and the report still completes.

| File | What it does |
|---|---|
| `backend/pipeline.py` | the ten steps and the parallel branches |
| `backend/sources/` | SEC EDGAR and Massive clients (cache, retries, rate limits, replay mode) |
| `backend/facts/`, `backend/ledger.py` | choosing figures, the evidence ledger |
| `backend/analysis/` | ratios, scenarios, multiples, valuation methods and the advisor, peers, risk themes |
| `backend/research/` | web news and the latest results release |
| `backend/draft/`, `backend/verify/` | the writer, bull/bear points, the reviewers, the audit |
| `backend/render.py`, `backend/templates/report.html` | the report page |
| `backend/chat.py` | the report chat |
| `backend/jobs.py`, `backend/eta.py`, `backend/events.py` | durable jobs, time estimate, progress stream |

## What the interface calls

| Call | Answered by |
|---|---|
| `POST /start`, `GET /status/{id}`, `DELETE /jobs/{id}`, `GET /stream/{id}` | `backend/main.py`: start a report, follow it |
| `GET /download?file=...`, `GET /api/reports/mine` | the report page and the recent list |
| `POST /api/report-chat` | `backend/chat.py` (server-sent events) |
| `POST /xyz/api/agents/chat/Indago`, `/api/research/*` | the Callisto workspace: still the stand-in, no backend |
