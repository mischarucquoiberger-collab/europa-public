# What Changed: rules for any AI agent in this repo (Money Talks #3, Sat 2026-11-21)

Product: type a ticker → what changed between a company's latest SEC filing and the one before. Every number and quote is checked against the SEC source before it is shown. Track: Money Intelligence. Submit by 4:15 PM ET.

- **API contract is fixed** (`POST /api/compare`, `POST /api/ask`, shapes in `backend/app.py`). The Ninoo front end depends on it. Change it only after telling the team.
- **All model calls go through `backend/llm.py`** (Nicrron API, required by the rules). No direct OpenAI/Anthropic calls.
- **PRISM traces are required.** Every agent step (fetch, compare, check, write) should appear as its own step. Follow the PRISM setup brief for the SDK.
- **Checker statuses:** VERIFIED (show) · MISMATCH / NOT_FOUND (block) · UNCHECKABLE (block, say why). Fail closed.
- **Never** put keys in code, commits, logs or chat. Keys live in `.env` (gitignored). Stage files by name, never `git add -A`.
- Public SEC data or clearly labeled synthetic data only. No personal investment advice: decline "should I buy/sell".
- One owner per file (see team plan). Don't edit another person's files.
