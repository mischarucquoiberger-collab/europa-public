// Reports page, viewer and report-access fixes (QA G4): Recent rows from the
// account's server list, a shared Viewer link rebound through /status, the
// unavailable-report state, fit-to-width on tablets, and the search box's
// ticker-then-name queries, word ranking and display case.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { mergeReportHistory, serverReportEntry } from '../src/lib/reportStorage.js';
import { buildCompanyIndex, displayCompanyName, matchCompanyIndex } from '../src/lib/companyIndex.js';

const require = createRequire(import.meta.url);
const src = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8');
const JOB_A = 'a'.repeat(32);
const JOB_B = 'b'.repeat(32);
const JOB_C = 'c'.repeat(32);

// ── Recent: server rows merged with this browser's history ──────────────────

const serverRow = (jobId, extra = {}) => ({
  job_id: jobId, ticker: '7203', company_name: 'Toyota Motor Corporation',
  html_file: `report_7203_${jobId.slice(0, 8)}.html`, pdf_file: `report_7203_${jobId.slice(0, 8)}.pdf`,
  status: 'complete', created_at: '2026-10-01T09:00:00', finished_at: '2026-10-01T10:00:00',
  source_count: 42, ...extra,
});

test('a server row becomes a viewable Recent entry with its source count', () => {
  const entry = serverReportEntry(serverRow(JOB_A));
  assert.equal(entry.jobId, JOB_A);
  assert.equal(entry.ticker, '7203');
  assert.equal(entry.companyName, 'Toyota Motor Corporation');
  assert.equal(entry.html, '/download?file=report_7203_aaaaaaaa.html');
  assert.equal(entry.pdf, '/download?file=report_7203_aaaaaaaa.pdf');
  assert.equal(entry.finishedAt, '2026-10-01T10:00:00');
  assert.equal(entry.sourceCount, 42);
  assert.deepEqual(entry.sources, []);
  assert.equal(entry.status, 'complete');
  assert.equal(serverReportEntry(serverRow(JOB_A, { status: 'warning' })).status, 'warning');
});

test('unusable server rows are dropped', () => {
  assert.equal(serverReportEntry(null), null);
  assert.equal(serverReportEntry(serverRow('not-a-job')), null);
  assert.equal(serverReportEntry(serverRow(JOB_A, { html_file: null, pdf_file: null })), null);
  assert.equal(serverReportEntry(serverRow(JOB_A, { html_file: '../secret.html', pdf_file: null })), null);
});

test('merge: one row per jobId, the local row wins, newest first', () => {
  const local = [{ jobId: JOB_B, ticker: '6758', finishedAt: '2026-10-02T10:00:00', sources: [{ title: 's' }],
    html: '/download?file=report_6758_bbbbbbbb.html' }];
  const merged = mergeReportHistory(local, [
    serverRow(JOB_A),
    serverRow(JOB_B, { ticker: '9999', finished_at: '2026-09-01T00:00:00' }),
    serverRow(JOB_C, { finished_at: '2026-10-03T10:00:00' }),
    { job_id: 'junk' },
  ]);
  assert.deepEqual(merged.map((row) => row.jobId), [JOB_C, JOB_B, JOB_A]);
  assert.equal(merged[1].ticker, '6758', 'the local row is kept for a jobId both sides have');
  assert.equal(merged[1].sources.length, 1);
  assert.deepEqual(mergeReportHistory(local, null).map((row) => row.jobId), [JOB_B], 'no server rows: local only');
  assert.equal(mergeReportHistory([], Array.from({ length: 60 }, (_, i) => serverRow(i.toString(16).padStart(32, '0')))).length, 50);
});

