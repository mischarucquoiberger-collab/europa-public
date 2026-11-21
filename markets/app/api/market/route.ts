import { bars, ipos, linksOnly, news, validTicker, volatilityBars } from "@/lib/massive";
import { earnings } from "@/lib/earnings";
import { traced } from "@/lib/trace";

export async function GET(req: Request) {
  const params = new URL(req.url).searchParams;
  const ticker = (params.get("ticker") ?? "I:SPX").toUpperCase();
  const section = params.get("section") ?? "chart";
  const range = params.get("range") ?? "1M";
  const periods: Record<string, number> = { "1W": 7, "1M": 30, "3M": 90, "1Y": 365 };
  if (!validTicker(ticker) || !Object.hasOwn(periods, range) || !["chart", "feed", "earnings", "watchlist", "news", "volatility"].includes(section)) {
    return Response.json({ error: "Choose a valid ticker and range." }, { status: 400 });
  }
  if (section !== "earnings" && !process.env.MASSIVE_API_KEY) return Response.json({ mode: "sample" });
  try {
    return await traced(`Market · ${section}`, async (trace) => {
      if (section === "earnings") return Response.json({ earnings: await earnings(trace, ticker) });
      if (section === "feed") return Response.json({ mode: "market", ipos: await ipos(trace) });
      if (section === "watchlist") {
        const symbols = ["SPY", "QQQ", "IWM", "I:SPX", "I:NDX", "I:VIX"];
        const results = await Promise.allSettled(symbols.map((symbol) => bars(trace, symbol, 14)));
        return Response.json({ mode: "market", watchlist: Object.fromEntries(symbols.map((symbol, i) => {
          const result = results[i];
          return [symbol, result.status === "fulfilled" ? result.value : []];
        })) });
      }
      if (section === "volatility") {
        const [vix, spx] = await Promise.allSettled([volatilityBars(trace, 30), bars(trace, "SPY", 30)]);
        return Response.json({ mode: "market", volatility: vix.status === "fulfilled" ? vix.value.points : [], volatilityTicker: vix.status === "fulfilled" ? vix.value.ticker : null, spx: spx.status === "fulfilled" ? spx.value : [] });
      }
      if (section === "news") return Response.json({ mode: "market", news: linksOnly(await news(trace, ticker)) });
      const data = { points: await bars(trace, ticker, periods[range]), ticker };
      const actualTicker = data.ticker;
      return Response.json({ mode: "market", points: data.points, actualTicker, currency: actualTicker.startsWith("I:") ? "PTS" : "USD" });
    });
  } catch {
    return Response.json({ error: "Market data is currently unavailable. Check your Massive plan or try again." }, { status: 502 });
  }
}
