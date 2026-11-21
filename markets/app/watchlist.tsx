"use client";
import { useState, useEffect } from "react";
import {StockLink} from "./stock-news";
import {RowSkeleton} from "./skeletons";

const defaults = ["AAPL", "MSFT", "NVDA"];
const key = "europa-watchlist-v1";
const valid = (s: unknown): s is string => typeof s === "string" && /^[A-Z][A-Z0-9.-]{0,14}$/.test(s);

function WatchRow({symbol, remove}: {symbol:string; remove:()=>void}) {
  const [quote,setQuote] = useState<{close:number; change:number|null; date:string; low?:number; high?:number; volume?:number; open?:number; previous?:number; averageVolume?:number}|null|undefined>(undefined);
  const [why,setWhy] = useState("Unavailable");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const response = await fetch("/api/market?section=chart&range=1M&ticker="+encodeURIComponent(symbol), {signal:controller.signal});
      if (!response.ok) {
        const body = await response.json().catch(()=>null);
        throw new Error(body?.reason === "plan" ? "Not on data plan" : "Unavailable");
      }
      const {points=[]} = await response.json();
      if (!points.length) setWhy("No data");
      const last = points.at(-1), prev = points.at(-2);
      const recentVolumes = points.slice(-20).map((p:{v?:number})=>p.v).filter((v:unknown):v is number=>typeof v==="number" && Number.isFinite(v));
      const averageVolume = recentVolumes.length===20 ? recentVolumes.reduce((sum:number,v:number)=>sum+v,0)/20 : undefined;
      setQuote(last ? {close:last.c, open:last.o, previous:prev?.c, averageVolume, low:last.l, high:last.h, volume:last.v, change:prev?.c ? last.c-prev.c : null, date:new Date(last.t).toISOString().slice(0,10)} : null);
    }
    load().catch((error)=>{if (!controller.signal.aborted) {setWhy(error instanceof Error && error.message === "Not on data plan" ? error.message : "Unavailable"); setQuote(null);}});
    return ()=>controller.abort();
  }, [symbol]);
  const signed = (n:number) => (n>0?"+":"")+n.toFixed(2);
  const [expanded,setExpanded] = useState(false);
  return <><tr><th scope="row"><button className="watch-expand" aria-label={"Session details for "+symbol} aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?"▾":"▸"}</button> <StockLink ticker={symbol}/></th><td title={quote?.date}>{quote ? "$"+quote.close.toFixed(2) : quote===null?why:<span className="sk sk-text" style={{width:"3.6rem",marginLeft:"auto"}}/>}</td>
    <td>{quote?.change != null ? signed(quote.change) : quote===undefined ? <span className="sk sk-text" style={{width:"2.8rem",marginLeft:"auto"}}/> : "—"}</td><td className={!quote?.change?"":quote.change<0?"down":"up"}>{quote?.change != null ? signed(100*quote.change/(quote.close-quote.change))+"%" : quote===undefined ? <span className="sk sk-text" style={{width:"3rem",marginLeft:"auto"}}/> : "—"}</td>
    <td><button aria-label={"Remove "+symbol} onClick={remove}>×</button></td></tr>{expanded && <tr><td colSpan={5}><dl className="watch-stats">
    <div><dt>Trading date</dt><dd>{quote?.date ?? "—"}</dd></div>
    <div><dt>Day range</dt><dd>{quote?.low != null && quote.high != null ? "$"+quote.low.toFixed(2)+" – $"+quote.high.toFixed(2) : "—"}</dd></div>
    <div><dt>Volume</dt><dd>{quote?.volume != null ? Math.round(quote.volume).toLocaleString("en-US")+" shares" : "—"}</dd></div>
    <div><dt>Opening price</dt><dd>{quote?.open != null ? "$"+quote.open.toFixed(2) : "—"}</dd></div>
    <div><dt>Previous close</dt><dd>{quote?.previous != null ? "$"+quote.previous.toFixed(2) : "—"}</dd></div>
    <div><dt>20-session avg. volume</dt><dd>{quote?.averageVolume != null ? Math.round(quote.averageVolume).toLocaleString("en-US")+" shares" : "—"}</dd></div>
  </dl></td></tr>}</>;
}
export default function Watchlist() {
  const [symbols,setSymbols]=useState<string[]|null>(null);
  const [input,setInput]=useState("");
  useEffect(()=>{
    try {const stored=JSON.parse(localStorage.getItem(key)??"null"); setSymbols(Array.isArray(stored)?stored.filter(valid):defaults);}
    catch {setSymbols(defaults);}
  },[]);
  function save(next:string[]) {setSymbols(next);try {localStorage.setItem(key,JSON.stringify(next));} catch {}}
  const symbol=input.trim().toUpperCase();
  return <section className="saved-watch"><header><h2>Watchlist</h2><form onSubmit={e=>{e.preventDefault();if(symbols && valid(symbol) && !symbols.includes(symbol)){save([...symbols,symbol]);setInput("");}}}>
    <input aria-label="Ticker to watch" placeholder="Add ticker" maxLength={15} value={input} onChange={e=>setInput(e.target.value)}/><button disabled={!symbols || !valid(symbol) || symbols.includes(symbol)}>Add</button></form></header>
    <table><thead><tr><th>Symbol</th><th>Latest close</th><th>Change</th><th>Change %</th><th aria-label="Manage"/></tr></thead><tbody>{symbols?.map(s=><WatchRow key={s} symbol={s} remove={()=>save(symbols.filter(x=>x!==s))}/>)}</tbody></table>
    {symbols===null && <RowSkeleton rows={3} cells={4}/>}
    {symbols?.length===0 && <p>Add a ticker to track its closing price.</p>}</section>;
}
