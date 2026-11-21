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
  /**
   * True for a fourth quarter worked out from the annual report: the full-year
   * revenue in the 10-K less the nine-month revenue in the third-quarter 10-Q.
   * A 10-K does not report the fourth quarter on its own, and EPS cannot be
   * subtracted that way (share counts differ), so a derived row has no EPS.
   */
  derived?: boolean;
};

type SecFact = { start?: string; end: string; val: number; accn?: string; fy?: number; fp?: string; form?: string; filed?: string };
type FactTag = { units: Record<string, SecFact[]> };
type CompanyFacts = { cik: string | number; facts: { "us-gaap"?: Record<string, FactTag> } };
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

/**
 * Total revenue tags, most preferred first. Companies move between these over the
 * years (NVIDIA files "Revenues" today but used the contract-revenue tag until 2022;
 * banks such as JPMorgan report "total net revenue" as RevenuesNetOfInterestExpense),
 * so each period takes the first tag that has a value for it instead of the first tag
 * the company has ever used.
 */
const revenueTags = [
  "Revenues",
  "RevenueFromContractWithCustomerExcludingAssessedTax",
  "RevenuesNetOfInterestExpense",
  "RevenueFromContractWithCustomerIncludingAssessedTax",
  "SalesRevenueNet",
];
const epsTags = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"];

async function secJson<T>(trace: Trace, spanName: string, url: string, ticker: string, cache: RequestInit & { next?: { revalidate: number } }): Promise<T> {
  return trace.step(spanName, {
    "gen_ai.operation.name": "execute_tool",
    "gen_ai.tool.name": spanName.toLowerCase().replaceAll(/[^a-z0-9]+/g, "_"),
    "server.address": new URL(url).host,
    "gen_ai.tool.call.arguments": JSON.stringify({ ticker, path: new URL(url).pathname }),
  }, async (annotate) => {
    const response = await fetch(url, { headers: secHeaders, ...cache, signal: AbortSignal.timeout(12_000) });
    annotate({ "http.response.status_code": response.status });
    if (!response.ok) throw new ProviderError("SEC EDGAR", response.status);
    const result = await response.json() as T;
    annotate({ "gen_ai.tool.call.result": "SEC filing facts retrieved" });
    return result;
  });
}

function accessionUrl(cik: string | number, accn: string) {
  return `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${accn.replaceAll("-", "")}/${accn}-index.htm`;
}

const dayMs = 86_400_000;
const time = (date: string) => Date.parse(`${date}T00:00:00Z`);
const length = (fact: SecFact) => fact.start ? Math.round((time(fact.end) - time(fact.start)) / dayMs) + 1 : 0;
const original = (a: SecFact, b: SecFact) => (a.filed ?? "").localeCompare(b.filed ?? "") || (a.accn ?? "").localeCompare(b.accn ?? "");

/**
 * Quarterly revenue and diluted EPS from a company's SEC XBRL facts.
 *
 * A filing also repeats earlier periods as comparatives, and each fact carries the
 * fiscal year and period of the FILING (not of the period it measures). So a quarter
 * is labelled only from the filing that reports it as its own period: the filing whose
 * latest period end is that quarter's end. Its fy/fp are the company's own fiscal
 * labels (NVIDIA's year ending January 2026 is FY2026; Target's is fiscal 2025).
 */
