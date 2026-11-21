"use client";

import Watchlist from "./watchlist";
import { CountValue } from "@/app/count-value";
import { CalendarDays, ChevronDown, Newspaper } from "lucide-react";
import { useEffect, useState } from "react";
import type { Article, Ipo, Point } from "@/lib/massive";
import type { Earnings } from "@/lib/earnings";
import {PricePlot} from "./price-plot";
import Performance from "./performance";
import Technicals from "./technicals";
import { ChartSkeleton, HeadlineSkeleton, RowSkeleton } from "./skeletons";
import { StockLink } from "./stock-news";
import "./closing-sheet.css";
import { ReportLinks, Wordmark } from "./masthead";

const instruments = [
  { ticker: "SPY", code: "SPY", name: "S&P 500 ETF", detail: "SPDR S&P 500 ETF Trust" },
  { ticker: "QQQ", code: "QQQ", name: "Nasdaq 100 ETF", detail: "Invesco QQQ Trust" },
  { ticker: "IWM", code: "IWM", name: "Russell 2000 ETF", detail: "iShares Russell 2000 ETF" },
  { ticker: "I:SPX", code: "SPX", name: "S&P 500 Index", detail: "S&P 500 Index" },
  { ticker: "I:NDX", code: "NDX", name: "Nasdaq 100 Index", detail: "Nasdaq 100 Index" },
  { ticker: "I:VIX", code: "VIX", name: "Volatility Index", detail: "Cboe Volatility Index" },
];
const ranges = ["1W", "1M", "3M", "1Y"];

const format = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shortDate = (s: string) => new Date(s.length === 10 ? s + "T12:00:00Z" : s).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
export const PLAN_MESSAGE = "Not available on this data plan";
export const DOWN_MESSAGE = "Market data is unavailable right now";

/** A failed /api/market call, carrying the plain message the panel should show. */
class MarketError extends Error {
  constructor(readonly reason: "plan" | "unavailable") { super(reason === "plan" ? PLAN_MESSAGE : DOWN_MESSAGE); }
}
async function market(query: string, signal: AbortSignal) {
  const response = await fetch(`/api/market?${query}`, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new MarketError(body?.reason === "plan" ? "plan" : "unavailable");
  }
  return response.json();
}
const messageOf = (error: unknown) => error instanceof MarketError ? error.message : DOWN_MESSAGE;