test('Home merges /api/reports/mine into Recent and degrades silently', () => {
  const home = src('pages/Home.jsx');
  assert.match(home, /await fetch\("\/api\/reports\/mine", \{ signal \}\)/);
  assert.match(home, /if \(!res\.ok\) return \[\];/);
  assert.match(home, /const recentRows = useMemo\(\(\) => mergeReportHistory\(history, serverRows\), \[history, serverRows\]\);/);
  assert.match(home, /\.catch\(\(\) => \{ \/\* Recent falls back to this browser's history\. \*\/ \}\)/);
  // No "first report" flash on a new device while its server list is loading.
  assert.match(home, /\{recentRows\.length === 0 && serverListSettled && \(/);
  assert.match(home, /setTimeout\(\(\) => setServerListSettled\(true\), 1500\)/);
  // One row per company (newest run), 12 companies at most.
  assert.match(home, /groupRecentByTicker\(recentRows, 12\)/);
  assert.match(home, /\{recentGroups\.map\(/);
  assert.doesNotMatch(home, /\{history\.slice\(0, 12\)/);
  assert.match(home, /aria-label=\{`View \$\{sourceCount\} sources`\}/);
  // The warning badge sits in the name's flexible slot, before the fixed ticker column.
  const badge = home.indexOf('aria-label={`Report warning: ${warningText}`}');
  const ticker = home.indexOf('{/* Ticker */}');
  assert.ok(badge > 0 && ticker > badge, 'badge renders before the ticker column');
});

// ── Viewer: a shared link rebinds through the owner-scoped /status ───────────

const viewerPath = fileURLToPath(new URL('../src/pages/ReportViewer.jsx', import.meta.url));
const viewerSource = readFileSync(viewerPath, 'utf8');
const REAL = {
  '@/lib/reportStorage': fileURLToPath(new URL('../src/lib/reportStorage.js', import.meta.url)),
  '@/lib/safeUrl': fileURLToPath(new URL('../src/lib/safeUrl.js', import.meta.url)),
  '@/lib/accountStorage': fileURLToPath(new URL('../src/lib/accountStorage.js', import.meta.url)),
};
const importedNames = {};
for (const [, clause, from] of viewerSource.matchAll(/import\s+([\s\S]*?)\s+from\s+["']([^"']+)["']/g)) {
  importedNames[from] = (clause.match(/\{([\s\S]*)\}/)?.[1] || '').split(',').map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean);
}
const compiled = await build({
  stdin: { contents: `export { reportEntryFromStatus } from ${JSON.stringify(viewerPath)};`,
    resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', logLevel: 'silent',
  external: ['react', 'react/*'], loader: { '.css': 'empty' },
  plugins: [{
    name: 'viewer-stubs',
    setup(builder) {
      builder.onResolve({ filter: /.*/ }, ({ path, importer }) => {
        if (importer !== viewerPath) return undefined;
        if (path === 'react' || path.startsWith('react/')) return { path, external: true };
        if (REAL[path]) return { path: REAL[path] };
        return { path, namespace: 'stub' };
      });
      builder.onLoad({ filter: /.*/, namespace: 'stub' }, ({ path }) => ({
        contents: ['function Stub() { return null; }', 'export default Stub;',
          ...(importedNames[path] || []).map((n) => `export const ${n} = Stub;`)].join('\n'),
        loader: 'js',
      }));
    },
  }],
});
const mod = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, mod, mod.exports);
const { reportEntryFromStatus } = mod.exports;

const status = (extra = {}) => ({
  job_id: JOB_A, status: 'complete', stock_code: '7203', company_name: 'Toyota Motor Corporation',
  html_file: 'report_7203_aaaaaaaa.html', pdf_file: 'report_7203_aaaaaaaa.pdf', finished_at: '2026-10-01T10:00:00',
  sources: [{ type: 'edinet', title: 'Annual report', url: 'https://disclosure2.edinet-fsa.go.jp/x' }], ...extra,
});
const viewUrl = '/download?file=report_7203_aaaaaaaa.html&inline=1';

test('a finished report of this account rebuilds the ticker, PDF, sources and finish time', () => {
  const entry = reportEntryFromStatus(status(), JOB_A, viewUrl);
  assert.equal(entry.jobId, JOB_A);
  assert.equal(entry.ticker, '7203');
  assert.equal(entry.pdf, '/download?file=report_7203_aaaaaaaa.pdf');
  assert.equal(entry.sources.length, 1);
  assert.equal(entry.finishedAt, '2026-10-01T10:00:00');
  assert.ok(reportEntryFromStatus(status({ status: 'warning' }), JOB_A, viewUrl));
});

test('no binding for another job, another file, or an unfinished job', () => {
  assert.equal(reportEntryFromStatus(status({ job_id: JOB_B }), JOB_A, viewUrl), null);
  assert.equal(reportEntryFromStatus(status(), JOB_A, '/download?file=report_7203_bbbbbbbb.html&inline=1'), null);
  assert.equal(reportEntryFromStatus(status({ status: 'running' }), JOB_A, viewUrl), null);
  assert.equal(reportEntryFromStatus(null, JOB_A, viewUrl), null);
  assert.equal(reportEntryFromStatus(status(), 'bad', viewUrl), null);
});

test('the Viewer waits for /status before calling a shared link a mismatch', () => {
  assert.match(viewerSource, /getStatus\(normalizedRequestedJobId\)/);
  assert.match(viewerSource, /const bindingPending = Boolean\(statusBindingKey && !statusEntry\);/);
  assert.match(viewerSource, /const bindingMismatch = Boolean\(url && requestedJobId && \(!normalizedRequestedJobId \|\| \(!reportData && !bindingPending\)\)\);/);
  assert.match(viewerSource, /const jobId = bindingMismatch \? null : bindingPending \? null :/);
  assert.match(viewerSource, /const notesKey = !bindingMismatch && fileName && !bindingPending/);
});

test('a missing report shows the unavailable state, not the raw 404 JSON', () => {
  // HTML: the frame's own (single) request; a non-HTML answer is the 404 JSON.
  assert.match(viewerSource, /if \(contentType && contentType !== "text\/html"\) \{\s*setDocumentCheck\(\{ url: viewUrl, available: false \}\);/);
  // PDF (an <object>, unreadable): the status is asked first.
  assert.match(viewerSource, /if \(!viewUrl \|\| !isPdf\) return undefined;/);
  assert.match(viewerSource, /fetch\(viewUrl, \{ credentials: "same-origin", cache: "no-store", signal: controller\.signal \}\)/);
  assert.match(viewerSource, /This report is unavailable or was deleted\./);
  assert.match(viewerSource, /Back to Reports\n/);
  const frame = viewerSource.indexOf('ref={reportFrameRef}');
  const gate = viewerSource.indexOf(') : !reportReady ? (');
  assert.ok(gate > 0 && gate < frame, 'the frame loads only after the check');
  assert.match(viewerSource, /<button onClick=\{handlePrint\} disabled=\{noReport\}/);
  assert.match(viewerSource, /<button onClick=\{handleShare\} disabled=\{noReport\}/);
  assert.match(viewerSource, /<button onClick=\{zoomIn\} disabled=\{noReport \|\| atMaxZoom\}/);
  assert.match(viewerSource, /if \(!viewUrl \|\| noReport\) return;/);
});

test('tablet widths scale the A4 frame to fit', () => {
  assert.match(viewerSource, /onLoad=\{handleFrameLoad\}/);
  assert.match(viewerSource, /setFrameLoaded\(true\);\n\s+measureFit\(\);/);
  assert.match(viewerSource, /const frameZoom = isPdf \? zoom : \+\(zoom \* fitZoom\)\.toFixed\(3\);/);
  assert.match(viewerSource, /transform: `scale\(\$\{frameZoom\}\)`/);
  assert.match(viewerSource, /new ResizeObserver\(\(\) => measureFit\(\)\)/);
});

// ── Search: 'AAPL Apple', word ranking, display case ──────────────────────

const index = buildCompanyIndex(JSON.parse(src('data/companies.json')));
const tickers = (q, n = 5) => matchCompanyIndex(index, q.trim().toLowerCase(), n).map((c) => c.ticker);

test("a symbol followed by a name (the placeholder's own format) finds the company", () => {
  assert.deepEqual(tickers('aapl apple'), ['AAPL']);
  assert.deepEqual(tickers('NVDA   NVIDIA Corporation'), ['NVDA']);
  assert.deepEqual(tickers('crox, crocs'), ['CROX']);
  assert.equal(tickers('aapl')[0], 'AAPL');
});

test("'bank of' ranks Bank of America by whole first words; a half word still finds it", () => {
  assert.equal(tickers('bank of')[0], 'BAC');
  assert.equal(tickers('bank of a')[0], 'BAC');
  assert.equal(tickers('eli lilly')[0], 'LLY');
  assert.equal(tickers('walt disney')[0], 'DIS', 'a later word');
  assert.equal(tickers('planet fit')[0], 'PLNT');
});

test('the search label no longer promises EDINET codes', () => {
  const bar = src('components/home/SearchBar.jsx');
  assert.match(bar, /aria-label="Search company by ticker or name"/);
  assert.doesNotMatch(bar, /EDINET code/);
  assert.match(bar, /\{company\.adHoc \? `Generate a report for \$\{company\.ticker\}` : displayCompanyName\(company\.name\)\}/);
});

test('display case: capitals become title case, acronyms and mixed case stay', () => {
  assert.equal(displayCompanyName('TOYOTA MOTOR CORPORATION'), 'Toyota Motor Corporation');
  assert.equal(displayCompanyName('SONY GROUP CORPORATION'), 'Sony Group Corporation');
  assert.equal(displayCompanyName('DAIWA HOUSE INDUSTRY CO.,LTD.'), 'Daiwa House Industry Co., Ltd.');
  assert.equal(displayCompanyName('KDDI CORPORATION'), 'KDDI Corporation');
  assert.equal(displayCompanyName('NHK SPRING CO.,LTD.'), 'NHK Spring Co., Ltd.');
  assert.equal(displayCompanyName('ANA HOLDINGS INC.'), 'ANA Holdings Inc.');
  assert.equal(displayCompanyName('BANK OF THE RYUKYUS,LIMITED'), 'Bank of the Ryukyus, Limited');
  assert.equal(displayCompanyName('S&B FOODS INC.'), 'S&B Foods Inc.');
  assert.equal(displayCompanyName('Mitsubishi UFJ Financial Group,Inc.'), 'Mitsubishi UFJ Financial Group, Inc.');
  assert.equal(displayCompanyName('SoftBank Group Corp.'), 'SoftBank Group Corp.');
  assert.equal(displayCompanyName('en Inc.'), 'en Inc.');
  assert.equal(displayCompanyName(''), '');
  // Initials that happen to contain a vowel, and an index name with a suffix.
  assert.equal(displayCompanyName('OSG CORPORATION CO.,LTD.'), 'OSG Corporation Co., Ltd.');
  assert.equal(displayCompanyName('PCA CORPORATION'), 'PCA Corporation');
  assert.equal(displayCompanyName('NEXT FUNDS TOPIX-17 ELECTRIC POWER & GAS ETF'), 'Next Funds TOPIX-17 Electric Power & Gas ETF');
});