export function secQuarterlyFacts(facts: CompanyFacts, ticker: string): Earnings[] {
  const gaap = facts.facts["us-gaap"] ?? {};
  const usable = (fact: SecFact) => !!fact.start && !!fact.accn && !!fact.fy && !!fact.fp && (fact.form === "10-Q" || fact.form === "10-K") && Number.isFinite(fact.val);
  const revenue = revenueTags.map((tag) => (gaap[tag]?.units.USD ?? []).filter(usable));
  const eps = epsTags.map((tag) => (gaap[tag]?.units["USD/shares"] ?? []).filter(usable));

  // The period each filing reports on: the latest end date among its facts.
  const reportEnd = new Map<string, string>();
  for (const fact of [...revenue.flat(), ...eps.flat()]) {
    if ((reportEnd.get(fact.accn!) ?? "") < fact.end) reportEnd.set(fact.accn!, fact.end);
  }
  const ownPeriod = (fact: SecFact) => reportEnd.get(fact.accn!) === fact.end;

  /** First tag (by preference) with a value for this exact period in this filing. */
  function revenueIn(accn: string, start: string, end: string) {
    for (const list of revenue) {
      const fact = list.find((item) => item.accn === accn && item.start === start && item.end === end);
      if (fact) return fact.val;
    }
    return undefined;
  }
  function epsIn(accn: string, start: string, end: string) {
    for (const list of eps) {
      const fact = list.find((item) => item.accn === accn && item.start === start && item.end === end);
      if (fact) return fact.val;
    }
    return undefined;
  }

  // Each quarter, from the original 10-Q that reports it as its own period.
  const quarters = new Map<string, { row: Earnings; start: string; accn: string }>();
  for (const list of revenue) {
    for (const fact of [...list].sort(original)) {
      const days = length(fact);
      if (fact.form !== "10-Q" || !/^Q[1-3]$/.test(fact.fp!) || days < 75 || days > 120 || !ownPeriod(fact)) continue;
      const key = fact.end;
      if (quarters.has(key)) continue; // an earlier filing or a preferred tag already gave this quarter
      const dilutedEps = epsIn(fact.accn!, fact.start!, fact.end);
      quarters.set(key, {
        start: fact.start!, accn: fact.accn!,
        row: {
          ticker,
          fiscal_year: fact.fy!,
          fiscal_quarter: Number(fact.fp!.slice(1)),
          period_end: fact.end,
          revenue: revenueIn(fact.accn!, fact.start!, fact.end),
          ...(dilutedEps === undefined ? {} : { diluted_earnings_per_share: dilutedEps }),
          filing_url: accessionUrl(facts.cik, fact.accn!),
          source: "SEC EDGAR",
        },
      });
    }
  }

  // Fourth quarters: the 10-K's full year less the nine months in that year's Q3 10-Q.
  const derived: Earnings[] = [];
  const annuals = new Map<number, SecFact>();
  for (const list of revenue) {
    for (const fact of [...list].sort(original)) {
      const days = length(fact);
      if (fact.form === "10-K" && fact.fp === "FY" && days >= 350 && days <= 380 && ownPeriod(fact) && !annuals.has(fact.fy!)) annuals.set(fact.fy!, fact);
    }
  }
  for (const [year, annual] of annuals) {
    const third = [...quarters.values()].find(({ row }) => row.fiscal_year === year && row.fiscal_quarter === 3);
    if (!third || third.row.period_end >= annual.end) continue;
    const fullYear = revenueIn(annual.accn!, annual.start!, annual.end);
    const nineMonths = revenueIn(third.accn, annual.start!, third.row.period_end);
    if (fullYear === undefined || nineMonths === undefined || fullYear - nineMonths <= 0) continue;
    if (quarters.has(annual.end)) continue;
    derived.push({
      ticker,
      fiscal_year: year,
      fiscal_quarter: 4,
      period_end: annual.end,
      revenue: fullYear - nineMonths,
      filing_url: accessionUrl(facts.cik, annual.accn!),
      source: "SEC EDGAR",
      derived: true,
    });
  }

  return [...[...quarters.values()].map(({ row }) => row), ...derived]
    .filter((row) => row.revenue !== undefined || row.diluted_earnings_per_share !== undefined)
    .sort((a, b) => b.period_end.localeCompare(a.period_end))
    .slice(0, 8);
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
      // Massive gives no accession number, so there is no exact filing to link to.
      source: "Massive" as const,
    }))
    .sort((a, b) => b.period_end.localeCompare(a.period_end)).slice(0, 8);
}

// SEC company facts run 1–8 MB, over the 2 MB limit of Next's fetch cache, so the
// computed quarters are kept here instead (per server process, for six hours).
const secCache = new Map<string, { at: number; rows: Earnings[] }>();
const SEC_TTL = 6 * 3_600_000;

async function secEarnings(trace: Trace, ticker: string): Promise<Earnings[]> {
  const cached = secCache.get(ticker);
  if (cached && Date.now() - cached.at < SEC_TTL) return cached.rows;
  const listing = await secJson<Record<string, { cik_str: number; ticker: string; title: string }>>(
    trace, "SEC EDGAR · ticker_to_cik", "https://www.sec.gov/files/company_tickers.json", ticker, { next: { revalidate: 86_400 } },
  );
  const entry = Object.values(listing).find((item) => item.ticker.toUpperCase() === ticker.toUpperCase());
  if (!entry) return [];
  const cik = String(entry.cik_str).padStart(10, "0");
  const facts = await secJson<CompanyFacts>(trace, "SEC EDGAR · company_facts", `https://data.sec.gov/api/xbrl/companyfacts/CIK${cik}.json`, ticker, { cache: "no-store" });
  const rows = secQuarterlyFacts(facts, ticker);
  secCache.set(ticker, { at: Date.now(), rows });
  return rows;
}

async function massiveEarnings(trace: Trace, ticker: string): Promise<Earnings[]> {
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
  return massiveRows(rows, ticker);
}

/**
 * Latest quarters for a U.S. filer. SEC EDGAR comes first: it is the filing of record,
 * it is free, and each row links to the exact filing. Massive's fundamentals endpoint
 * is not on this project's plan; it is only tried when EDGAR has nothing usable.
 * Throws when every source failed, so callers can tell "unavailable" from "none".
 */
export async function earnings(trace: Trace, ticker: string): Promise<Earnings[]> {
  let failure: unknown = null;
  try {
    const rows = await secEarnings(trace, ticker);
    if (rows.length) return rows;
  } catch (error) {
    failure = error;
  }
  try {
    return await massiveEarnings(trace, ticker);
  } catch {
    // Massive's fundamentals are not on this plan, so a refusal here is expected. If EDGAR
    // answered (with no quarters: a fund, a foreign filer, an unknown symbol) the honest
    // result is "none"; if EDGAR itself failed, report the source as unavailable.
    if (failure) throw failure;
    return [];
  }
}
