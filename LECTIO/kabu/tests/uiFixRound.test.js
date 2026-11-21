// UI fix round 11-22 (bug hunt findings 1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15):
// the search submits from the text in the box (never a stale highlight), any
// US-shaped ticker can start a report, a failed job stops spinning, the viewer's
// empty state, Q shortcut, single report request and zoom limits, one share link,
// and one progress number on the Reports card and the progress page.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  POPULAR_COMPANIES, buildCompanyIndex, findIndexedTicker, matchCompanyIndex, normalizeUsTicker,
} from '../src/lib/companyIndex.js';
import { copyReportShareLink, reportShareLink, reportViewerPath, SHARE_TOAST } from '../src/lib/reportShareLink.js';

const src = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8');
const bar = src('components/home/SearchBar.jsx');
const gen = src('pages/GenerateReport.jsx');
const viewer = src('pages/ReportViewer.jsx');
const index = buildCompanyIndex(JSON.parse(src('data/companies.json')));

/** A top-level function's source text, from its declaration to its closing brace. */
function fnSource(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  const from = source.lastIndexOf('\n', start) + 1;
  return source.slice(from, source.indexOf('\n}\n', start) + 2).replace(/^export /, '');
}

// The SearchBar's pure helpers, run against the real company list.
const searchHelpers = new Function(
  'MAX_RESULTS', 'matchCompanyIndex', 'POPULAR_COMPANIES', 'normalizeUsTicker', 'findIndexedTicker',
  `${['matchCompanies', 'dropdownRows', 'defaultHighlight', 'pickSubmission'].map((n) => fnSource(bar, n)).join('\n')}
   return { dropdownRows, defaultHighlight, pickSubmission };`,
)(20, matchCompanyIndex, POPULAR_COMPANIES, normalizeUsTicker, findIndexedTicker);
const { dropdownRows, pickSubmission } = searchHelpers;

test('finding 1: a highlight chosen for earlier text is never submitted for new text', () => {
  // "A" highlighted Apple; the box now holds "zzzz" (the highlight is stale).
  const stale = { text: 'A', idx: 0 };
  assert.equal(dropdownRows('A', index)[0].ticker, 'AAPL');
  assert.deepEqual(pickSubmission('zzzz', index, stale), { ticker: 'ZZZZ', name: '' });
  assert.equal(pickSubmission('zzzzzz', index, stale), null, 'not a ticker shape: nothing starts');
  assert.equal(pickSubmission('zz zz', index, stale), null);
  // An out-of-range highlight for the same text is ignored too.
  assert.equal(pickSubmission('KO', index, { text: 'KO', idx: 40 }).ticker, 'KO');
  // A highlight made for this very text is honoured.
  const koRows = dropdownRows('KO', index);
  assert.ok(koRows.length > 1);
  assert.equal(pickSubmission('KO', index, { text: 'KO', idx: 1 }).ticker, koRows[1].ticker);
});

test('finding 1: the submit reads the box itself and the rows are derived in the same render', () => {
  assert.match(bar, /const text = inputRef\.current \? inputRef\.current\.value : query;/);
  assert.match(bar, /const pick = pickSubmission\(text, index, highlight, recentCompanies\);/);
  assert.match(bar, /const highlightIdx = highlight\.text === query && highlight\.idx < filteredCompanies\.length/);
  assert.doesNotMatch(bar, /setFilteredCompanies|filteredCompanies\[highlightIdx\]/, 'no row list set one effect late');
});

test('finding 6: an unlisted US-shaped ticker gets one row and starts a report; listed companies still win', () => {
  assert.deepEqual(dropdownRows('IBM', index).map((r) => [r.ticker, r.name, r.adHoc]), [['IBM', '', true]]);
  assert.deepEqual(dropdownRows(' ibm ', index).map((r) => r.ticker), ['IBM'], 'trimmed, upper-cased');
  assert.deepEqual(dropdownRows('bf-b', index).map((r) => r.ticker), ['BF-B']);
  assert.deepEqual(pickSubmission('IBM', index), { ticker: 'IBM', name: '' }, 'the backend supplies the name');
  assert.deepEqual(pickSubmission('ibm', index), { ticker: 'IBM', name: '' });
  assert.deepEqual(pickSubmission('apple', index), { ticker: 'AAPL', name: 'Apple Inc.' });
  assert.deepEqual(pickSubmission('brk-b', index), { ticker: 'BRK.B', name: 'Berkshire Hathaway Inc.' });
  assert.deepEqual(pickSubmission('aapl, apple', index), { ticker: 'AAPL', name: 'Apple Inc.' });
  assert.deepEqual(dropdownRows('ibm corp', index), [], 'not ticker-shaped: "No results"');
  assert.equal(pickSubmission('ibm corp', index), null);
  assert.equal(pickSubmission('   ', index), null);
  assert.deepEqual(dropdownRows('IBM', null), [], 'nothing offered before the list has loaded');
  assert.match(bar, /\{company\.adHoc \? `Generate a report for \$\{company\.ticker\}` : displayCompanyName\(company\.name\)\}/);
  assert.match(bar, /onChange=\{\(e\) => \{ setQuery\(e\.target\.value\); setError\(null\); wantIndex\(\); \}\}/, 'typing clears an old error');
});

