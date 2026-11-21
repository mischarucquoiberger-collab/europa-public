"use client";

/**
 * Technicals card for the desk rail.
 *
 * Loads one year of daily bars for the previewed ticker and shows the kind of
 * at-a-glance signals TradingView puts beside a chart:
 *   - Performance over 1W / 1M / 3M / YTD / 1Y
 *   - Trend: price vs. the 20, 50 and 200-day moving averages
 *   - Momentum: 14-day RSI
 *   - 52-week position: distance from the yearly high and low
 *   - Risk: annualised volatility over the last 30 sessions
 *   - Activity: today's volume vs. the 30-day average (stocks/ETFs only)
 *
 * The maths is in small pure functions below, so each metric can be
 * changed or removed on its own.
 */

import { useEffect, useState } from "react";
import type { Point } from "@/lib/massive";
import { TechnicalsSkeleton } from "./skeletons";

const DAY = 86_400_000;

// ---------- calculations ----------

/** Percentage change from `from` to `to`. */
const pctChange = (from: number, to: number) => (to / from - 1) * 100;

/** Close on or just before `time` (points are sorted oldest → newest). */
function closeAt(points: Point[], time: number) {
  let found: Point | undefined;
  for (const p of points) {
    if (p.t > time) break;
    found = p;
  }
  return found?.c;
}

/** Return since `daysAgo` calendar days before the latest bar. */
function periodReturn(points: Point[], daysAgo: number) {
  const last = points.at(-1);
  if (!last) return null;
  const target = last.t - daysAgo * DAY;
  // If history starts a few days after the target (weekends, holidays,
  // API window edges), use the first bar rather than showing nothing.
  const start = closeAt(points, target) ?? (points[0].t - target <= 7 * DAY ? points[0].c : undefined);
  return start ? pctChange(start, last.c) : null;
}

/** Return since the last close of the previous calendar year. */
function ytdReturn(points: Point[]) {
  const last = points.at(-1);
  if (!last) return null;
  const jan1 = Date.UTC(new Date(last.t).getUTCFullYear(), 0, 1);
  const start = closeAt(points, jan1 - 1);
  return start ? pctChange(start, last.c) : null;
}

/** Simple moving average of the last `length` closes. */
function sma(points: Point[], length: number) {
  if (points.length < length) return null;
  const window = points.slice(-length);
  return window.reduce((sum, p) => sum + p.c, 0) / length;
}

/** Wilder's 14-day Relative Strength Index (0–100). */
function rsi(points: Point[], length = 14) {
  if (points.length <= length) return null;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i < points.length; i++) {
    const diff = points[i].c - points[i - 1].c;
    const up = Math.max(diff, 0);
    const down = Math.max(-diff, 0);
    if (i <= length) {
      gain += up / length;
      loss += down / length;
    } else {
      gain = (gain * (length - 1) + up) / length;
      loss = (loss * (length - 1) + down) / length;
    }
  }
  if (loss === 0) return 100;
  return 100 - 100 / (1 + gain / loss);
}

/** Annualised standard deviation of daily returns over the last `length` sessions. */
function volatility(points: Point[], length = 30) {
  const window = points.slice(-(length + 1));
  if (window.length < 3) return null;
  const returns = window.slice(1).map((p, i) => Math.log(p.c / window[i].c));
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((a, r) => a + (r - mean) ** 2, 0) / (returns.length - 1);
  return Math.sqrt(variance) * Math.sqrt(252) * 100;
}

/** Latest volume divided by the average of the previous `length` sessions. */
function relativeVolume(points: Point[], length = 30) {
  const last = points.at(-1);
  const prior = points.slice(-(length + 1), -1).filter((p) => p.v);
  if (!last?.v || prior.length < 5) return null;
  const average = prior.reduce((sum, p) => sum + (p.v ?? 0), 0) / prior.length;
  return last.v / average;
}

// ---------- labels ----------

const signed = (n: number) => (n > 0 ? "+" : "") + n.toFixed(2) + "%";
const tone = (n: number | null) => (n === null ? "" : n < 0 ? "down" : "up");

function rsiLabel(value: number) {
  if (value >= 70) return "Overbought";
  if (value <= 30) return "Oversold";
  return "Neutral";
}

function trendLabel(above: number, total: number) {
  if (total === 0) return "Not enough history";
  if (above === total) return "Strong uptrend";
  if (above === 0) return "Strong downtrend";
  return above > total / 2 ? "Leaning up" : "Leaning down";
}

// ---------- component ----------

