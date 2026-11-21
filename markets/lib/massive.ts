import { ProviderError, type Trace } from "./trace";

export type Point = { t: number; c: number; o?: number; h?: number; l?: number; v?: number };
export type Article = { image_url?: string; id: string; headline?:string; summary?:string; tickers?: string[]; title: string; article_url: string; published_utc: string; publisher?: { name: string }; description?: string };
export type Ipo = { ticker: string; issuer_name: string; listing_date?: string; primary_exchange?: string; final_issue_price?: number; ipo_status?: string };
export type Earnings = { fiscal_year: number; fiscal_quarter: number; period_end: string; revenue?: number; diluted_earnings_per_share?: number; ticker?: string };
type IncomeStatement = { ticker?: string; fiscal_year?: number; fiscal_period?: string; period_end?: string; revenues?: { value?: number }; revenue?: number; diluted_earnings_per_share?: { value?: number } | number; };
export const validTicker = (ticker: string) => /^(?:I:)?[A-Z0-9][A-Z0-9.-]{0,14}$/.test(ticker);
export const day = (offset = 0) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

async function get<T>(trace: Trace, operation: string, path: string, query: Record<string, string>, context: Record<string, string> = {}, singleton = false) {
  const key = process.env.MASSIVE_API_KEY;
  if (!key) throw new Error("Massive is not configured");
  return trace.step(`Massive · ${operation}`, {
    "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": `massive.${operation}`,
    "server.address": "api.massive.com", "gen_ai.tool.call.arguments": JSON.stringify({ path, ...query, ...context }),
  }, async (annotate) => {
    const url = new URL(path, "https://api.massive.com");
    url.search = new URLSearchParams(query).toString();
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${key}` }, next: { revalidate: 120 },
      signal: AbortSignal.timeout(9000),
    });
    annotate({ "http.response.status_code": res.status });
    if (!res.ok) throw new ProviderError("Massive", res.status);
    const body = await res.json() as { results?: T[] | T; status?: string; request_id?: string };
    if (body.status === "ERROR" || body.status === "NOT_AUTHORIZED") throw new ProviderError("Massive", 502);
    const results = Array.isArray(body.results) ? body.results : singleton && body.results ? [body.results] : [];
    annotate({ "gen_ai.tool.call.result": JSON.stringify({ count: results.length, requestId: body.request_id }) });
    return results;
  });
}
export const bars = (trace: Trace, ticker: string, days: number) =>
  get<Point>(trace, "daily_bars", `/v2/aggs/ticker/${encodeURIComponent(ticker)}/range/1/day/${day(-days)}/${day()}`, { sort: "asc", limit: "500", ...(ticker.startsWith("I:") ? {} : { adjusted: "true" }) }, { ticker });

// Massive's stocks aggregates endpoint does not cover all index tickers on every plan.
// VIXY is a Massive-covered volatility ETF and VXX is used as a fallback.
export const volatilityBars = async (trace: Trace, days: number) => {
  const primary = await Promise.allSettled([bars(trace, "I:VIX", days), bars(trace, "VIXY", days), bars(trace, "VXX", days)]);
  for (let i = 0; i < primary.length; i++) {
    const result = primary[i];
    if (result.status === "fulfilled" && result.value.length) {
      return { points: result.value, ticker: ["I:VIX", "VIXY", "VXX"][i] };
    }
  }
  throw new Error("No volatility index or proxy bars returned by Massive");
};
export const news = (trace: Trace, ticker: string) =>
  get<Article>(trace, "ticker_news", "/v2/reference/news", { ticker, limit: "6", sort: "published_utc", order: "desc" });
export const ipos = (trace: Trace) =>
  get<Ipo>(trace, "ipos", "/vX/reference/ipos", { "listing_date.gte": day(-30), "listing_date.lte": day(90), sort: "listing_date", order: "desc", limit: "12" });
export const earnings = async (trace: Trace, ticker: string): Promise<Earnings[]> => {
  const rows = await get<IncomeStatement>(trace, "income_statements", "/stocks/financials/v1/income-statements", {
    ticker, timeframe: "quarterly", order: "desc", sort: "period_end", limit: "8",
  });
  return rows.map((row) => {
    const fiscalPeriod = row.fiscal_period ?? (row as IncomeStatement & { fiscal_quarter?: number }).fiscal_quarter?.toString();
    const fiscalQuarter = Number(typeof fiscalPeriod === "string" ? fiscalPeriod.match(/Q?([1-4])/i)?.[1] : NaN);
    const fiscalYear = Number(row.fiscal_year);
    const rawRevenue = (row as IncomeStatement & { revenues?: number | { value?: number } }).revenues;
    const revenue = typeof rawRevenue === "number" ? rawRevenue : rawRevenue?.value ?? row.revenue;
    const eps = typeof row.diluted_earnings_per_share === "number" ? row.diluted_earnings_per_share : row.diluted_earnings_per_share?.value;
    return {
      ticker: row.ticker,
      fiscal_year: fiscalYear,
      fiscal_quarter: fiscalQuarter,
      period_end: row.period_end ?? "",
      ...(typeof revenue === "number" ? { revenue } : {}),
      ...(typeof eps === "number" ? { diluted_earnings_per_share: eps } : {}),
    };
  }).filter((row) => Number.isFinite(row.fiscal_year) && row.fiscal_year > 0 && Number.isFinite(row.fiscal_quarter) && row.fiscal_quarter >= 1 && row.fiscal_quarter <= 4);
};
export const linksOnly = (articles: Article[]) => articles.filter((a) => /^https?:\/\//i.test(a.article_url));

export type Instrument = { name: string; type?: string; currency_name?: string; primary_exchange?: string };
export async function instrument(trace: Trace, ticker: string) {
  const [detail] = await get<Instrument>(trace, "instrument", "/v3/reference/tickers/" + encodeURIComponent(ticker), {}, { ticker }, true);
  return detail;
}
export async function equityNews(trace: Trace, ticker?: string) {
  const items = await get<Article>(trace, "equity_news", "/v2/reference/news", {
    ...(ticker ? { ticker } : {}), limit: "50", sort: "published_utc", order: "desc",
  });
  const ids = new Set<string>(), urls = new Set<string>();
  return linksOnly(items).flatMap(item => {
    const symbols = [...new Set(item.tickers?.filter(t => validTicker(t) && !t.includes(":")))];
    if (!symbols.length || !item.title || !Date.parse(item.published_utc)) return [];
    const url = new URL(item.article_url);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) if (key.startsWith("utm_")) url.searchParams.delete(key);
    if (ids.has(item.id) || urls.has(url.href)) return [];
    if (item.id) ids.add(item.id);
    urls.add(url.href);
    return [{ ...item, tickers: symbols }];
  }).slice(0, 6);
}
