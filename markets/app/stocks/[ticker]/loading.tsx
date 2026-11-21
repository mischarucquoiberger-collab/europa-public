import Link from "next/link";
import "../../closing-sheet.css";

/**
 * Shown by Next.js while a stock page fetches quotes, news and filings.
 *
 * It deliberately mirrors page.tsx element for element: same wrappers, same
 * headings, same toolbar. Static parts (the back link, section headings) are
 * rendered for real, and only the data-driven text is replaced by a grey bar
 * that keeps its line height. That way nothing moves when the real page swaps in.
 */

/** Grey bar sized by hidden placeholder text, so it occupies a real line box. */
function Ghost({ children }: { children: string }) {
  return <span className="sk-ghost">{children}</span>;
}

export default function LoadingStock() {
  return (
    <main className="shell closing-sheet stock-page" aria-busy="true">
      <div className="paper-mast ticker-mast">
        <Link href="/" aria-label="Back to markets">← Markets</Link>
      </div>

      <header>
        <small><Ghost>TICKER · CS XNAS</Ghost></small>
        <h1><Ghost>Company name</Ghost></h1>
        <div className="close-price"><Ghost>000.00</Ghost> <small><Ghost>USD</Ghost></small></div>
        <p><Ghost>Massive daily close · As of 0000-00-00</Ghost></p>
      </header>

      <section className="instrument-plot">
        <div className="chart-toolbar">
          <h2>Daily prices</h2>
          <div className="ranges">{["Line", "Candles"].map((m) => <button key={m} disabled>{m}</button>)}</div>
          <div className="ranges">{["1W", "1M", "3M", "1Y"].map((r) => <button key={r} disabled aria-pressed={r === "1M"}>{r}</button>)}</div>
        </div>
        <div className="price-plot"><div className="sk sk-chart" aria-hidden="true" /></div>
      </section>

      <section className="news-section">
        <h2><Ghost>Headlines</Ghost></h2>
        <div className="news-grid" aria-hidden="true">
          {Array.from({ length: 4 }, (_, i) => (
            <article key={i}>
              <small><Ghost>Publisher · Nov 00, 0:00 PM ET</Ghost></small>
              <h3><Ghost>A headline about this company that runs onto a second line</Ghost></h3>
              <Ghost>Story details</Ghost>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