type Props = {
  /** Ticker to load, e.g. "SPY" or "I:NDX". */
  ticker: string;
  /** Points to use when the API is in sample mode (no key configured). */
  fallback: Point[];
};

export default function Technicals({ ticker, fallback }: Props) {
  const [state, setState] = useState<{ ticker: string; points: Point[]; sample: boolean } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/market?section=chart&range=1Y&ticker=${encodeURIComponent(ticker)}`, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data) => {
        const sample = data.mode === "sample";
        setState({ ticker, points: sample ? fallback : data.points ?? [], sample });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ ticker, points: [], sample: false });
      });
    return () => controller.abort();
    // `fallback` is regenerated each render; only refetch when the ticker changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  const name = ticker.replace("I:", "");
  const loading = state?.ticker !== ticker;
  // While a new ticker loads, keep the previous figures on screen (dimmed) so the
  // card doesn't collapse and reflow. Only the very first load shows skeletons.
  const points = state?.points ?? [];
  const last = points.at(-1);

  const header = (
    <header>
      <h2>{name} technicals</h2>
      <p>Daily bars · 1 year{state?.sample && !loading ? " · Sample" : ""}</p>
    </header>
  );

  if (!last) {
    return (
      <section className="technicals" aria-busy={loading}>
        {header}
        {loading ? <TechnicalsSkeleton/> : <p className="technicals-empty">No price history available.</p>}
      </section>
    );
  }

  // Performance
  const performance: [string, number | null][] = [
    ["1W", periodReturn(points, 7)],
    ["1M", periodReturn(points, 30)],
    ["3M", periodReturn(points, 90)],
    ["YTD", ytdReturn(points)],
    ["1Y", periodReturn(points, 365)],
  ];

  // Trend vs. moving averages
  const averages = ([20, 50, 200] as const)
    .map((length) => ({ length, value: sma(points, length) }))
    .filter((a): a is { length: 20 | 50 | 200; value: number } => a.value !== null);
  const above = averages.filter((a) => last.c >= a.value).length;

  // 52-week position
  const high = Math.max(...points.map((p) => p.h ?? p.c));
  const low = Math.min(...points.map((p) => p.l ?? p.c));
  const position = high === low ? 50 : ((last.c - low) / (high - low)) * 100;

  const momentum = rsi(points);
  const vol = volatility(points);
  const relVol = relativeVolume(points);

  return (
    <section className="technicals" aria-busy={loading} data-loading={loading}>
      {header}

      <div className="technicals-perf" role="list" aria-label="Performance">
        {performance.map(([label, value]) => (
          <div role="listitem" key={label}>
            <span>{label}</span>
            <b className={tone(value)}>{value === null ? "—" : signed(value)}</b>
          </div>
        ))}
      </div>

      {/* "wide" rows span the full width; RSI, volatility and volume share one row. */}
      <dl className="technicals-list">
        <div className="wide">
          <dt>Trend vs. moving averages</dt>
          <dd className="technicals-trend">
            <strong>{trendLabel(above, averages.length)}</strong>
            <span className="technicals-chips">
              {averages.map((a) => (
                <span
                  key={a.length}
                  className={last.c >= a.value ? "up" : "down"}
                  title={`${a.length}-day average ${a.value.toFixed(2)}`}
                >
                  {last.c >= a.value ? "▲" : "▼"} {a.length}D
                </span>
              ))}
            </span>
          </dd>
        </div>

        <div className="wide">
          <dt>52-week range</dt>
          <dd>
            <strong className={tone(pctChange(high, last.c))}>{signed(pctChange(high, last.c))}</strong> from high ·{" "}
            <strong className={tone(pctChange(low, last.c))}>{signed(pctChange(low, last.c))}</strong> from low
            <span className="technicals-meter" aria-hidden="true">
              <i style={{ left: `${position}%` }} />
            </span>
          </dd>
        </div>

        {momentum !== null && (
          <div>
            <dt>RSI (14)</dt>
            <dd>
              <strong>{momentum.toFixed(0)}</strong> · {rsiLabel(momentum)}
            </dd>
          </div>
        )}

        {vol !== null && (
          <div>
            <dt>Volatility (30D)</dt>
            <dd>
              <strong>{vol.toFixed(1)}%</strong> annualised
            </dd>
          </div>
        )}

        {relVol !== null && (
          <div>
            <dt>Relative volume</dt>
            <dd>
              <strong>{relVol.toFixed(2)}×</strong> vs. 30-day avg
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
