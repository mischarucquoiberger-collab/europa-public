"use client";
import {useState} from "react";
import type { Article } from "@/lib/massive";

export function StockLink({ ticker }: { ticker: string }) {
  return <a className="stock-link" href={'/stocks/'+encodeURIComponent(ticker)} target="_blank" rel="noopener">{ticker}</a>;
}
export function NewsList({ stories, title = "Stock news" }: { stories: Article[] | null; title?: string }) {
  const [expanded,setExpanded]=useState(false);
  return <section className="news-section"><h2>{title}</h2>{stories?.length ? <div className="news-grid">{(expanded?stories:stories.slice(0,4)).map(story =>
    <article key={story.id || story.article_url}>
      {story.image_url?.startsWith("https://") && <img className="news-photo" loading="lazy" alt="" src={story.image_url} onError={e=>{e.currentTarget.hidden=true;}}/>}
      <small><b>{story.publisher?.name}</b> · <time dateTime={story.published_utc}>{new Date(story.published_utc).toLocaleString("en-US",{month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZone:"America/New_York"})} ET</time></small>
      <h3><a href={story.article_url} target="_blank" rel="noreferrer">{story.headline??story.title}</a></h3>
      {(story.summary || !!story.tickers?.length) && <details><summary>Story details</summary>
      {story.summary && <p>{story.summary}</p>}
      <div className="symbols">{story.tickers?.map(ticker => <StockLink key={ticker} ticker={ticker}/>)}</div></details>}
    </article>)}</div> : <p>{stories ? "No recent equity headlines." : "News is currently unavailable."}</p>}{!!stories && stories.length>4 && <button className="more-stories" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?"Fewer stories":"More stories"}</button>}</section>;
}
