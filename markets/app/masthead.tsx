import Link from "next/link";
import { TickerSearch } from "./search";
import { shellUrl } from "@/lib/shell";

export function Wordmark() {
  return <span className="brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/></span>EUROPA</span>;
}

/**
 * The two report features side by side: this app's own quick brief, and the main
 * app's full research report (its Reports page, opened in the top window, not in the frame).
 */
export function ReportLinks({ ticker, current }: { ticker?: string; current?: boolean }) {
  return <span className="report-links">
    <Link href={ticker ? "/reports?ticker=" + encodeURIComponent(ticker) : "/reports"} aria-current={current ? "page" : undefined}>Quick brief</Link>
    <a href={shellUrl + "/#/Reports"} target="_top">Full report</a>
  </span>;
}

export function Masthead({ page }: { page: "markets" | "reports" }) {
  return <header className="topbar"><div className="mast">
    <Link href="/" aria-label="Europa home"><Wordmark/></Link>
    <nav aria-label="Main navigation">
      <Link href="/" aria-current={page === "markets" ? "page" : undefined}>Markets</Link>
      <span className="nav-research"><span>Research</span><ReportLinks current={page === "reports"}/></span>
    </nav>
    <TickerSearch/>
  </div></header>;
}
