"use client";
import { useState } from "react";
import { Search } from "lucide-react";
import companies from "@/lib/companies.json";

export function TickerSearch() {
  const [query, setQuery] = useState("");
  const text = query.trim().toLowerCase();
  const matches = text ? companies.filter(company =>
    company.ticker.toLowerCase().startsWith(text) || company.name.toLowerCase().includes(text)
  ).slice(0, 5) : [];
  const exact = matches.find(company => company.ticker.toLowerCase() === text);
  const ticker = exact?.ticker ?? matches[0]?.ticker ?? query.trim().toUpperCase();
  const valid = /^(?:I:)?[A-Z][A-Z0-9.-]{0,14}$/.test(ticker);
  const path = (symbol: string) => "/stocks/" + encodeURIComponent(symbol);
  return <form className="header-search" role="search" action={valid ? path(ticker) : undefined}
    target="_blank" rel="noopener" onSubmit={event => { if (!valid) event.preventDefault(); }}>
    <Search size={16} aria-hidden="true"/>
    <input aria-label="Find a stock by company or ticker" value={query} onChange={event => setQuery(event.target.value)}
      placeholder="Company or ticker" autoComplete="off" required/>
    <button disabled={!valid}>Open chart</button>
    {text && <div className="search-result">
      {matches.length ? matches.map(company => <a key={company.ticker} href={path(company.ticker)} target="_blank" rel="noopener">{company.ticker} · {company.name}</a>)
        : valid ? <a href={path(ticker)} target="_blank" rel="noopener">Open {ticker} chart</a> : <span>Enter a stock symbol or company name.</span>}
    </div>}
  </form>;
}
