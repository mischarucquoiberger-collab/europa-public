import { ProviderError, type Trace } from "./trace";

export type Earnings = {
  ticker?: string;
  fiscal_year: number;
  fiscal_quarter: number;
  period_end: string;
  revenue?: number;
  diluted_earnings_per_share?: number;
  filing_url?: string;
  source: "Massive" | "SEC EDGAR";
};

type SecFact = { start?: string; end: string; val: number; accn?: string; fy?: number; fp?: string; form?: string; filed?: string; frame?: string };
type FactTag = { units: Record<string, SecFact[]> };
type CompanyFacts = { cik: string; facts: { "us-gaap": Record<string, FactTag> } };
type MassiveRow = {
  tickers?: string[];
  fiscal_year?: number;
  fiscal_quarter?: number;
  period_end?: string;
  filing_date?: string;
  timeframe?: string;
  revenue?: number;
  diluted_earnings_per_share?: number;
};

const secHeaders = {
  "User-Agent": process.env.SEC_USER_AGENT || "EUROPA/1.0 earnings research contact: contact@example.com",
  Accept: "application/json",
};

async function secJson<T>(trace: Trace, spanName: string, url: string, ticker: string): Promise<T> {
  return trace.step(spanName, {
    "gen_ai.operation.name": "execute_tool",
    "gen_ai.tool.name": spanName.toLowerCase().replaceAll(/[^a-z0-9]+/g, "_"),
    "server.address": new URL(url).host,
    "gen_ai.tool.call.arguments": JSON.stringify({ ticker, path: new URL(url).pathname }),
  }, async (annotate) => {
    const response = await fetch(url, {
      headers: secHeaders,
      next: { revalidate: 21_600 },
      signal: AbortSignal.timeout(12_000),
    });
    annotate({ "http.response.status_code": response.status });
    if (!response.ok) throw new ProviderError("SEC EDGAR", response.status);
    const result = await response.json() as T;
    annotate({ "gen_ai.tool.call.result": "SEC filing facts retrieved" });
    return result;
  });
}

function accessionUrl(cik: string, accn: string) {
  return `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${accn.replaceAll("-", "")}/${accn}-index.htm`;
}

function isQuarterDuration(start: string | undefined, end: string) {
  if (!start) return false;
  const startTime = Date.parse(`${start}T00:00:00Z`);
  const endTime = Date.parse(`${end}T00:00:00Z`);
  const days = Math.round((endTime - startTime) / 86_400_000) + 1;
  return days >= 75 && days <= 105;
}

function secQuarterlyFacts(facts: CompanyFacts, ticker: string): Earnings[] {
  const gaap = facts.facts["us-gaap"];
  const revenueFacts = gaap.RevenueFromContractWithCustomerExcludingAssessedTax?.units.USD ?? gaap.Revenues?.units.USD ?? gaap.SalesRevenueNet?.units.USD ?? [];
  const epsFacts = gaap.EarningsPerShareDiluted?.units["USD/shares"] ?? [];
  const rows = new Map<string, { row: Earnings; filed: string }>();
  for (const revenueFact of revenueFacts) {
    if (!isQuarterDuration(revenueFact.start, revenueFact.end) || !revenueFact.accn || revenueFact.form !== "10-Q") continue;
    const report = revenueFacts.filter((fact) => fact.start === revenueFact.start && fact.end === revenueFact.end && fact.form === "10-Q" && fact.fy && /^Q[1-4]$/.test(fact.fp ?? "")).sort((a, b) => (a.accn ?? "").localeCompare(b.accn ?? ""))[0] ?? revenueFact;
    if (!report.fy || !/^Q[1-4]$/.test(report.fp ?? "")) continue;
    const eps = epsFacts.filter((fact) => fact.start === report.start && fact.end === report.end && fact.form === "10-Q" && fact.accn === report.accn).sort((a, b) => (b.filed ?? "").localeCompare(a.filed ?? ""))[0];
    const month = Number(report.end.slice(5, 7));
    const row: Earnings = {
      ticker,
      fiscal_year: report.fy!,
      fiscal_quarter: Number(report.fp?.slice(1)),
      period_end: report.end,
      revenue: report.val,
      ...(eps ? { diluted_earnings_per_share: eps.val } : {}),
      filing_url: accessionUrl(facts.cik, report.accn!),
      source: "SEC EDGAR",
    };
    // Preserve SEC's reported fiscal quarter (not the calendar quarter); month only validates exact duration.
    if (month >= 1 && month <= 12) {
      const key = `${row.fiscal_year}-${row.fiscal_quarter}-${row.period_end}`;
      const current = rows.get(key);
      if (!current || (report.filed ?? "") > current.filed) rows.set(key, { row, filed: report.filed ?? "" });
    }
  }
  return [...rows.values()].map(({row})=>row).sort((a, b) => b.period_end.localeCompare(a.period_end)).slice(0, 8);
}

