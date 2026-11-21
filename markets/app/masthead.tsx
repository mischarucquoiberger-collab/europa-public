import Link from "next/link";
import { TickerSearch } from "./search";

export function Wordmark() {
  return <span className="brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/></span>EUROPA</span>;
}

export function Masthead({ page }: { page: "markets" | "reports" }) {
  return <header className="topbar"><div className="mast">
    <Link href="/" aria-label="Europa home"><Wordmark/></Link>
    <nav aria-label="Main navigation">
      <Link href="/" aria-current={page === "markets" ? "page" : undefined}>Markets</Link>
      <Link href="/reports" aria-current={page === "reports" ? "page" : undefined}>Research</Link>
    </nav>
    <TickerSearch/>
  </div></header>;
}
