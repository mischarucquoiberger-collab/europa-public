import { CountValue } from "@/app/count-value";
import { notFound } from "next/navigation";
import { bars, equityNews, instrument, validTicker } from "@/lib/massive";
import { earnings } from "@/lib/earnings";
import { traced, ProviderError } from "@/lib/trace";
import { Briefing } from "../../briefing";
import {Suspense} from "react";
import Link from "next/link";
import { TickerSearch } from "../../search";
import "../../closing-sheet.css";
import SessionChart from "./session-chart";
import { NewsSkeleton } from "../../skeletons";

export const dynamic = "force-dynamic";
export default async function StockPage({ params }: { params: Promise<{ticker:string}> }) {
  const ticker = (await params).ticker.toUpperCase().replace(/^I%3A/, "I:");
  if (!validTicker(ticker)) notFound();
  const data = await traced("Stock page · "+ticker, async trace => {
    const detail = await instrument(trace,ticker).catch(error => error instanceof ProviderError && error.status === 404 ? null : undefined);
    if (detail === null) return null;
    const fund = ["ETF","ETN","FUND"].includes(detail?.type ?? "");
    const index = ticker.startsWith("I:");
    const [points, stories, filings] = await Promise.all([
      bars(trace,ticker,365).catch(()=>[]), equityNews(trace,ticker).catch(()=>null),
      fund || index ? null : earnings(trace,ticker).catch(()=>null)
    ]);
    return { detail, fund, index, points, stories, filings, traceId: trace.traceId };
  });
  const mast = <div className="paper-mast ticker-mast"><Link href="/" aria-label="Back to markets">← Markets</Link></div>;
  if (!data) return <main className="shell closing-sheet stock-page">{mast}<h1>Symbol unavailable</h1><p>Massive has no instrument record for {ticker}.</p></main>;
  const { points, detail } = data;
  const last = points.at(-1), previous = points.at(-2);
  const change = last && previous ? last.c - previous.c : null;
  return <main className="shell closing-sheet stock-page" data-trace-id={data.traceId}>{mast}
    <header><small>{ticker} · {data.index ? "Index" : detail?.type} {detail?.primary_exchange}</small><h1>{detail?.name ?? ticker}</h1>
    {last && <><div className="close-price"><CountValue text={last.c.toFixed(2)}/> <small>{data.index ? "points" : detail?.currency_name?.toUpperCase() ?? "USD"}</small></div>
    <p>{change !== null && previous?.c ? (change>=0?"+":"")+change.toFixed(2)+" ("+(100*change/previous.c).toFixed(2)+"%) · " : ""}Massive daily close · As of {new Date(last.t).toISOString().slice(0,10)}</p></>}</header>
    <SessionChart points={points} units={data.index?"pts":detail?.currency_name?.toUpperCase()??"USD"}/>
    <Suspense fallback={<NewsSkeleton title={ticker+" news"}/>}><Briefing newspaper title={ticker+" news"} stories={data.stories}/></Suspense>
    {!data.fund && !data.index && <section className="earnings"><h2>Quarterly earnings</h2>{data.filings?.length ? <div className="filings-scroll"><table><thead><tr><th>Fiscal quarter</th><th>Period end</th><th>Revenue (USD)</th><th>Diluted EPS (USD)</th><th>Source</th></tr></thead><tbody>{data.filings.map(row=><tr key={row.period_end}><th scope="row">Q{row.fiscal_quarter} FY{row.fiscal_year}</th><td>{row.period_end}</td><td><CountValue text={row.revenue?.toLocaleString("en-US") ?? "Unavailable"}/></td><td><CountValue text={row.diluted_earnings_per_share?.toFixed(2) ?? "Unavailable"}/></td><td>{row.filing_url ? <a href={row.filing_url}>{row.source}</a> : row.source}</td></tr>)}</tbody></table></div> : <p>No quarterly earnings available.</p>}</section>}
  </main>;
}
