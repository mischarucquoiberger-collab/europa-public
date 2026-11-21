// Beta polish (G3-reports-query): Reports > Recent shows one row per company
// (newest run + a "×N runs" badge), the hover slide moves only the name block,
// a warning's reason is readable without a tooltip, "/" focuses the search,
// the Query eyebrow, and the chat dock's single "recent chats" toggle name.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const require = createRequire(import.meta.url);
const src = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8');
const homePath = fileURLToPath(new URL('../src/pages/Home.jsx', import.meta.url));
const homeSource = readFileSync(homePath, 'utf8');

// Bundle Home.jsx's pure export with every UI import stubbed.
const importedNames = {};
for (const [, clause, from] of homeSource.matchAll(/import\s+([\s\S]*?)\s+from\s+["']([^"']+)["']/g)) {
  importedNames[from] = (clause.match(/\{([\s\S]*)\}/)?.[1] || '').split(',')
    .map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean);
}
const compiled = await build({
  stdin: { contents: `export { groupRecentByTicker } from ${JSON.stringify(homePath)};`,
    resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', logLevel: 'silent',
  external: ['react', 'react/*'], loader: { '.css': 'empty' },
  plugins: [{
    name: 'home-stubs',
    setup(b) {
      b.onResolve({ filter: /.*/ }, ({ path, importer }) => {
        if (importer !== homePath) return undefined;
        if (path === 'react' || path.startsWith('react/')) return { path, external: true };
        return { path, namespace: 'stub' };
      });
      b.onLoad({ filter: /.*/, namespace: 'stub' }, ({ path }) => ({
        contents: ['function Stub() { return null; }', 'export default Stub;',
          ...(importedNames[path] || []).map((n) => `export const ${n} = Stub;`)].join('\n'),
        loader: 'js',
      }));
    },
  }],
});
const mod = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, mod, mod.exports);
const { groupRecentByTicker } = mod.exports;

const row = (jobId, ticker, finishedAt) => ({ jobId, ticker, companyName: `Co ${ticker}`, finishedAt });

test('Recent keeps the newest run per ticker and counts the others', () => {
  const rows = [ // newest first, as mergeReportHistory returns them
    row('j5', '7203', '2026-10-05'), row('j4', '6758', '2026-10-04'),
    row('j3', '7203', '2026-10-03'), row('j2', ' 7203 ', '2026-10-02'), row('j1', '6758', '2026-10-01'),
  ];
  const groups = groupRecentByTicker(rows);
  assert.deepEqual(groups.map((g) => [g.item.jobId, g.runs]), [['j5', 3], ['j4', 2]]);
});

test('deleting the shown run surfaces the next-newest run of that ticker', () => {
  const rows = [row('j3', '7203', '3'), row('j2', '7203', '2'), row('j1', '7203', '1')];
  const after = rows.filter((r) => r.jobId !== 'j3');
  assert.deepEqual(groupRecentByTicker(after).map((g) => [g.item.jobId, g.runs]), [['j2', 2]]);
});

test('grouping caps at 12 companies, never merges ticker-less rows, skips rows without a jobId', () => {
  const many = Array.from({ length: 15 }, (_, i) => row(`j${i}`, String(1000 + i), String(100 - i)));
  assert.equal(groupRecentByTicker(many).length, 12);
  const odd = [row('a', '', '3'), row('b', '', '2'), { ticker: '7203' }, null];
  assert.deepEqual(groupRecentByTicker(odd).map((g) => [g.item.jobId, g.runs]), [['a', 1], ['b', 1]]);
  assert.deepEqual(groupRecentByTicker(undefined), []);
});

test('Recent renders grouped rows with the runs badge, slides only the name block, shows the warning reason', () => {
  assert.match(homeSource, /recentGroups\.map\(\(\{ item, runs \}, idx\)/);
  assert.doesNotMatch(homeSource, /recentRows\.slice\(0, 12\)/);
  assert.match(homeSource, /×\{runs\} runs/);
  assert.match(homeSource, /color: isHov \? "#f4f5f7"/);
  // The slide lives on the clickable name block (rr-recent-main), not the whole row.
  const rowStyle = homeSource.slice(homeSource.indexOf('className="rr-recent-row"'), homeSource.indexOf('onMouseEnter={() => setHoveredItem'));
  assert.doesNotMatch(rowStyle, /translateX/);
  const main = homeSource.slice(homeSource.indexOf('className="rr-recent-main"'), homeSource.indexOf('onFocus={(e) => { if (isViewable)'));
  assert.match(main, /translateX\(6px\)/);
  assert.match(homeSource, /prefers-reduced-motion: reduce\) \{ \.rr-recent-main/);
  // Reason as a visible second line, with the pill's title kept.
  assert.match(homeSource, /title=\{warningText\}[\s\S]{0,900}"Warning" : "HTML only"/);
  assert.match(homeSource, /textOverflow: "ellipsis",\s*whiteSpace: "nowrap",\s*\}\}\s*>\s*\{warningText\}/);
});

test('search: one placeholder line, "/" focuses it unless typing, key hint hidden on touch', () => {
  const bar = src('components/home/SearchBar.jsx');
  assert.match(bar, /"Search any company by name or ticker…"/);
  assert.doesNotMatch(bar, /"Search any company by (ticker|name)…"/);
  assert.match(bar, /e\.key !== "\/" \|\| e\.metaKey \|\| e\.ctrlKey \|\| e\.altKey/);
  assert.match(bar, /isTypingTarget\(e\.target\) \|\| isTypingTarget\(document\.activeElement\)/);
  assert.match(bar, /tag === "INPUT" \|\| tag === "TEXTAREA" \|\| tag === "SELECT"/);
  assert.match(bar, /isContentEditable/);
  assert.match(bar, /aria-keyshortcuts="\/"/);
  assert.match(bar, /!query && !isFocused && !isSubmitting && \(\s*<kbd/);
  assert.match(bar, /@media \(hover: none\) \{ \.search-bar__kbd \{ display: none/);
});

