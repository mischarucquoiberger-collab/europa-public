"use client";

import Watchlist from "./watchlist";
import { CountValue } from "@/app/count-value";
import { CalendarDays, ChevronDown, Newspaper } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { Article, Ipo, Point } from "@/lib/massive";
import type { Earnings } from "@/lib/earnings";
import {PricePlot} from "./price-plot";
import Performance from "./performance";
import Technicals from "./technicals";
import { ChartSkeleton, HeadlineSkeleton, RowSkeleton } from "./skeletons";
import { StockLink } from "./stock-news";
import "./closing-sheet.css";
import {TickerSearch} from "./search";
import { Wordmark } from "./masthead";

const instruments = [
  { ticker: "SPY", code: "SPY", name: "S&P 500 ETF", detail: "SPDR S&P 500 ETF Trust", color: "#EEF0EA", value: 689.23 },
  { ticker: "QQQ", code: "QQQ", name: "Nasdaq 100 ETF", detail: "Invesco QQQ Trust", color: "#9FB0C8", value: 615.28 },
  { ticker: "IWM", code: "IWM", name: "Russell 2000 ETF", detail: "iShares Russell 2000 ETF", color: "#8A93A0", value: 251.34 },
  { ticker: "I:SPX", code: "SPX", name: "S&P 500 Index", detail: "S&P 500 Index", color: "#b4bd90", value: 6892.34 },
  { ticker: "I:NDX", code: "NDX", name: "Nasdaq 100 Index", detail: "Nasdaq 100 Index", color: "#93d2d0", value: 25136.62 },
  { ticker: "I:VIX", code: "VIX", name: "Volatility Index", detail: "Cboe Volatility Index", color: "#eeac9b", value: 17.26 },
];
const ranges = ["1W", "1M", "3M", "1Y"];
const sampleIpos: Ipo[] = [
  { ticker: "STRM", issuer_name: "Streamline Systems", primary_exchange: "NASDAQ", listing_date: "2026-11-24", ipo_status: "pending" },
  { ticker: "HWVN", issuer_name: "Harborwave Networks", primary_exchange: "NYSE", listing_date: "2026-11-25", ipo_status: "pending" },
  { ticker: "EMBR", issuer_name: "Ember Systems", primary_exchange: "NASDAQ", listing_date: "2026-12-02", ipo_status: "pending" },
  { ticker: "NRVA", issuer_name: "Novera Robotics", primary_exchange: "NASDAQ", listing_date: "2026-12-04", ipo_status: "pending" },
];
const sampleEarnings: Earnings[] = [];

const format = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shortDate = (s: string) => new Date(s.length === 10 ? s + "T12:00:00Z" : s).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
function sample(index: number, range = "1M"): Point[] {
  const count = [8, 25, 56, 100][ranges.indexOf(range)] || 25;
  const info = instruments[index];
  return Array.from({ length: count }, (_, i) => {
    const x = i / (count - 1);
    const wave = Math.sin(i * 1.21 + index * 2) * .006 + Math.sin(i * .48 + index) * .011 + Math.cos(i * 2.33) * .0024;
    return { t: Date.UTC(2026, 10, 20 - Math.round((count - 1 - i) * 1.4)), c: i === count - 1 ? info.value : info.value * (1 + (index === 5 ? .12 : -.10) * (1 - x) + wave) };
  });
}

async function market(query: string, signal: AbortSignal) {
  const response = await fetch(`/api/market?${query}`, { signal });
  if (!response.ok) throw new Error("Market data unavailable");
  return response.json();
}

