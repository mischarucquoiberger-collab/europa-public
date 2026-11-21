"use client";
import {useState} from "react";
import type {Point} from "@/lib/massive";
import {PricePlot} from "../../price-plot";

const periods={"1W":7,"1M":30,"3M":90,"1Y":365};
export default function SessionChart({points,units}:{points:Point[];units:string}) {
  const [range,setRange]=useState<keyof typeof periods>("1M");
  const [mode,setMode]=useState("Line");
  const [pin,setPin]=useState<number|null>(null);
  const end=points.at(-1);
  const rows=end?points.filter(p=>p.t>end.t-periods[range]*86400000):[];
  const candles=rows.length>0&&rows.every(p=>p.o!=null&&p.h!=null&&p.l!=null);
  return <section className="instrument-plot"><div className="chart-toolbar"><h2>Daily prices</h2><div className="ranges">{["Line","Candles"].map(m=><button key={m} disabled={m==="Candles"&&!candles} aria-pressed={m===(candles?mode:"Line")} onClick={()=>setMode(m)}>{m}</button>)}</div><div className="ranges">{(Object.keys(periods) as (keyof typeof periods)[]).map(r=><button key={r} aria-pressed={range===r} onClick={()=>{setPin(null);setRange(r)}}>{r}</button>)}</div></div>
    <PricePlot key={range} points={rows} previous={points[points.length-rows.length-1]} units={units} label="Daily prices" pinned={pin} onPin={setPin} candles={candles&&mode==="Candles"}/>
  </section>;
}
