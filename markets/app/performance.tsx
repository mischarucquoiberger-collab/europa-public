"use client";
import { CountValue } from "@/app/count-value";
import { useEffect, useMemo, useState } from "react";
import { StockLink } from "./stock-news";

const sectors = { XLK:"Technology", XLF:"Financials", XLE:"Energy", XLV:"Health care", XLU:"Utilities" };
const defaults = ["SPY","QQQ","IWM"];
const periods = { "1W":7, "1M":30, "3M":90, "1Y":365 };
const colors = ["#d8e7fc","#f0ad87","#82cdc2","#c4aff1","#dace83","#90afdf","#eca4bc","#99c681"];
type History = Map<string,number>;
type Period = keyof typeof periods;
const percent = (n:number) => (n>0?"+":"")+n.toFixed(2)+"%";
/** "up" (green) for gains, "down" (red) for losses, nothing for zero or missing values. */
const tone = (n:number|null) => n===null||n===0 ? "" : n>0 ? "up" : "down";
const priceReturn = (start:number,end:number) => 100*(end/start-1);
const iso = (time:number) => new Date(time).toISOString().slice(0,10);

function HistoryRequest({ticker,save}:{ticker:string;save:(ticker:string,history:History)=>void}) {
  useEffect(()=>{
    const controller=new AbortController();
    async function load() {
      const response=await fetch("/api/market?section=chart&range=1Y&ticker="+encodeURIComponent(ticker),{signal:controller.signal});
      if(!response.ok) throw new Error("Unavailable");
      const data=await response.json();
      const history:History=new Map();
      for(const bar of data.points ?? []) if(Number.isFinite(bar.t) && bar.c>0) history.set(iso(bar.t),bar.c);
      if(!controller.signal.aborted) save(ticker,history);
    }
    load().catch(()=>{if(!controller.signal.aborted) save(ticker,new Map())});
    return ()=>controller.abort();
  },[ticker,save]);
  return null;
}
function windowDates(history:History,days:number) {
  const dates=[...history.keys()];
  if(!dates.length) return [];
  const cutoff=iso(Date.parse(dates[dates.length-1])-days*86400000);
  return dates.filter(d=>d>=cutoff);
}
export default function Performance() {
  const [selected,setSelected]=useState(defaults);
  const [histories,setHistories]=useState<Record<string,History>>({});
  const [period,setPeriod]=useState<Period>("1M");
  const [query,setQuery]=useState("");
  const [inspection,setInspection]=useState("");
  const [descending,setDescending]=useState(true);
  const save=useMemo(()=> (ticker:string,history:History)=>setHistories(old=>({...old,[ticker]:history})),[]);
  const requested=[...new Set([...defaults,...Object.keys(sectors),...selected])];
  const loaded=selected.filter(t=>histories[t]?.size);
  const {dates,lines}=useMemo(()=>{
    const series=selected.filter(t=>histories[t]?.size);
    const mostRecent=Math.max(...series.map(t=>Date.parse([...histories[t].keys()].at(-1)!)));
    if(!series.length) return {dates:[] as string[],lines:[] as {ticker:string;values:number[]}[]};
    const cutoff=iso(mostRecent-periods[period]*86400000);
    const dates=[...histories[series[0]].keys()].filter(d=>d>=cutoff && series.every(t=>histories[t].has(d)));
    return {dates,lines:series.map(ticker=>({ticker,values:dates.map(d=>priceReturn(histories[ticker].get(dates[0])!,histories[ticker].get(d)!))}))};
  },[histories,period,selected]);
  const idx=dates.includes(inspection)?dates.indexOf(inspection):dates.length-1;
  const values=lines.flatMap(line=>line.values);
  const low=Math.min(0,...values),high=Math.max(0,...values);
  const x=(i:number)=>55+835*i/Math.max(1,dates.length-1);
  const y=(v:number)=>20+170*(high-v)/(high-low || 1);
  const spy=histories.SPY;
  const table=Object.entries(sectors).map(([ticker,name])=>{
    const h=histories[ticker], days=h ? windowDates(h,30) : [];
    const end=days.at(-1),first=days[0],previous=days.at(-2);
    const close=end && h.get(end);
    const ret=typeof close==="number" && days.length>1 ? priceReturn(h.get(first)!,close) : null;
    const change=previous && typeof close==="number" ? priceReturn(h.get(previous)!,close) : null;
    const excess=ret!==null && end && spy?.has(first) && spy.has(end) ? ret-priceReturn(spy.get(first)!,spy.get(end)!) : null;
    return {ticker,name,close,ret,change,excess,end,first};
  }).sort((a,b)=>a.ret===null ? 1 : b.ret===null ? -1 : (descending?-1:1)*(a.ret-b.ret));
  function add(symbol:string){setSelected(old=>old.includes(symbol)?old:[...old,symbol]);setQuery("")}
  return <section className="analytics">
    {requested.filter(t=>!histories[t]).map(t=><HistoryRequest key={t} ticker={t} save={save}/>)}
    <div className="panel-head"><h2>Compare performance</h2><div className="ranges">{(Object.keys(periods) as Period[]).map(p=><button key={p} aria-pressed={period===p} onClick={()=>setPeriod(p)}>{p}</button>)}</div></div>
    <p className="muted">Each line starts at 0%. Follow it to see how much the price gained or lost. Dividends are excluded.</p>
    <form onSubmit={e=>{e.preventDefault();add(query.trim().toUpperCase())}}><label>Compare a stock <input value={query} placeholder="Ticker, e.g. AAPL" required maxLength={15} pattern="[A-Za-z0-9][A-Za-z0-9.\-]{0,14}" onChange={e=>setQuery(e.target.value)}/></label><button disabled={!query.trim() || selected.includes(query.trim().toUpperCase())}>+ Compare</button></form>
    <div className="comparison-legend">{selected.map((t,i)=><div key={t} style={{borderColor:colors[i%colors.length]}}><strong>{t}</strong> {histories[t] ? !histories[t].size ? "Unavailable" : dates.length ? <CountValue text={percent(lines.find(l=>l.ticker===t)!.values.at(-1)!)}/> : "No overlap" : "Loading…"} <button aria-label={"Remove "+t} onClick={()=>setSelected(old=>old.filter(v=>v!==t))}>×</button></div>)}</div>
    {dates.length>0 ? <>
    <svg className="returns-chart" viewBox="0 0 900 220" aria-label="Price return over shared sessions" role="img" onPointerMove={e=>{const box=e.currentTarget.getBoundingClientRect();setInspection(dates[Math.max(0,Math.min(dates.length-1,Math.round(((e.clientX-box.left)/box.width*900-55)/835*(dates.length-1))))])}}>
      {[...new Set([high,0,low])].map(v=><g key={v}><text x="2" y={y(v)+4}>{v.toFixed(1)}%</text><path d={`M55 ${y(v)}h835`} stroke={v===0?"#9fb0c8":"#35425a"} strokeDasharray={v===0?"5 3":undefined}/></g>)}
      {lines.map(line=><polyline key={period+line.ticker} pathLength="1" fill="none" stroke={colors[selected.indexOf(line.ticker)%colors.length]} strokeWidth="2.5" points={line.values.map((v,i)=>x(i)+","+y(v)).join(" ")}/>)}
      <path d={`M${x(idx)} 12v183`} stroke="#8495ae" strokeDasharray="3 4"/>
      <text x="55" y="214">{dates[0]}</text><text x="890" y="214" textAnchor="end">{dates.at(-1)}</text>
    </svg>
    <div className="return-inspector">
      <label>Compare on <select value={dates[idx]} onChange={e=>setInspection(e.target.value)}>{dates.map(d=><option key={d} value={d}>{new Date(d+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</option>)}</select></label>
      <div className="return-quotes">{lines.map(l=><span key={l.ticker}><i aria-hidden="true" style={{background:colors[selected.indexOf(l.ticker)%colors.length]}}/>{l.ticker} <strong>{percent(l.values[idx])}</strong></span>)}</div>
    </div></> : <p>{loaded.length ? "No shared trading dates in this period." : "Select a symbol with available closes."}</p>}
    <h2>U.S. sectors</h2><p className="muted">One-month returns compared with SPY. The difference is shown in percentage points.</p>
    <div className="filings-scroll"><table><thead><tr><th>Sector / ETF</th><th>Close (USD)</th><th>1D change</th><th aria-sort={descending?"descending":"ascending"}><button onClick={()=>setDescending(!descending)}>1M return {descending?"↓":"↑"}</button></th><th>vs. SPY</th><th>Compare</th></tr></thead>
    <tbody>{table.map(r=><tr key={r.ticker}><th scope="row">{r.name} <StockLink ticker={r.ticker}/><small>{r.first} {r.end && "– "+r.end}</small></th><td>{typeof r.close==="number"?<CountValue text={r.close.toFixed(2)}/>:histories[r.ticker]?"Unavailable":<span className="sk sk-text" style={{width:"3.4rem",marginLeft:"auto"}}/>}</td><td className={tone(r.change)}>{r.change===null?"—":<CountValue text={percent(r.change)}/>}</td><td className={tone(r.ret)}>{r.ret===null?"—":<CountValue text={percent(r.ret)}/>}</td><td className={tone(r.excess)}>{r.excess===null?"—":<CountValue text={(r.excess>0?"+":"")+r.excess.toFixed(2)+" pp"}/>}</td><td><button disabled={selected.includes(r.ticker)} onClick={()=>add(r.ticker)}>{selected.includes(r.ticker)?"Added":"Add"}</button></td></tr>)}</tbody></table></div>
  </section>;
}
