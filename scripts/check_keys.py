"""Check that every key in .env is present and works. Prints names and results only, never a value.

    python3 scripts/check_keys.py            # everything except the model call
    python3 scripts/check_keys.py --model    # also one tiny model call (spends a few tokens)
"""
import datetime
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402  (loads .env)

MASSIVE = "https://api.massive.com"


def present(name):
    try:
        return bool(config.secret(name))
    except Exception:
        return False


def get(url, headers, timeout=20):
    """(status, parsed json or None). Never raises, never prints the request."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, None
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except Exception:
            return error.code, None
    except Exception as error:
        return f"no answer ({type(error).__name__})", None


def massive_checks():
    key = config.secret("MASSIVE_API_KEY")
    today = datetime.date.today()
    day = lambda years: (today - datetime.timedelta(days=365 * years)).isoformat()
    probes = [
        ("company details", "/v3/reference/tickers/AAPL", {}),
        ("previous close", "/v2/aggs/ticker/AAPL/prev", {}),
        ("daily bars, last 30 days", f"/v2/aggs/ticker/AAPL/range/1/day/{day(0)[:8]}01/{today.isoformat()}", {"limit": 5}),
        ("daily bars, 4 years back", f"/v2/aggs/ticker/AAPL/range/1/day/{day(4)}/{(today - datetime.timedelta(days=365 * 4 - 10)).isoformat()}", {"limit": 5}),
        ("daily bars, 8 years back", f"/v2/aggs/ticker/AAPL/range/1/day/{day(8)}/{(today - datetime.timedelta(days=365 * 8 - 10)).isoformat()}", {"limit": 5}),
        ("related companies", "/v1/related-companies/AAPL", {}),
        ("news", "/v2/reference/news", {"ticker": "AAPL", "limit": 1}),
        ("dividends", "/stocks/v1/dividends", {"ticker": "AAPL", "limit": 1}),
        ("income statements", "/stocks/financials/v1/income-statements", {"tickers": "AAPL", "limit": 1}),
        ("last quote", "/v2/last/nbbo/AAPL", {}),
        ("class share written BRK.B", "/v3/reference/tickers/BRK.B", {}),
    ]
    # how the key is sent: a header keeps it out of URLs and logs
    status, _ = get(MASSIVE + "/v3/reference/tickers/AAPL", {"Authorization": f"Bearer {key}"})
    by_header = status == 200
    print(f"  key accepted in a header: {'yes' if by_header else 'no (' + str(status) + ')'}")
    for label, path, params in probes:
        query = dict(params)
        headers = {"Authorization": f"Bearer {key}"} if by_header else {}
        if not by_header:
            query["apiKey"] = key
        url = MASSIVE + path + ("?" + urllib.parse.urlencode(query) if query else "")
        status, data = get(url, headers)
        detail = ""
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                detail = f"{len(results)} row(s)"
            elif isinstance(results, dict):
                detail = "1 record"
            if status != 200:
                detail = str(data.get("message") or data.get("error") or data.get("status") or "")[:90]
        print(f"  {label:28s} {status}  {detail}")


def sec_checks():
    agent = config.secret("SEC_USER_AGENT")
    shaped = bool(re.search(r"\S+\s+\S*[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", agent))
    print(f"  contact line has a name and an email-shaped address: {'yes' if shaped else 'NO'}")
    if not shaped:
        return
    headers = {"User-Agent": agent, "Accept-Encoding": "identity"}
    status, data = get("https://www.sec.gov/files/company_tickers.json", headers)
    print(f"  ticker list                  {status}  {len(data) if isinstance(data, dict) else ''} companies")
    status, data = get("https://data.sec.gov/submissions/CIK0000320193.json", headers)
    recent = (data or {}).get("filings", {}).get("recent", {}).get("form", []) if isinstance(data, dict) else []
    print(f"  filings index (one company)  {status}  {len(recent)} recent filings")
    status, data = get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", headers)
    tags = len((data or {}).get("facts", {}).get("us-gaap", {})) if isinstance(data, dict) else 0
    print(f"  reported figures             {status}  {tags} us-gaap tags")


def main():
    print("Keys present (names only):")
    for name in ("NICRRON_API_KEY", "PRISMTRACE_API_KEY", "PRISMTRACE_PROJECT_ID", "MASSIVE_API_KEY", "SEC_USER_AGENT"):
        print(f"  {name:24s} {'filled' if present(name) else 'EMPTY'}")
    if present("MASSIVE_API_KEY"):
        print("Massive:")
        massive_checks()
    if present("SEC_USER_AGENT"):
        print("SEC EDGAR:")
        sec_checks()
    if "--model" in sys.argv:
        import llm
        import prism
        print("Model (one tiny call through call_llm):")
        try:
            reply = llm.call_llm([{"role": "user", "content": "Reply with the single word: ready"}],
                                 session_id="setup-check", max_tokens=8)
            prism.flush()
            print(f"  answered: {reply.strip()[:40]!r}")
        except Exception as error:
            print(f"  FAILED: {type(error).__name__}: {str(error)[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
