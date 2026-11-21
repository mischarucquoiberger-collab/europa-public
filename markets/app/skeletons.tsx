/**
 * Loading placeholders shared across the desk.
 *
 * They all use the `.sk` shimmer block defined in closing-sheet.css, and they
 * are sized to match the real content so nothing shifts when data arrives.
 */

/** A line of shimmering text. `w` is any CSS width, e.g. "60%" or "4rem". */
export function TextSkeleton({ w = "100%" }: { w?: string }) {
  return <span className="sk sk-text" style={{ width: w }} />;
}

/** Stand-in for the price chart, including the axis and volume strip. */
export function ChartSkeleton() {
  return (
    <div className="chart-skeleton" aria-hidden="true">
      <div className="sk sk-chart" />
      <div className="chart-skeleton-axis">
        {[0, 1, 2, 3, 4].map((i) => <span className="sk sk-text" key={i} style={{ width: "3.2rem" }} />)}
      </div>
    </div>
  );
}

/** Stand-in for a table body: `rows` rows of `cells` cells. */
export function RowSkeleton({ rows = 4, cells = 3 }: { rows?: number; cells?: number }) {
  return (
    <div className="row-skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} style={{ gridTemplateColumns: `repeat(${cells}, minmax(0,1fr))` }}>
          {Array.from({ length: cells }, (_, cell) => (
            <span className="sk sk-text" key={cell} style={{ width: cell === 0 ? "70%" : "45%" }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Stand-in for the headline cards under the chart. */
export function HeadlineSkeleton({ count = 3 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div className="headline-skeleton" key={i} aria-hidden="true">
          <span className="sk sk-text" style={{ width: "40%" }} />
          <span className="sk sk-text" style={{ width: "92%" }} />
          <span className="sk sk-text" style={{ width: "65%" }} />
        </div>
      ))}
    </>
  );
}

/** Stand-in for the technicals card: performance tiles plus metric rows. */
export function TechnicalsSkeleton() {
  return (
    <div className="technicals-skeleton" aria-hidden="true">
      <div className="technicals-perf">
        {Array.from({ length: 5 }, (_, i) => <div key={i}><span className="sk sk-text" style={{ width: "60%", margin: "0 auto" }} /><span className="sk sk-text" style={{ width: "80%", margin: "4px auto 0" }} /></div>)}
      </div>
      {Array.from({ length: 3 }, (_, i) => (
        <div className="technicals-skeleton-row" key={i}>
          <span className="sk sk-text" style={{ width: "35%" }} />
          <span className="sk sk-text" style={{ width: "70%" }} />
        </div>
      ))}
    </div>
  );
}

/** Stand-in for a news section: a heading plus a grid of article cards. */
export function NewsSkeleton({ title = "Stock news", count = 4 }: { title?: string; count?: number }) {
  return (
    <section className="news-section">
      <h2>{title}</h2>
      <div className="news-grid" aria-busy="true">
        {Array.from({ length: count }, (_, i) => (
          <article key={i} aria-hidden="true">
            <span className="sk sk-text" style={{ width: "45%" }} />
            <span className="sk sk-text" style={{ width: "95%", height: "1.1em", marginTop: 8 }} />
            <span className="sk sk-text" style={{ width: "70%", height: "1.1em" }} />
            <span className="sk sk-text" style={{ width: "30%", marginTop: 10 }} />
          </article>
        ))}
      </div>
    </section>
  );
}