export default function Desk({ briefing }: { briefing: React.ReactNode }) {
  const [selected, setSelected] = useState(0);
  const [pinned, setPinned] = useState<number | null>(null);
  const [recentOpen,setRecentOpen]=useState(false);
  const [range, setRange] = useState("1M");
  // `points` are kept while a new range/ticker loads so the chart never blanks out;
  // `loading` dims the panel instead. `ready` stays false only until the first load.
  const [series, setSeries] = useState<{ points: Point[]; sample: boolean; error?: boolean; ready?: boolean; loading?: boolean; actualTicker?: string; currency?: string }>({ points: [], sample: false, loading: true });
  const [watchlist, setWatchlist] = useState<Record<string, Point[]> | null>(null);
  const [volatility, setVolatility] = useState<{ points: Point[]; ticker: string } | null>(null);
  const [allListings, setAllListings] = useState(false);
  const [feed, setFeed] = useState<{ ipos: Ipo[] | null; earnings: Earnings[] | null } | null>(null);
  const [mode, setMode] = useState("");
  const [ticker, setTicker] = useState("MSFT");
  const [rows, setRows] = useState<Earnings[] | null | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    market("section=earnings&ticker=" + encodeURIComponent(ticker), controller.signal)
      .then(data => { if (!controller.signal.aborted) setRows(data.earnings ?? null); })
      .catch(() => { if (!controller.signal.aborted) setRows(null); });
    return () => controller.abort();
  }, [ticker]);
  const [activeNews, setActiveNews] = useState(false);
  const [headlines, setHeadlines] = useState<Article[] | null>(null);
  const instrument = instruments[selected];
  const previewTicker = instrument.ticker === "I:SPX" && watchlist && !watchlist[instrument.ticker]?.length ? "SPY" : instrument.ticker === "I:VIX" ? volatility?.ticker ?? instrument.ticker : instrument.ticker;
  const previewName = previewTicker === instrument.ticker ? instrument.detail : previewTicker+" ETF · "+instrument.code+" proxy";
  useEffect(() => {
    const controller = new AbortController();
    market("section=feed", controller.signal).then((data) => {
      setMode(data.mode);
      setFeed(data.mode === "sample" ? { ipos: sampleIpos, earnings: sampleEarnings } : data);
    }).catch(() => { if (!controller.signal.aborted) setFeed({ ipos: null, earnings: null }); });
    market("section=watchlist", controller.signal).then((data) => {
      setWatchlist(data.mode === "sample" ? Object.fromEntries(instruments.map((item, i) => [item.ticker, sample(i).slice(-10)])) : data.watchlist);
    }).catch(() => { if (!controller.signal.aborted) setWatchlist({}); });
    market("section=volatility", controller.signal).then((data) => {
      if (!controller.signal.aborted) setVolatility(data.mode === "sample" ? { points: sample(5, "1M"), ticker: "I:VIX" } : { points: data.volatility, ticker: data.volatilityTicker ?? "I:VIX" });
    }).catch(() => { if (!controller.signal.aborted) setVolatility({ points: [], ticker: "I:VIX" }); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setSeries((old) => ({ ...old, loading: true, error: false }));
    setPinned(null);
    market(`section=chart&ticker=${encodeURIComponent(previewTicker)}&range=${range}`, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setSeries({ points: data.mode === "sample" ? sample(selected, range) : data.points, sample: data.mode === "sample", ready: true, loading: false, actualTicker: data.actualTicker ?? instrument.ticker, currency: data.currency ?? (instrument.ticker.startsWith("I:") ? "PTS" : "USD") });
    }).catch(() => { if (!controller.signal.aborted) setSeries({ points: [], sample: false, error: true, ready: true, loading: false }); });
    return () => controller.abort();
  }, [previewTicker, instrument.ticker, range, selected]);
  useEffect(() => {
    if (!activeNews) return;
    const controller = new AbortController();
    market(`section=news&ticker=${encodeURIComponent(previewTicker)}`, controller.signal).then((data) => setHeadlines(data.news ?? [])).catch(() => {
      if (!controller.signal.aborted) setHeadlines([]);
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
            if(item.ticker==="I:SPX" && (!watchlist || symbol==="SPY")) return null;
            const caption = symbol==="SPY"?"Tracks the S&P 500":symbol!==item.ticker?"Volatility ETF":item.name;
            return <div className="watch-row" key={item.ticker} data-selected={selected===i}>
              <button className="card-hit" aria-label={"Preview "+symbol} aria-pressed={selected===i} onClick={()=>select(i)}/>
              <a className="card-name" href={"/stocks/"+encodeURIComponent(symbol).replace(/^I%3A/, "I:")} target="_blank" rel="noopener" aria-label={"Open "+symbol+" chart in a new tab"}><strong>{symbol.replace("I:","")}</strong><span aria-hidden="true">↗</span></a>
              <span className="strip-name">{caption}</span>
              <span className="tape-price"><strong>{last ? <CountValue text={(symbol.startsWith("I:")?format(last.c)+" pts":"$"+format(last.c))}/>:"—"}</strong><small className={delta!==null&&delta<0?"down":"up"}>{delta===null?"—":<CountValue text={(delta>=0?"+":"")+delta.toFixed(2)+"%"}/>}</small></span>
            </div>;
          })}
      </section>
      <div className="desk-columns">
      <section className="market-grid" aria-label="Price and closing sessions">
        <article className="chart-panel">
          <div className="chart-heading"><div><h2>{previewTicker}</h2><span>{previewName}</span></div>
            <div className="ranges" aria-label="Chart range">{ranges.map((item) => <button key={item} aria-pressed={item === range} onClick={() => {
              if (item === range) return;
              setPinned(null); setRange(item);
            }}>{item}</button>)}</div>
          </div>
          <div className="quote"><strong>{point ? <CountValue text={format(point.c)}/> : series.ready ? "—" : <span className="sk sk-price" aria-label="Loading price"/>}</strong><span>{series.currency ?? (instrument.ticker.startsWith("I:") ? "PTS" : "USD")}</span>{series.actualTicker && series.actualTicker !== instrument.ticker && <span className="muted">{series.actualTicker} · {series.currency} ETF proxy</span>}
            {change !== null && <span className={change < 0 ? "down" : "up"}><CountValue text={(change >= 0 ? "+" : "") + change.toFixed(2) + "%"}/> <small>from previous close</small></span>}</div>
          <p className="quote-date">{series.sample?"Sample close":"Latest close"}{date && <> · <time dateTime={date.toISOString()}>{date.toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</time></>}{point && !series.sample && " · Massive"}</p>
          {/* First load shows a skeleton; later loads keep the old chart and dim it. */}
          <div className="chart-body" aria-busy={!!series.loading} data-loading={series.loading && series.points.length > 0}>
            {series.points.length ? <PricePlot key={previewTicker+range} points={series.points} pinned={pinned} onPin={setPinned} label={previewTicker+" daily closes"} units={series.currency??"USD"}/>
              : series.ready ? <p className="empty">Daily prices unavailable.</p> : <ChartSkeleton/>}
          </div>
          <div className="chart-stats" data-loading={series.loading}><div><span>Lowest close</span><strong>{closes.length ? <CountValue text={format(Math.min(...closes))}/> : "—"}</strong></div><div><span>Highest close</span><strong>{closes.length ? <CountValue text={format(Math.max(...closes))}/> : "—"}</strong></div>
            <button className="text-button news-button" aria-expanded={activeNews} onClick={() => { setActiveNews(!activeNews); setHeadlines(null); }}><Newspaper size={16}/>{activeNews ? "Hide news" : "Headlines"}</button></div>
          {activeNews && <div className="headlines" role="status">{headlines === null ? <HeadlineSkeleton/> : headlines.length ? headlines.map((item) => <a key={item.id} href={item.article_url} target="_blank" rel="noreferrer"><small>{item.publisher?.name || previewTicker}</small><strong>{item.title}</strong></a>) : "No headlines available for this selection."}</div>}
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
              <td><CountValue text={format(bar.c)}/></td><td className={pct === null ? "" : pct < 0 ? "down" : "up"}>{pct === null ? "—" : <CountValue text={(pct >= 0 ? "+" : "") + pct.toFixed(2) + "%"}/>}</td>
            </tr>;
          })}
        </tbody></table>{!series.points.length && (series.ready ? <p className="empty">No closing sessions available.</p> : <RowSkeleton rows={4} cells={3}/>)}
        <p className="ledger-note">{series.sample ? "Sample prices" : "Source · Massive"} · {series.actualTicker && series.actualTicker !== instrument.ticker ? `${series.actualTicker} ETF proxy · ${series.currency ?? "USD"}` : instrument.ticker.startsWith("I:") ? "Index points" : `${instrument.ticker} · USD`}</p>
        </div></aside>
      </section>
      <aside className="desk-rail"><Watchlist/>
        <Technicals ticker={previewTicker} fallback={sample(selected, "1Y")}/></aside>
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
          {!feed?.ipos?.length && (!feed ? <RowSkeleton rows={5} cells={3}/> : <p className="empty">{feed.ipos === null ? "IPO data unavailable." : "No listings in this window."}</p>)}
        </section>
        <section className="panel earnings">
          <div className="panel-head"><h2>Quarterly earnings</h2><Link href={'/reports?ticker='+ticker}>Company research</Link></div>
          <form onSubmit={event => {
            event.preventDefault();
            const symbol = String(new FormData(event.currentTarget).get("symbol")).trim().toUpperCase();
            if (symbol !== ticker) { setRows(undefined); setTicker(symbol); }
          }}>
            <label htmlFor="earnings-symbol">Company ticker</label>
            <input id="earnings-symbol" name="symbol" defaultValue="MSFT" required pattern="[A-Za-z][A-Za-z0-9.\-]{0,14}" maxLength={15}/>
            <button>View quarters →</button>
          </form>
          <p role="status"><StockLink ticker={ticker}/> · {rows === undefined ? "Loading earnings…" : rows === null ? "Earnings unavailable." : rows.length ? rows.length + " reported quarters" : "No quarterly results available."}</p>
          {rows === undefined && <RowSkeleton rows={5} cells={5}/>}
          {!!rows?.length && <div className="filings-scroll"><table><caption className="table-units">Figures in USD</caption>
            <thead><tr><th>Fiscal quarter</th><th>Period end</th><th>Revenue</th><th>Diluted EPS</th><th>Source</th></tr></thead>
            <tbody>{rows.map(row => <tr key={row.period_end}><th scope="row">Q{row.fiscal_quarter} FY{row.fiscal_year}</th><td>{row.period_end}</td>
              <td>{row.revenue == null ? "Unavailable" : <CountValue text={new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 }).format(row.revenue)}/>}</td>
              <td>{row.diluted_earnings_per_share == null ? "Unavailable" : <CountValue text={"$"+format(row.diluted_earnings_per_share)}/>}</td>
              <td>{row.filing_url ? <a href={row.filing_url} aria-label={row.source+" filing for "+row.period_end} title={row.source}>Filing ↗</a> : row.source}</td></tr>)}</tbody></table></div>}
        </section>
      </div>
      <footer><Wordmark/><span>{mode === "sample" ? "Illustrative market data" : "Market data by Massive"}</span></footer>
    </main>;
}

