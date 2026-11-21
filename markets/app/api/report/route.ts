import { linksOnly, news, validTicker } from "@/lib/massive";
import { earnings } from "@/lib/earnings";
import { ProviderError, traced } from "@/lib/trace";

/**
 * The quick brief. This route only gathers the evidence (headlines from Massive and
 * reported quarters from SEC EDGAR) and hands it to the project's Python backend,
 * which makes the model call through call_llm() and traces a redacted copy itself.
 * No model provider is called from here and no model key is read by this app.
 */
const backendOrigin = () => (process.env.BACKEND_ORIGIN || "http://127.0.0.1:8130").replace(/\/+$/, "");

type Brief = { summary?: unknown; model?: unknown; withheld?: unknown; checked?: unknown; detail?: unknown };

class BackendUnreachable extends Error {}
class BackendRefused extends Error {
  constructor(readonly status: number, readonly detail: string) { super(detail); }
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const ticker = typeof body?.ticker === "string" ? body.ticker.trim().toUpperCase() : "";
  if (!validTicker(ticker) || ticker.startsWith("I:")) return Response.json({ error: "Enter a stock ticker such as MSFT." }, { status: 400 });
  if (!process.env.MASSIVE_API_KEY) return Response.json({ error: "Market data is unavailable right now, so there is no evidence to brief from." }, { status: 503 });
  try {
    return await traced("Company report", async (trace) => {
      const [headlines, financials] = await Promise.allSettled([news(trace, ticker), earnings(trace, ticker)]);
      const articles = headlines.status === "fulfilled" ? linksOnly(headlines.value).slice(0, 5) : [];
      // Only quarters a filing reports; a derived fourth quarter is left out of the evidence.
      const statements = financials.status === "fulfilled" ? financials.value.filter((row) => !row.derived).slice(0, 4) : [];
      if (!articles.length && !statements.length) {
        return Response.json({ error: "No source data was available for that ticker." }, { status: 422 });
      }
      const evidence = {
        ticker,
        headlines: articles.map((a, i) => ({
          source: `N${i + 1}`, title: a.title, date: a.published_utc,
          publisher: a.publisher?.name ?? "", description: a.description?.slice(0, 400) ?? "",
        })),
        quarters: statements.map((row) => ({
          fiscal_year: row.fiscal_year, fiscal_quarter: row.fiscal_quarter, period_end: row.period_end,
          revenue: row.revenue ?? null, diluted_eps: row.diluted_earnings_per_share ?? null,
          filing_url: row.filing_url ?? null, source: row.source,
        })),
      };
      const address = `${backendOrigin()}/api/brief`;
      // The trace records the operation, the address and the status code only: no prompt, no reply.
      const brief = await trace.step("Backend · brief", {
        "gen_ai.operation.name": "invoke_agent", "server.address": address,
      }, async (annotate) => {
        let response: Response;
        try {
          response = await fetch(address, {
            method: "POST", cache: "no-store", signal: AbortSignal.timeout(60_000),
            headers: { "Content-Type": "application/json" }, body: JSON.stringify(evidence),
          });
        } catch {
          throw new BackendUnreachable("backend not reachable");
        }
        annotate({ "http.response.status_code": response.status });
        const data = await response.json().catch(() => null) as Brief | null;
        if (!response.ok) throw new BackendRefused(response.status, typeof data?.detail === "string" ? data.detail : "");
        if (typeof data?.summary !== "string" || !data.summary.trim()) throw new ProviderError("Backend", 502);
        return { summary: data.summary, model: typeof data.model === "string" ? data.model : "" };
      });
      return Response.json({
        ...brief, ticker, traceId: trace.traceId,
        sources: [
          ...articles.map((a, i) => ({ label: `N${i + 1}`, title: a.title, url: a.article_url })),
          ...statements.map((statement, i) => ({ label: `F${i + 1}`, title: `Q${statement.fiscal_quarter} FY${statement.fiscal_year} filing (${statement.source})`, url: statement.filing_url ?? "" })).filter((source) => source.url),
        ],
      });
    });
  } catch (error) {
    if (error instanceof BackendUnreachable) {
      return Response.json({ error: "The brief service is not reachable right now. The research backend needs to be running; try again in a moment." }, { status: 503 });
    }
    if (error instanceof BackendRefused) {
      const reason = error.detail ? `: ${error.detail}` : ".";
      return Response.json({ error: `The brief could not be written${reason}` }, { status: [400, 422, 503].includes(error.status) ? error.status : 502 });
    }
    return Response.json({ error: "The brief couldn’t be generated. Try again in a moment." }, { status: 502 });
  }
}