test('finding 4: a failed job has no LIVE step or spinner; the failed step is marked', () => {
  assert.match(gen, /const failed = !noTarget && isError && !isComplete && i === stepIdx;/);
  assert.match(gen, /const active = !noTarget && !isError && i === stepIdx && !isComplete && !isQueued;/);
  assert.match(gen, /\{failed && <span className="ml-auto text-\[10px\] font-semibold text-red-400">Failed<\/span>\}/);
  assert.match(gen, /\{error && error !== status\?\.error && <p/, 'one error line, not the same text twice');
});

test('findings 7 and 12: the ready screen offers "New report" (Reports) and "Home" (#/Home); a re-run only after a warning', () => {
  const ready = gen.slice(gen.indexOf('{/* Bottom actions */}'), gen.indexOf('{/* ━━ ERROR STATE'));
  assert.match(ready, /<Link\s+to="\/Reports"\s+state=\{\{ openContent: true \}\}[\s\S]*?New report\n/);
  assert.match(ready, /\{isWarning && \(\s*<button\s+onClick=\{\(\) => startNewJob\(\)\}[\s\S]*?Run again\n/);
  assert.match(ready, /<Link\s+to="\/Home"[\s\S]*?Home\n/);
  assert.doesNotMatch(ready, /New Report/);
});

test('finding 8: the viewer has no Q shortcut', () => {
  assert.doesNotMatch(viewer, /Query mode/);
  assert.doesNotMatch(viewer, /case "q"/);
});

test('finding 9: the progress page shows the Reports card field: interpolated_progress, else progress, never lower', () => {
  const shownProgress = new Function(`${fnSource(gen, 'shownProgress')}; return shownProgress;`)();
  assert.equal(shownProgress({ progress: 80, interpolated_progress: 83 }, 80), 83);
  assert.equal(shownProgress({ progress: 80 }, 80), 80);
  assert.equal(shownProgress({ progress: 80, interpolated_progress: null }, 80), 80);
  assert.equal(shownProgress({ interpolated_progress: Number.NaN }, 15), 15);
  assert.equal(shownProgress({ interpolated_progress: 130 }, 15), 100);
  assert.equal(shownProgress(null, 0), 0);
  assert.match(gen, /if \(rawPct > maxPctRef\.current\) maxPctRef\.current = rawPct;/);
  assert.match(src('pages/Home.jsx'), /const reportedProgress = Number\(st\.interpolated_progress \?\? st\.progress\);/);
  assert.match(src('pages/Home.jsx'), /\{g\.step\} — \{Math\.round\(g\.progress\)\}%/);
  assert.match(gen, /\{Math\.round\(pct\)\}%/);
});

test('finding 10: a job without a separate name shows its ticker once', () => {
  assert.match(gen, /const headerName = companyName && companyName\.toUpperCase\(\) !== String\(ticker \|\| ""\)\.toUpperCase\(\) \? companyName : ticker;/);
  assert.match(gen, /\{headerName !== ticker && <span className="text-\[#f4f5f7\] font-mono">\{ticker\}<\/span>\}/);
});

test('finding 11: the empty progress page does not call the report a Callisto report', () => {
  assert.match(gen, /Pick a company on the Reports page to generate a research report\./);
  assert.doesNotMatch(gen, /Callisto research report/);
});

test('finding 13: both screens copy the same #/Viewer link with the same toast', () => {
  const report = { url: '/download?inline=1&file=report_KO_0bf03456.html', title: 'Coca Cola Co.', jobId: '0BF034563362401699AC9C3801ED8BBE' };
  assert.equal(reportViewerPath(report, 'http://x.test'),
    '/Viewer?url=%2Fdownload%3Finline%3D1%26file%3Dreport_KO_0bf03456.html&title=Coca+Cola+Co.&jobId=0bf034563362401699ac9c3801ed8bbe');
  assert.equal(reportShareLink(report, { origin: 'http://x.test', pathname: '/' }),
    'http://x.test/#/Viewer?url=%2Fdownload%3Finline%3D1%26file%3Dreport_KO_0bf03456.html&title=Coca+Cola+Co.&jobId=0bf034563362401699ac9c3801ed8bbe');
  assert.equal(reportViewerPath({ url: 'https://evil.test/download?file=report_KO_0bf03456.html' }, 'http://x.test'), null);
  assert.equal(reportViewerPath({ url: '/download?inline=1&file=report_KO_nope.html' }, 'http://x.test'), null);
  assert.match(gen, /const handleShare = \(\) => \{ copyReportShareLink\(viewerReport, toast\); \};/);
  assert.match(viewer, /const handleShare = \(\) => \{ copyReportShareLink\(\{ url, title, jobId: normalizedRequestedJobId \}, deskToast\); \};/);
  assert.doesNotMatch(gen, /mailto:/);
});

test('finding 13: the copy reports success or failure through the toast', async () => {
  const saved = globalThis.window;
  globalThis.window = { location: { origin: 'http://x.test', pathname: '/' } };
  try {
    const seen = [];
    const written = [];
    const ok = await copyReportShareLink({ url: '/download?inline=1&file=report_KO_0bf03456.html' }, (t) => seen.push(t),
      { writeText: (text) => { written.push(text); return Promise.resolve(); } });
    assert.equal(ok, true);
    assert.deepEqual(seen, [SHARE_TOAST]);
    assert.match(written[0], /^http:\/\/x\.test\/#\/Viewer\?url=/);
    const failed = await copyReportShareLink({ url: '/download?inline=1&file=report_KO_0bf03456.html' }, (t) => seen.push(t),
      { writeText: () => Promise.reject(new Error('blocked')) });
    assert.equal(failed, false);
    assert.equal(seen.at(-1).title, 'Copy failed');
  } finally {
    globalThis.window = saved;
  }
});

test('finding 5: without a valid report file the viewer binds nothing and says it could not open the report', () => {
  assert.match(viewer, /\(\) => \(url \? findReportInHistory\(requestedJobId, url\) : null\)/);
  assert.match(viewer, /const statusBindingKey = url && !historyReport && normalizedRequestedJobId/);
  assert.match(viewer, /const noReport = !url \|\| reportUnavailable;\n\s+const shownReport = noReport \? null : reportData;/);
  assert.match(viewer, /const sources = useMemo\(\(\) => shownReport\?\.sources \|\| \[\], \[shownReport\]\);/);
  assert.match(viewer, /This report could not be opened\./);
  assert.doesNotMatch(viewer, /No report URL provided/);
  assert.match(viewer, /\{!noReport && \(<>/, 'the report tools are hidden without a report');
});

test('finding 14: an HTML report is requested once, by the frame (no status pre-fetch)', () => {
  const check = viewer.slice(viewer.indexOf('/* ── Report availability'), viewer.indexOf('const handleFrameLoad'));
  assert.match(check, /if \(!viewUrl \|\| !isPdf\) return undefined;/);
  assert.match(check, /const documentChecked = Boolean\(viewUrl\) && \(!isPdf \|\| documentCheck\.url === viewUrl\);/);
  // The desk style is added to the loaded document; it never touches the src.
  assert.doesNotMatch(fnSource(viewer, 'dressReportFrame'), /\.src\b|location/);
});

test('finding 15: zoom buttons are disabled at 50% and 200%; zoomed in, the sheet keeps its width and the pane scrolls', () => {
  assert.match(viewer, /<button onClick=\{zoomOut\} disabled=\{noReport \|\| atMinZoom\} aria-disabled=\{noReport \|\| atMinZoom \? "true" : undefined\}/);
  assert.match(viewer, /<button onClick=\{zoomIn\} disabled=\{noReport \|\| atMaxZoom\} aria-disabled=\{noReport \|\| atMaxZoom \? "true" : undefined\}/);
  assert.match(viewer, /const atMinZoom = zoom <= MIN_ZOOM;\n\s+const atMaxZoom = zoom >= MAX_ZOOM;/);
  assert.match(viewer, /overflow-x-auto overflow-y-hidden/);
  const zoomedFrameWidth = new Function(`${fnSource(viewer, 'zoomedFrameWidth')}; return zoomedFrameWidth;`)();
  assert.equal(zoomedFrameWidth(2, 0), '50%');
  assert.equal(zoomedFrameWidth(2, 794), 'max(50%, 794px)');
  assert.equal(zoomedFrameWidth(1.5, 793.2), 'max(66.66666666666667%, 794px)');
});

test('the ready screen preview shows its fallback, not raw 404 JSON, when the file is missing', () => {
  assert.match(gen, /if \(contentType && contentType !== "text\/html"\) setPreviewError\(true\);\n\s+else setPreviewLoaded\(true\);/);
});
