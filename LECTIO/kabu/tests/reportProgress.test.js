import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { reportProgress, STATUS_FRESH_MS } from "../src/lib/reportProgress.js";

const fresh = { receivedAt: 1_000_000, now: 1_000_000 };
const status = (overrides = {}) => ({
  status: "running", step: "Data Fetch", progress: 15, interpolated_progress: 24,
  message: "Fetching EDINET filings", edinet_count: 6, eta_seconds: 31,
  ...overrides,
});

test("cold EDINET search displays actual 15% milestone, message and discoveries, not invented24%", () => {
  const data = status();
  const before = structuredClone(data);
  const view = reportProgress(data, fresh);
  assert.deepEqual(view, {
    progress: 15, message: "Fetching EDINET filings", etaSeconds: null, filingsFound: 6,
  });
  assert.deepEqual(data, before);
  // Time alone neither manufactures progress nor changes the claimed activity.
  const later = reportProgress(data, { ...fresh, now: fresh.now + 145_000 });
  assert.equal(later.progress, 15);
  assert.equal(later.message, view.message);
  assert.equal(later.etaSeconds, null);
});

test("new actual filing count is shown without implying completion", () => {
  assert.equal(reportProgress(status({ edinet_count: 1 }), fresh).filingsFound, 1);
  assert.equal(reportProgress(status({ edinet_count: 6 }), fresh).filingsFound, 6);
  assert.equal(reportProgress(status({ edinet_count: 6 }), fresh).progress, 15);
});

test("later-stage estimate tracks both upward and downward backend corrections", () => {
  const draft = status({ step: "Drafting", message: "Writing report", progress: 80, eta_seconds: 20 });
  assert.equal(reportProgress(draft, fresh).etaSeconds, 20);
  assert.equal(reportProgress({ ...draft, eta_seconds: 90 }, fresh).etaSeconds, 90);
  assert.equal(reportProgress({ ...draft, eta_seconds: 12 }, fresh).etaSeconds, 12);
  // Merely waiting does not run a second countdown against the snapshot.
  assert.equal(reportProgress(draft, { ...fresh, now: fresh.now + 5000 }).etaSeconds, 20);
});

test("ETA is hidden when request failed, snapshot is stale, or receipt time is missing", () => {
  const draft = status({ step: "Drafting" });
  assert.equal(reportProgress(draft, { ...fresh, hasError: true }).etaSeconds, null);
  assert.equal(reportProgress(draft, { ...fresh, now: fresh.now + STATUS_FRESH_MS + 1 }).etaSeconds, null);
  assert.equal(reportProgress(draft, { now: fresh.now }).etaSeconds, null);
  assert.equal(reportProgress(draft, { ...fresh, now: fresh.receivedAt - 1 }).etaSeconds, null);
});

for (const step of ["Starting", "Company Info", "Data Fetch", "Extraction"]) {
  test(`no exact numeric remaining-time promise during ${step}`, () => {
    assert.equal(reportProgress(status({ step }), fresh).etaSeconds, null);
  });
}

for (const state of ["queued", "complete", "warning", "error"]) {
  test(`no running ETA for ${state}`, () => {
    assert.equal(reportProgress(status({ status: state, step: "Drafting" }), fresh).etaSeconds, null);
  });
}

test("empty, malformed or unavailable fields never invent current work or a countdown", () => {
  assert.deepEqual(reportProgress(null, fresh), {
    progress: 0, message: "Waiting for the next report status update…", etaSeconds: null, filingsFound: null,
  });
  assert.equal(reportProgress({ status: "queued", message: " " }, fresh).message, "Queued — waiting for a report worker.");
  for (const value of [undefined, null, "31", NaN, Infinity, -1, 0]) {
    assert.equal(reportProgress(status({ step: "Drafting", eta_seconds: value }), fresh).etaSeconds, null);
  }
  for (const value of [undefined, null, "6", NaN, Infinity, -1, 0, 1.5]) {
    assert.equal(reportProgress(status({ edinet_count: value }), fresh).filingsFound, null);
  }
  assert.equal(reportProgress(status({ progress: NaN }), fresh).progress, 0);
  assert.equal(reportProgress(status({ progress: 130 }), fresh).progress, 100);
  assert.equal(reportProgress(status({ progress: -2 }), fresh).progress, 0);
  assert.equal(reportProgress(status({ step: "Drafting", eta_seconds: 900 }), fresh).etaSeconds, 600);
});

test("rendered page uses shared truth mapping and retains stale-poll guard and actual elapsed clock", () => {
  const source = readFileSync(new URL("../src/pages/GenerateReport.jsx", import.meta.url), "utf8");
  assert.match(source, /const progressView = reportProgress\(status,/);
  assert.match(source, /const stageMsg = progressView\.message/);
  // The shown number is the same field as the Reports card's (UI fix round 11-22):
  // interpolated_progress when sent, else progress; see uiFixRound.test.js.
  assert.match(source, /const rawPct = shownProgress\(status, progressView\.progress\)/);
  assert.match(source, /if \(dead\) return;\s*statusReceivedAtRef\.current = Date\.now\(\)/);
  assert.match(source, /setElapsed\(Math\.max\(0, Math\.floor\(\(end\.getTime\(\) - new Date\(createdAt\)\.getTime\(\)\) \/ 1000\)\)\)/);
  assert.match(source, /reported progress/);
  assert.match(source, /SEC filing\{progressView\.filingsFound === 1/);
  assert.doesNotMatch(source, /EDINET/);
  assert.match(source, /Est\. remaining/);
  assert.doesNotMatch(source, /STAGE_MESSAGES|stageMsgIdx|countdownRef|serverEtaRef/);
});
