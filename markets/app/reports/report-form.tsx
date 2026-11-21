"use client";
import { Search } from "lucide-react";
import { useState } from "react";

type Report = { traceId: string; summary: string; model: string; ticker: string; sources: { label: string; title: string; url: string }[] };

export default function ReportForm({ initialTicker }: { initialTicker: string }) {
  const [ticker, setTicker] = useState(initialTicker);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<Report>();
  const [error, setError] = useState("");
  return <>
    <form className="panel report-form" onSubmit={async (event) => {
      event.preventDefault();
      if (pending) return;
      setPending(true); setError(""); setResult(undefined);
      try {
        const res = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker }) });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Report unavailable.");
        setResult(data);
      } catch (error) {
        setError(error instanceof Error ? error.message : "Something went wrong.");
      } finally { setPending(false); }
    }}>
      <label htmlFor="ticker">Stock ticker</label>
      <div className="report-controls"><Search size={18}/><input id="ticker" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="e.g. MSFT" required maxLength={15}/><button className="primary" disabled={pending} type="submit">{pending ? "Generating…" : "Generate research brief"}</button></div>
    </form>
    {pending && <div className="panel report-result" role="status"><div className="loading-bar"/><p>Retrieving market sources and drafting your brief…</p></div>}
    {error && <div className="panel report-result down" role="alert">{error}</div>}
    {result && <article className="panel report-result"><h2>{result.ticker} research brief</h2><p className="muted">{result.model}</p><p className="run-id">Run <code>{result.traceId}</code></p><div className="report-summary">{result.summary}</div>
      {!!result.sources.length && <><h3>Sources</h3><ul>{result.sources.map((source) => <li key={source.label}><a href={source.url} target="_blank" rel="noreferrer">[{source.label}] {source.title}</a></li>)}</ul></>}
    </article>}
  </>;
}