function massiveRows(rows: MassiveRow[], ticker: string): Earnings[] {
  return rows.filter((row) => row.timeframe === "quarterly" && row.tickers?.some((item) => item.toUpperCase() === ticker.toUpperCase()))
    .filter((row) => Number.isInteger(row.fiscal_year) && Number.isInteger(row.fiscal_quarter) && Number(row.fiscal_quarter) >= 1 && Number(row.fiscal_quarter) <= 4 && /^\d{4}-\d{2}-\d{2}$/.test(row.period_end ?? ""))
    .map((row) => ({
      ticker,
      fiscal_year: row.fiscal_year!,
      fiscal_quarter: row.fiscal_quarter!,
      period_end: row.period_end!,
      // Massive returns 0 for unreported concepts as well; keep those unavailable.
      ...(typeof row.revenue === "number" && row.revenue !== 0 ? { revenue: row.revenue } : {}),
      ...(typeof row.diluted_earnings_per_share === "number" && row.diluted_earnings_per_share !== 0 ? { diluted_earnings_per_share: row.diluted_earnings_per_share } : {}),
      ...(row.filing_date ? { filing_url: `https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(ticker)}&forms=10-Q%252C10-K` } : {}),
      source: "Massive" as const,
    }))
    .sort((a, b) => b.period_end.localeCompare(a.period_end)).slice(0, 8);
}

export async function earnings(trace: Trace, ticker: string): Promise<Earnings[]> {
  let massive: Earnings[] = [];
  try {
    const rows = await trace.step("Massive · income_statements", {
      "gen_ai.operation.name": "execute_tool",
      "gen_ai.tool.name": "massive.income_statements",
      "server.address": "api.massive.com",
      "gen_ai.tool.call.arguments": JSON.stringify({ path: "/stocks/financials/v1/income-statements", tickers: ticker, timeframe: "quarterly", sort: "period_end.desc", limit: "50" }),
    }, async (annotate) => {
      const key = process.env.MASSIVE_API_KEY;
      if (!key) throw new Error("Massive is not configured");
      const url = new URL("/stocks/financials/v1/income-statements", "https://api.massive.com");
      url.search = new URLSearchParams({ tickers: ticker, timeframe: "quarterly", sort: "period_end.desc", limit: "50" }).toString();
      const response = await fetch(url, { headers: { Authorization: `Bearer ${key}` }, next: { revalidate: 1800 }, signal: AbortSignal.timeout(9000) });
      annotate({ "http.response.status_code": response.status });
      if (!response.ok) throw new ProviderError("Massive", response.status);
      const body = await response.json() as { status?: string; results?: MassiveRow[] };
      if (body.status !== "OK") throw new ProviderError("Massive", 502);
      annotate({ "gen_ai.tool.call.result": JSON.stringify({ count: body.results?.length ?? 0 }) });
      return Array.isArray(body.results) ? body.results : [];
    });
    massive = massiveRows(rows, ticker);
  } catch {
    // Entitlement errors (e.g. 403) are expected on plans without the expansion.
  }
  // Follow the fallback path if Massive denies access or has no usable quarterly results.
  if (massive.length) return massive;
  try {
    const listing = await secJson<Record<string, { cik_str: number; ticker: string; title: string }>>(
      trace, "SEC EDGAR · ticker_to_cik", "https://www.sec.gov/files/company_tickers.json", ticker,
    );
    const entry = Object.values(listing).find((item) => item.ticker.toUpperCase() === ticker.toUpperCase());
    if (!entry) return [];
    const cik = String(entry.cik_str).padStart(10, "0");
    const facts = await secJson<CompanyFacts>(trace, "SEC EDGAR · company_facts", `https://data.sec.gov/api/xbrl/companyfacts/CIK${cik}.json`, ticker);
    return secQuarterlyFacts(facts, ticker);
  } catch {
    return [];
  }
}
