import test, { beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  normalizeJobId,
  readActiveReports,
  readReportHistory,
  removeActiveReport,
  upsertActiveReport,
  upsertReportHistory,
} from "../src/lib/reportStorage.js";
import {
  safeExternalUrl,
  safeReportUrl,
} from "../src/lib/safeUrl.js";

class MemoryStorage {
  #values = new Map();
  get length() { return this.#values.size; }
  key(index) { return [...this.#values.keys()][index] ?? null; }
  getItem(key) { return this.#values.has(key) ? this.#values.get(key) : null; }
  setItem(key, value) { this.#values.set(String(key), String(value)); }
  removeItem(key) { this.#values.delete(String(key)); }
  clear() { this.#values.clear(); }
}

beforeEach(() => {
  globalThis.localStorage = new MemoryStorage();
});

// Execute the page's actual non-JSX start/effect bodies with deferred requests.
// This models effect cleanup/replay and successive render closures, without a
// DOM, network, or a duplicate test-only implementation of the start guard.
function startFlowHarness() {
  const source = readFileSync(new URL("../src/pages/GenerateReport.jsx", import.meta.url), "utf8");
  const lifecycle = source.slice(source.indexOf("  const routeVersionRef ="), source.indexOf("  const isComplete ="));
  const start = source.slice(source.indexOf("  /* ── Start job ── */"), source.indexOf("  /* ── Poll status ── */"));
  assert.ok(lifecycle && start, "start/lifecycle source anchors must remain available");
  const request = (overrides = {}) => ({
    queue: ["7203", "6758"], queueIdx: 0, ticker: "7203", companyName: "Toyota",
    mode: "full", jobId: null, jobIdRequested: false, invalidJobId: false, ...overrides,
  });
  let routeRequest = request();
  const state = { ...routeRequest, autoStartAllowed: true, isStarting: false, status: null, error: null };
  const writes = [], navigations = [], requests = [], refs = [];
  const shared = {
    normalizeJobId, upsertActiveReport, removeActiveReport, URLSearchParams,
    statusReceivedAtRef: { current: 0 }, maxPctRef: { current: 0 }, maxStepRef: { current: 0 },
    toLatinName: (name, ticker) => name || ticker,
    navigate: (...args) => navigations.push(args),
    startReport: (payload) => new Promise((resolve, reject) => requests.push({ payload, resolve, reject })),
  };
  for (const key of ["queue", "queueIdx", "ticker", "companyName", "mode", "jobId", "autoStartAllowed", "status", "error", "isStarting", "showSources"]) {
    shared[`set${key[0].toUpperCase()}${key.slice(1)}`] = (value) => {
      state[key] = value;
      writes.push([key, value]);
    };
  }
  const render = () => {
    let cursor = 0;
    const effects = [];
    const scope = {
      ...shared, ...state, routeRequest,
      useRef: (initial) => refs[cursor++] ||= { current: initial },
      useEffect: (setup, deps) => effects.push({ setup, deps }),
    };
    // Only repository-owned, non-JSX code is evaluated; parameters represent
    // one render's immutable values, so late responses retain their own ticker.
    const evaluate = new Function(...Object.keys(scope), `${lifecycle}\n${start}\nreturn { startNewJob, startQueueItem };`);
    return { ...evaluate(...Object.values(scope)), effects };
  };
  let current = render();
  const cleanups = current.effects.map(({ setup }) => setup());
  return {
    state, writes, navigations, requests,
    get current() { return current; },
    unmount() { cleanups.forEach((cleanup) => cleanup?.()); },
    replayEffects() {
      cleanups.forEach((cleanup) => cleanup?.());
      current.effects.forEach(({ setup }, index) => { cleanups[index] = setup(); });
    },
    changeRoute(overrides) {
      routeRequest = request(overrides);
      // Commit the route-sync effect, then render its new state before letting
      // auto-start run. The mount effect does not replay for a query change.
      current = render();
      current.effects.find(({ deps }) => deps[0] === routeRequest).setup();
      current = render();
    },
    rerender() { current = render(); },
  };
}

async function settleStart(request, { reject, jobId = "a".repeat(32) } = {}) {
  if (reject) request.reject(new Error(reject));
  else request.resolve({ job_id: jobId });
  // The async start's catch/finally finish without performing any real fetch.
  await Promise.resolve();
}

test("pending start success after unmount retains the accepted job without navigation or state writes", async () => {
  const flow = startFlowHarness();
  assert.equal(flow.requests.length, 1);
  flow.unmount();
  flow.writes.length = 0;
  await settleStart(flow.requests[0]);
  assert.deepEqual(flow.writes, []);
  assert.deepEqual(flow.navigations, []);
  assert.equal(readActiveReports()[0]?.jobId, "a".repeat(32));
  assert.equal(readActiveReports()[0]?.ticker, "7203");
  await flow.current.startNewJob();
  assert.equal(flow.requests.length, 1, "an unmounted handler cannot retry the paid POST");
});

test("pending start rejection after unmount neither updates error state nor retries", async () => {
  const flow = startFlowHarness();
  flow.unmount();
  flow.writes.length = 0;
  await settleStart(flow.requests[0], { reject: "offline" });
  assert.deepEqual(flow.writes, []);
  assert.deepEqual(flow.navigations, []);
  assert.deepEqual(readActiveReports(), []);
  assert.equal(flow.requests.length, 1);
});

test("Strict Mode effect replay and rapid duplicate starts share the original pending POST", async () => {
  const flow = startFlowHarness();
  flow.replayEffects();
  await flow.current.startNewJob();
  assert.equal(flow.requests.length, 1);
  assert.equal(flow.state.isStarting, true);
  await settleStart(flow.requests[0]);
  assert.equal(flow.state.jobId, "a".repeat(32));
  assert.equal(flow.state.isStarting, false);
  assert.equal(flow.navigations.length, 1);
  assert.match(flow.navigations[0][0], /tickers=7203%2C6758&qi=0/);
  assert.deepEqual(flow.navigations[0][1], { replace: true });
});

test("an older same-route response preserves its job without replacing or unlocking the newer start", async () => {
  const flow = startFlowHarness();
  flow.changeRoute({ ticker: "6758", companyName: "Sony", queueIdx: 1 });
  const newer = flow.current.startNewJob();
  assert.equal(flow.requests.length, 2);
  flow.writes.length = 0;
  await settleStart(flow.requests[0]);
  assert.deepEqual(flow.writes, []);
  assert.deepEqual(flow.navigations, []);
  await flow.current.startNewJob();
  assert.equal(flow.requests.length, 2, "old finally must not release the newer pending guard");
  await settleStart(flow.requests[1], { jobId: "b".repeat(32) });
  await newer;
  assert.equal(flow.state.jobId, "b".repeat(32));
  assert.match(flow.navigations[0][0], /ticker=6758/);
  assert.equal(readActiveReports().length, 2);
});

test("an older same-route rejection cannot overwrite the new request's state", async () => {
  const flow = startFlowHarness();
  flow.changeRoute({ ticker: "6758", companyName: "Sony" });
  const newer = flow.current.startNewJob();
  flow.writes.length = 0;
  await settleStart(flow.requests[0], { reject: "old request failed" });
  assert.deepEqual(flow.writes, []);
  assert.deepEqual(flow.navigations, []);
  await settleStart(flow.requests[1], { jobId: "b".repeat(32) });
  await newer;
  assert.equal(flow.state.error, null);
});

test("failed start is terminal until explicit retry, which retains its batch URL", async () => {
  const flow = startFlowHarness();
  await settleStart(flow.requests[0], { reject: "offline" });
  assert.equal(flow.state.status.status, "error");
  assert.equal(flow.state.isStarting, false);
  flow.rerender();
  flow.current.effects.at(-1).setup();
  assert.equal(flow.requests.length, 1, "failed starts must not silently retry");
  const retry = flow.current.startNewJob();
  assert.equal(flow.requests.length, 2);
  await settleStart(flow.requests[1], { jobId: "b".repeat(32) });
  await retry;
  assert.match(flow.navigations[0][0], /tickers=7203%2C6758&qi=0/);
});

test("batch advance invalidates its pending predecessor and starts only the selected company", async () => {
  const flow = startFlowHarness();
  flow.current.startQueueItem(1);
  flow.rerender();
  const next = flow.current.startNewJob();
  assert.deepEqual(flow.requests.map(({ payload }) => payload.stock_code), ["7203", "6758"]);
  flow.writes.length = 0;
  await settleStart(flow.requests[0]);
  assert.deepEqual(flow.writes, []);
  assert.deepEqual(flow.navigations, []);
  await settleStart(flow.requests[1], { jobId: "b".repeat(32) });
  await next;
  assert.match(flow.navigations[0][0], /tickers=7203%2C6758&qi=1/);
});

test("invalid start acknowledgement stays terminal and never persists an invented job", async () => {
  const flow = startFlowHarness();
  await settleStart(flow.requests[0], { jobId: "not-a-job" });
  assert.equal(flow.state.error, "Job ID missing");
  assert.equal(flow.state.status.status, "error");
  assert.equal(flow.state.isStarting, false);
  assert.deepEqual(readActiveReports(), []);
  assert.deepEqual(flow.navigations, []);
});

test("home poll promotes terminal jobs that produced only a PDF", () => {
  // A complete/warning job whose only artifact is pdf_file must leave the
  // poll loop; requiring html_file would poll such a job forever.
  const homeSource = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../src/pages/Home.jsx"),
    "utf8",
  );
  assert.match(
    homeSource,
    /\(st\.status === "complete" \|\| st\.status === "warning"\) && \(st\.html_file \|\| st\.pdf_file\)/,
  );
});

test("normalizes only a complete hexadecimal report job id", () => {
  assert.equal(normalizeJobId("A".repeat(32)), "a".repeat(32));
  assert.equal(normalizeJobId("a".repeat(31)), null);
  assert.equal(normalizeJobId("g".repeat(32)), null);
  assert.equal(normalizeJobId("../../status/" + "a".repeat(32)), null);
});

test("accepts only HTTP(S) external URLs and canonical report downloads", () => {
  assert.equal(safeExternalUrl("javascript:alert(1)"), null);
  assert.equal(safeExternalUrl("data:text/html,hello"), null);
  assert.equal(safeExternalUrl("https://user:secret@example.com/a"), null);
  assert.equal(safeExternalUrl("https://example.com/a")?.startsWith("https://example.com/a"), true);

  const report = "/download?t=expired&inline=1&file=report_7203_deadbeef.html";
  assert.equal(
    safeReportUrl(report, "http://localhost"),
    "/download?inline=1&file=report_7203_deadbeef.html",
  );
  assert.equal(safeReportUrl("/status/" + "a".repeat(32), "http://localhost"), null);
  assert.equal(safeReportUrl("/download?file=../user_data.json", "http://localhost"), null);
  assert.equal(safeReportUrl("https://example.com/download?file=report_7203_deadbeef.html", "http://localhost"), null);
});

test("migrates report history to independent per-job records", () => {
  const first = "a".repeat(32);
  const second = "b".repeat(32);
  localStorage.setItem("reports_history", JSON.stringify([
    { jobId: first, ticker: "7203", html_file: "report_7203_aaaaaaaa.html", finishedAt: "2026-01-01" },
    { jobId: second, ticker: "6758", html_file: "report_6758_bbbbbbbb.html", finishedAt: "2026-01-02" },
  ]));

  assert.deepEqual(readReportHistory().map((entry) => entry.jobId), [second, first]);
  assert.equal(localStorage.getItem("reports_history"), null);

  upsertReportHistory({
    jobId: first,
    ticker: "7203",
    companyName: "Toyota",
    html_file: "report_7203_aaaaaaaa.html",
    finishedAt: "2026-01-03",
  });
  const after = readReportHistory();
  assert.equal(after.length, 2);
  assert.equal(after.find((entry) => entry.jobId === first)?.companyName, "Toyota");
  assert.equal(after.some((entry) => entry.jobId === second), true);
});

