"use client";
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { Point } from "@/lib/massive";

const dateLabel = (time:number,year=false) => new Date(time).toLocaleDateString("en-US",{month:"short",day:"numeric",...(year?{year:"numeric"}:{}),timeZone:"UTC"});
const money = (n:number) => n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:4});
const shares = new Intl.NumberFormat("en-US",{notation:"compact",maximumFractionDigits:1});
type Props = {points:Point[]; pinned:number|null; onPin:(index:number|null)=>void; candles?:boolean; units:string; label:string; previous?:Point};
export function PricePlot({points,pinned,onPin,candles=false,units,label,previous}:Props) {
  const frame=useRef<HTMLDivElement>(null);
  // Starts at 0 so nothing is drawn at a guessed width; the layout effect below
  // measures the real width before the browser paints, avoiding a visible resize.
  const [width,setWidth]=useState(0);
  const [cursor,setCursor]=useState<number|null>(null);
  const gradient=useId();
  useLayoutEffect(()=>{
    if(!frame.current)return;
    setWidth(Math.max(180,frame.current.getBoundingClientRect().width));
    const observer=new ResizeObserver(([entry])=>setWidth(Math.max(180,entry.contentRect.width)));
    observer.observe(frame.current);
    return ()=>observer.disconnect();
  },[]);
  const full=!!points.length && width>0;
  const left=12,right=width-64,top=16,bottom=210;
  const step=(right-left)/Math.max(1,points.length-1);
  const x=(i:number)=>points.length===1?(left+right)/2:left+step*i;
  const values=points.flatMap(p=>candles?[p.l??p.c,p.h??p.c]:[p.c]);
  const lo=Math.min(...values),hi=Math.max(...values);
  const y=(value:number)=>hi===lo?(top+bottom)/2:bottom-(value-lo)/(hi-lo)*(bottom-top);
  const maxVolume=Math.max(1,...points.map(p=>p.v??0));
  const volume=points.some(p=>p.v!=null);
  const height=volume?305:249;
  const idx=pinned??cursor;
  const bar=idx===null?undefined:points[idx];
  const prev=idx===null?undefined:points[idx-1]??previous;
  const change=bar && prev?.c?100*(bar.c/prev.c-1):null;
  const price=(n:number)=> units==="USD"?"$"+money(n):money(n)+" "+units;
  const lineColor=points.length>1 && points.at(-1)!.c<points[0].c?"#ff9c96":"#76e3c8";
  const path=points.map((p,i)=>(i?"L":"M")+x(i)+" "+y(p.c)).join(" ");
  function nearest(e:React.PointerEvent<SVGSVGElement>){
    return Math.max(0,Math.min(points.length-1,Math.round((e.clientX-e.currentTarget.getBoundingClientRect().left-left)/step)));
  }
  function clear(){onPin(null);setCursor(null)}
  const candleWidth=Math.max(1,Math.min(step*.65,14));
  return <div className="price-plot" ref={frame} style={width?undefined:{minHeight:height}}>{full ? <>
    <svg width="100%" height={height} role="group" aria-label={label+". Use arrow keys to inspect sessions, Enter to pin and Escape to dismiss."} tabIndex={0}
      onPointerMove={e=>setCursor(nearest(e))} onPointerLeave={()=>setCursor(null)} onPointerDown={e=>onPin(nearest(e))}
      onFocus={()=>setCursor(points.length-1)} onBlur={()=>setCursor(null)}
      onKeyDown={e=>{
        if(e.key==="Escape"){clear();return}
        if(e.key==="Enter"){e.preventDefault();onPin(idx??points.length-1);return}
        if(e.key==="ArrowLeft"||e.key==="ArrowRight"){e.preventDefault();const next=Math.min(points.length-1,Math.max(0,(idx??points.length-1)+(e.key==="ArrowLeft"?-1:1)));onPin(null);setCursor(next)}
      }}>
      <defs><linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1"><stop stopColor={lineColor} stopOpacity=".19"/><stop offset="1" stopColor={lineColor} stopOpacity="0"/></linearGradient></defs>
      {[0,1,2,3].map(i=>{const v=lo+(hi-lo)*i/3;return <g key={i}><path className="price-rule" d={`M${left} ${y(v)}H${right}`} stroke="#344158"/><text x={right+6} y={y(v)+4}>{v.toLocaleString("en-US",{maximumFractionDigits:2})}</text></g>})}
      {!candles&&<><path className="series-area" d={path+` V${bottom} H${left} Z`} fill={`url(#${gradient})`}/><path className="series-line" pathLength="1" d={path} stroke={lineColor} strokeWidth="2.8" strokeLinejoin="round" fill="none"/></>}
      {points.map((p,i)=>{const down=p.o!=null && p.c<p.o;const color=down?"#ff9a90":"#edf1f7";return <g key={p.t}>
        {candles&&p.o!=null&&p.h!=null&&p.l!=null&&<g className={down?"candle falling":"candle rising"} stroke={color}><path d={`M${x(i)} ${y(p.h)}V${y(p.l)}`} strokeWidth="1.4"/><rect x={x(i)-candleWidth/2} y={Math.min(y(p.o),y(p.c))} width={candleWidth} height={Math.max(1.5,Math.abs(y(p.o)-y(p.c)))} fill={down?color:"#152034"}/></g>}
        {p.v!=null&&<rect className="volume-bar" x={x(i)-candleWidth/2} y={274-34*p.v/maxVolume} width={candleWidth} height={34*p.v/maxVolume} fill={down?"#a87476":"#8899b1"}/>}
      </g>})}
      {volume&&<text x={left} y="233">Volume</text>}
      {[...new Set(Array.from({length:width<500?3:5},(_,i)=>Math.round(i*(points.length-1)/(width<500?2:4))))].map(i=><text key={i} x={x(i)} y={height-8} textAnchor={i===0?"start":i===points.length-1?"end":"middle"}>{dateLabel(points[i].t)}</text>)}
      {bar&&idx!==null&&<g><path d={`M${x(idx)} 8V${height-25}`} stroke="#d4ddea" strokeDasharray="4 3"/><circle cx={x(idx)} cy={y(bar.c)} r="5" fill="#eef2f6" stroke="#152034" strokeWidth="2"/></g>}
    </svg>
    {bar&&idx!==null&&<div className="session-tip" role="status" style={{left:Math.max(2,Math.min(width-187,x(idx)+(x(idx)+196>width?-188:12))),top:Math.max(4,Math.min(height-(candles?196:94),y(bar.c)-22))}}>
      {pinned!==null&&<button aria-label="Dismiss pinned session" onClick={clear}>×</button>}
      <strong>{price(bar.c)}</strong><time>{dateLabel(bar.t,true)}</time>
      {candles?<dl>{[["Open",price(bar.o!)],["High",price(bar.h!)],["Low",price(bar.l!)],["Close",price(bar.c)],["Volume",bar.v==null?"Unavailable":shares.format(bar.v)+" shares"]].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>:<small className={change!=null&&change<0?"down":"up"}>{change==null?"Prior close unavailable":(change>=0?"+":"")+change.toFixed(2)+"% vs. prior close"}</small>}
    </div>}
  </>:width===0?null:<p className="empty">Daily prices unavailable.</p>}</div>;
}