export default function Desk({ briefing }: { briefing: React.ReactNode }) {
  const [selected, setSelected] = useState(0);
  const [pinned, setPinned] = useState<number | null>(null);
  const [recentOpen,setRecentOpen]=useState(false);
  const [range, setRange] = useState("1M");
  // `points` are kept while a new range/ticker loads so the chart never blanks out;
  // `loading` dims the panel instead. `ready` stays false only until the first load.
  const [series, setSeries] = useState<{ points: Point[]; error?: string; ready?: boolean; loading?: boolean; actualTicker?: string; currency?: string }>({ points: [], loading: true });
  const [watchlist, setWatchlist] = useState<Record<string, Point[]> | null>(null);
  // Why a tile has no bars: "plan" (outside the Massive plan) or "unavailable" (the source failed).
  const [missing, setMissing] = useState<Record<string, "plan" | "unavailable">>({});
  const [volatility, setVolatility] = useState<{ points: Point[]; ticker: string; error?: string } | null>(null);
  const [allListings, setAllListings] = useState(false);
  const [feed, setFeed] = useState<{ ipos: Ipo[] | null; error?: string } | null>(null);
  const [ticker, setTicker] = useState("MSFT");
  const [rows, setRows] = useState<Earnings[] | null | undefined>(undefined);
  const [rowsError, setRowsError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    market("section=earnings&ticker=" + encodeURIComponent(ticker), controller.signal)
      .then(data => { if (!controller.signal.aborted) setRows(Array.isArray(data.earnings) ? data.earnings : null); })
      .catch((error) => { if (!controller.signal.aborted) { setRowsError(error instanceof MarketError && error.reason === "plan" ? PLAN_MESSAGE : "Earnings data is unavailable right now"); setRows(null); } });
    return () => controller.abort();
  }, [ticker]);
  const [activeNews, setActiveNews] = useState(false);
  const [headlines, setHeadlines] = useState<Article[] | string | null>(null);
  const instrument = instruments[selected];
  const previewTicker = instrument.ticker === "I:SPX" && watchlist && !watchlist[instrument.ticker]?.length ? "SPY" : instrument.ticker === "I:VIX" ? volatility?.ticker ?? instrument.ticker : instrument.ticker;
  const previewName = previewTicker === instrument.ticker ? instrument.detail : previewTicker+" ETF · "+instrument.code+" proxy";
  useEffect(() => {
    const controller = new AbortController();
    market("section=feed", controller.signal).then((data) => {
      setFeed({ ipos: Array.isArray(data.ipos) ? data.ipos : null });
    }).catch((error) => { if (!controller.signal.aborted) setFeed({ ipos: null, error: error instanceof MarketError && error.reason === "plan" ? PLAN_MESSAGE : "IPO data is unavailable right now" }); });
    market("section=watchlist", controller.signal).then((data) => {
      setWatchlist(data.watchlist ?? {});
      setMissing(data.missing ?? {});
    }).catch((error) => {
      if (controller.signal.aborted) return;
      setWatchlist({});
      setMissing(Object.fromEntries(instruments.map((item) => [item.ticker, error instanceof MarketError ? error.reason : "unavailable"])));
    });
    market("section=volatility", controller.signal).then((data) => {
      if (!controller.signal.aborted) setVolatility({ points: data.volatility ?? [], ticker: data.volatilityTicker ?? "I:VIX" });
    }).catch((error) => { if (!controller.signal.aborted) setVolatility({ points: [], ticker: "I:VIX", error: messageOf(error) }); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setSeries((old) => ({ ...old, loading: true, error: undefined }));
    setPinned(null);
    market(`section=chart&ticker=${encodeURIComponent(previewTicker)}&range=${range}`, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setSeries({ points: data.points ?? [], ready: true, loading: false, actualTicker: data.actualTicker ?? previewTicker, currency: data.currency ?? (previewTicker.startsWith("I:") ? "PTS" : "USD") });
    }).catch((error) => { if (!controller.signal.aborted) setSeries({ points: [], error: messageOf(error), ready: true, loading: false }); });
    return () => controller.abort();
  }, [previewTicker, instrument.ticker, range, selected]);
  useEffect(() => {
    if (!activeNews) return;
    const controller = new AbortController();
    market(`section=news&ticker=${encodeURIComponent(previewTicker)}`, controller.signal).then((data) => setHeadlines(data.news ?? [])).catch((error) => {
      if (!controller.signal.aborted) setHeadlines(error instanceof MarketError && error.reason === "plan" ? PLAN_MESSAGE : "Headlines are unavailable right now.");
    });
    return () => controller.abort();
  }, [activeNews, previewTicker]);
  const point = series.points.at(-1);
  const previous = series.points.at(-2);
  const change = point && previous?.c ? (point.c / previous.c - 1) * 100 : null;
  const select = (index: number) => {
    if (index === selected) return;
    // Leave the current series on screen; the fetch effect flags it as loading.
    setPinned(null);
    setSelected(index);
    setHeadlines(null);
  };
  const closes = series.points.map((p) => p.c);
  const date = point && new Date(point.t);
  return <main className="shell closing-sheet">
      <section className="quote-tape" aria-label="Market overview">
          {instruments.map((item, i) => {
            const symbol = item.ticker === "I:SPX" && watchlist && !watchlist[item.ticker]?.length ? "SPY" : item.ticker === "I:VIX" ? volatility?.ticker ?? item.ticker : item.ticker;
            const pts = symbol === volatility?.ticker ? volatility.points : watchlist?.[symbol] ?? [];
            const last = pts.at(-1), prev = pts.at(-2);
            const delta = last && prev?.c ? (last.c / prev.c - 1) * 100 : null;
            // SPY already has its own tile, so the S&P 500 tile is left out when the index is not on the plan.
            if(item.ticker==="I:SPX" && (!watchlist || symbol==="SPY")) return null;
            const caption = symbol==="SPY"?"Tracks the S&P 500":symbol!==item.ticker?"Volatility ETF":item.name;
            const waiting = !watchlist || (item.ticker === "I:VIX" && !volatility);
            const why = waiting || last ? null
              : symbol === volatility?.ticker ? volatility.error ?? "No recent closes"
              : missing[symbol] === "plan" ? PLAN_MESSAGE : missing[symbol] ? DOWN_MESSAGE : "No recent closes";
            return <div className="watch-row" key={item.ticker} data-selected={selected===i}>
              <button className="card-hit" aria-label={"Preview "+symbol} aria-pressed={selected===i} onClick={()=>select(i)}/>
              <a className="card-name" href={"/stocks/"+encodeURIComponent(symbol).replace(/^I%3A/, "I:")} target="_blank" rel="noopener" aria-label={"Open "+symbol+" chart in a new tab"}><strong>{symbol.replace("I:","")}</strong><span aria-hidden="true">↗</span></a>
              <span className="strip-name">{caption}</span>
              {why ? <span className="tape-price tape-missing"><small>{why}</small></span>
                : <span className="tape-price"><strong>{last ? <CountValue text={(symbol.startsWith("I:")?format(last.c)+" pts":"$"+format(last.c))}/>:"—"}</strong><small className={delta===null||delta===0?"":delta<0?"down":"up"}>{delta===null?"—":<CountValue text={(delta>0?"+":"")+delta.toFixed(2)+"%"}/>}</small></span>}
            </div>;
          })}
      </section>
      {!!watchlist?.SPY?.length && (missing["I:SPX"] === "plan" || missing["I:VIX"] === "plan") && <p className="tape-note">{[missing["I:SPX"] === "plan" && "S&P 500 index", missing["I:VIX"] === "plan" && "VIX"].filter(Boolean).join(" and ")} levels are not available on this data plan; the ETFs that track them are shown instead.</p>}
      <div className="desk-columns">
      <section className="market-grid" aria-label="Price and closing sessions">
        <article className="chart-panel">
          <div className="chart-heading"><div><h2>{previewTicker.replace(/^I:/, "")}</h2><span>{previewName}</span></div>
            <div className="ranges" aria-label="Chart range">{ranges.map((item) => <button key={item} aria-pressed={item === range} onClick={() => {
              if (item === range) return;
              setPinned(null); setRange(item);
            }}>{item}</button>)}</div>
          </div>
          <div className="quote"><strong>{point ? <CountValue text={format(point.c)}/> : series.ready ? "—" : <span className="sk sk-price" aria-label="Loading price"/>}</strong><span>{series.currency ?? (instrument.ticker.startsWith("I:") ? "PTS" : "USD")}</span>{series.actualTicker && series.actualTicker !== instrument.ticker && <span className="muted">{series.actualTicker} · ETF proxy for the {instrument.code}</span>}
            {change !== null && <span className={change === 0 ? "" : change < 0 ? "down" : "up"}><CountValue text={(change > 0 ? "+" : "") + change.toFixed(2) + "%"}/> <small>from previous close</small></span>}</div>
          {date && <p className="quote-date">Latest close{date && <> · <time dateTime={date.toISOString()}>{date.toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</time></>}{point && " · Massive"}</p>}
          {/* First load shows a skeleton; later loads keep the old chart and dim it. */}
          <div className="chart-body" aria-busy={!!series.loading} data-loading={series.loading && series.points.length > 0}>
            {series.points.length ? <PricePlot key={previewTicker+range} points={series.points} pinned={pinned} onPin={setPinned} label={previewTicker+" daily closes"} units={series.currency??"USD"}/>
              : series.ready ? <p className="empty">{series.error ?? "No daily prices for this symbol."}</p> : <ChartSkeleton/>}
          </div>
          <div className="chart-stats" data-loading={series.loading}><div><span>Lowest close</span><strong>{closes.length ? <CountValue text={format(Math.min(...closes))}/> : "—"}</strong></div><div><span>Highest close</span><strong>{closes.length ? <CountValue text={format(Math.max(...closes))}/> : "—"}</strong></div>
            <button className="text-button news-button" aria-expanded={activeNews} onClick={() => { setActiveNews(!activeNews); setHeadlines(null); }}><Newspaper size={16}/>{activeNews ? "Hide news" : "Headlines"}</button></div>
          {activeNews && <div className="headlines" role="status">{headlines === null ? <HeadlineSkeleton/> : typeof headlines === "string" ? headlines : headlines.length ? headlines.map((item) => <a key={item.id} href={item.article_url} target="_blank" rel="noreferrer"><small>{item.publisher?.name || previewTicker}</small><strong>{item.title}</strong></a>) : "No recent headlines for this symbol."}</div>}
        </article>
        <aside className="ledger">
          <h2>
            <button
              type="button"
              className="ledger-toggle"
              aria-controls="recent-sessions"
              aria-expanded={recentOpen}
              onClick={() => setRecentOpen(!recentOpen)}
            >
              <span>Recent closes</span>
              <ChevronDown className="ledger-toggle-icon" size={18} aria-hidden="true" />
            </button>
          </h2>
          <div id="recent-sessions" hidden={!recentOpen}><table><thead><tr><th>Session</th><th>Close</th><th>Change</th></tr></thead><tbody>
          {series.points.slice(-7).reverse().map((bar,i) => {
            const idx = series.points.length - 1 - i;
            const prev = series.points[idx - 1];
            const pct = prev?.c ? (bar.c / prev.c - 1) * 100 : null;
            return <tr key={bar.t} className={pinned === idx ? "pinned" : ""}>
              <td><button aria-label={"Inspect close for " + shortDate(new Date(bar.t).toISOString())} aria-pressed={pinned === idx} onClick={() => setPinned(pinned === idx ? null : idx)}>{shortDate(new Date(bar.t).toISOString())}</button></td>
              <td><CountValue text={format(bar.c)}/></td><td className={pct === null || pct === 0 ? "" : pct < 0 ? "down" : "up"}>{pct === null ? "—" : <CountValue text={(pct > 0 ? "+" : "") + pct.toFixed(2) + "%"}/>}</td>
            </tr>;
          })}
        </tbody></table>{!series.points.length && (series.ready ? <p className="empty">{series.error ?? "No closing sessions available."}</p> : <RowSkeleton rows={4} cells={3}/>)}
        <p className="ledger-note">Source · Massive · {series.actualTicker && series.actualTicker !== instrument.ticker ? `${series.actualTicker} ETF proxy · ${series.currency ?? "USD"}` : instrument.ticker.startsWith("I:") ? "Index points" : `${instrument.ticker} · USD`}</p>
        </div></aside>
      </section>
      <aside className="desk-rail"><Watchlist/>
        <Technicals ticker={previewTicker}/></aside>
      </div>
      {briefing}
      <div className="section-heading lower-heading"><div><h2>Market overview</h2><p>Company earnings and new listings</p></div></div>
      <Performance/>
      <div className="bottom-row">
        <section className="panel listings"><div className="panel-head"><h2><CalendarDays size={17}/>IPO calendar</h2></div>
          {feed?.ipos?.slice(0, allListings ? undefined : 5).map(ipo => <details className="ipo-entry" key={ipo.ticker + ipo.listing_date}>
            <summary className="listing"><span className="listing-date">{ipo.listing_date ? shortDate(ipo.listing_date) : "TBD"}</span><span><b>{ipo.ticker}</b><small>{ipo.issuer_name}</small></span><span className="exchange">{ipo.primary_exchange} <ChevronDown size={15} aria-hidden="true"/></span></summary>
            <dl><div><dt>Listing date</dt><dd>{ipo.listing_date || "Pending"}</dd></div><div><dt>Status</dt><dd>{ipo.ipo_status || "Unreported"}</dd></div><div><dt>Final offer price</dt><dd>{ipo.final_issue_price ?? "Unreported"}</dd></div></dl>
          </details>)}
          {!!feed?.ipos && feed.ipos.length > 5 && <button className="calendar-more" aria-expanded={allListings} onClick={() => setAllListings(!allListings)}>{allListings ? "Show fewer listings" : "View all "+feed.ipos.length+" listings"}</button>}
          {!feed?.ipos?.length && (!feed ? <RowSkeleton rows={5} cells={3}/> : <p className="empty">{feed.ipos === null ? feed.error ?? "IPO data is unavailable right now" : "No listings in this window."}</p>)}
        </section>
        <section className="panel earnings">
          <div className="panel-head"><h2>Quarterly earnings</h2><ReportLinks ticker={ticker}/></div>
          <form onSubmit={event => {
            event.preventDefault();
            const symbol = String(new FormData(event.currentTarget).get("symbol")).trim().toUpperCase();
            if (symbol !== ticker) { setRows(undefined); setTicker(symbol); }
          }}>
            <label htmlFor="earnings-symbol">Company ticker</label>
            <input id="earnings-symbol" name="symbol" defaultValue="MSFT" required pattern="[A-Za-z][A-Za-z0-9.\-]{0,14}" maxLength={15}/>
            <button>View quarters →</button>
          </form>
          <p role="status"><StockLink ticker={ticker}/> · {rows === undefined ? "Loading earnings…" : rows === null ? rowsError || "Earnings data is unavailable right now" : rows.length ? rows.length + " latest quarters" : "No quarterly results in SEC filings for this symbol."}</p>
          {rows === undefined && <RowSkeleton rows={5} cells={5}/>}
          {!!rows?.length && <div className="filings-scroll"><table><caption className="table-units">Figures in USD · fiscal quarters as each company names them{rows.some(row => row.derived) && " · Q4* = full year (10-K) less the first nine months; EPS is not reported for Q4 alone"}</caption>
            <thead><tr><th>Fiscal quarter</th><th>Period end</th><th>Revenue</th><th>Diluted EPS</th><th>Source</th></tr></thead>
            <tbody>{rows.map(row => <tr key={row.period_end}><th scope="row">Q{row.fiscal_quarter} FY{row.fiscal_year}{row.derived && <abbr title="Derived: full-year revenue in the 10-K less the nine months reported in the third-quarter 10-Q">*</abbr>}</th><td>{row.period_end}</td>
              <td>{row.revenue == null ? "Unavailable" : <CountValue text={new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 }).format(row.revenue)}/>}</td>
              <td>{row.diluted_earnings_per_share != null ? <CountValue text={(row.diluted_earnings_per_share < 0 ? "-$" : "$")+format(Math.abs(row.diluted_earnings_per_share))}/> : row.derived ? <span title="A 10-K does not report fourth-quarter EPS on its own">Not reported</span> : "Unavailable"}</td>
              <td>{row.filing_url ? <a href={row.filing_url} target="_blank" rel="noopener" aria-label={(row.derived ? "10-K" : row.source)+" filing for "+row.period_end} title={row.derived ? "SEC EDGAR · annual report (10-K)" : row.source}>{row.derived ? "10-K ↗" : "Filing ↗"}</a> : row.source}</td></tr>)}</tbody></table></div>}
        </section>
      </div>
      <footer><Wordmark/><span>Market data by Massive · Filings from SEC EDGAR</span></footer>
    </main>;
}

