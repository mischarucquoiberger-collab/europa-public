import { bars, ipos, linksOnly, news, validTicker, volatilityBars } from "@/lib/massive";
import { earnings } from "@/lib/earnings";
import { ProviderError, traced } from "@/lib/trace";

/** "plan": the symbol or endpoint is outside this project's Massive plan; "unavailable": the source failed. */
type Unavailable = "plan" | "unavailable";
const messages: Record<Unavailable, string> = {
  plan: "Not available on this data plan",
  unavailable: "Market data is unavailable right now",
};
const reasonFor = (error: unknown): Unavailable =>
  error instanceof ProviderError && (error.status === 401 || error.status === 403) ? "plan" : "unavailable";
const failure = (reason: Unavailable) =>
  Response.json({ error: messages[reason], reason }, { status: reason === "plan" ? 403 : 502 });

export async function GET(req: Request) {
  const params = new URL(req.url).searchParams;
  const ticker = (params.get("ticker") ?? "I:SPX").toUpperCase();
  const section = params.get("section") ?? "chart";
  const range = params.get("range") ?? "1M";
  const periods: Record<string, number> = { "1W": 7, "1M": 30, "3M": 90, "1Y": 365 };
  if (!validTicker(ticker) || !Object.hasOwn(periods, range) || !["chart", "feed", "earnings", "watchlist", "news", "volatility"].includes(section)) {
    return Response.json({ error: "Choose a valid ticker and range." }, { status: 400 });
  }
  // Without a key there is no market data at all: say so, never draw stand-in figures.
  if (section !== "earnings" && !process.env.MASSIVE_API_KEY) return failure("unavailable");
  try {
    return await traced(`Market · ${section}`, async (trace) => {
      if (section === "earnings") return Response.json({ earnings: await earnings(trace, ticker) });
      if (section === "feed") return Response.json({ ipos: await ipos(trace) });
      if (section === "watchlist") {
        const symbols = ["SPY", "QQQ", "IWM", "I:SPX", "I:NDX", "I:VIX"];
        const results = await Promise.allSettled(symbols.map((symbol) => bars(trace, symbol, 14)));
        return Response.json({
          watchlist: Object.fromEntries(symbols.map((symbol, i) => {
            const result = results[i];
            return [symbol, result.status === "fulfilled" ? result.value : []];
          })),
          // Why a symbol has no bars, so each tile can say so plainly.
          missing: Object.fromEntries(symbols.flatMap((symbol, i) => {
            const result = results[i];
            return result.status === "rejected" ? [[symbol, reasonFor(result.reason)]] : [];
          })),
        });
      }
      if (section === "volatility") {
        const [vix, spx] = await Promise.allSettled([volatilityBars(trace, 30), bars(trace, "SPY", 30)]);
        if (vix.status === "rejected") throw vix.reason;
        return Response.json({ volatility: vix.value.points, volatilityTicker: vix.value.ticker, spx: spx.status === "fulfilled" ? spx.value : [] });
      }
      if (section === "news") return Response.json({ news: linksOnly(await news(trace, ticker)) });
      const points = await bars(trace, ticker, periods[range]);
      return Response.json({ points, actualTicker: ticker, currency: ticker.startsWith("I:") ? "PTS" : "USD" });
    });
  } catch (error) {
    return failure(reasonFor(error));
  }
}
