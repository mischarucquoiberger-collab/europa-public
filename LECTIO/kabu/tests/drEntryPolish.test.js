// The Deep Research entry: no white flash before the black opening screen, the
// loader shows the header's Indago lettering, and the memory tab never sits on
// top of the opening screen.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('the loader draws the wordmark and has a dark tone', () => {
  const loader = read('src/components/IndagoLoader.jsx');
  assert.match(loader, /import \{ letteringWord \} from "\.\/indagoLettering\.js";/);
  assert.match(loader, /\.ndg-loader\.is-dark \.ndg-loader-word\{color:#f4f4f5;\}/);
  assert.doesNotMatch(loader, /INDAGO<span/);
  assert.match(loader, /tone === "dark" \? " is-dark" : ""/);
  // The bar is the navy accent on light pages; the dark tone uses the light ink (navy would vanish there).
  assert.match(loader, /background:#0e1420;border-radius:2px;/);
  assert.match(loader, /\.ndg-loader\.is-dark \.ndg-loader-bar\{background:#f4f4f5;\}/);
});

test('a report shows the loader until its frame has loaded (no blank pane)', () => {
  const viewer = read('src/pages/ReportViewer.jsx');
  assert.match(viewer, /const \[frameLoaded, setFrameLoaded\] = useState\(false\);/);
  assert.match(viewer, /useEffect\(\(\) => \{ setFrameLoaded\(false\); \}, \[viewUrl\]\);/);
  // The viewer is a light reading desk: its loaders paint the desk canvas, never navy.
  assert.match(viewer, /\{!frameLoaded && \(\s*<div className="absolute inset-0 z-\[1\] flex items-center justify-center bg-\[#eceef2\]" aria-busy="true">\s*<IndagoLoader label="Opening report…" \/>/);
  assert.match(viewer, /!reportReady \? \(\s*<div className="h-full flex items-center justify-center bg-\[#eceef2\]" aria-busy="true">\s*<IndagoLoader label="Opening report…" \/>/);
});

test('closing the menu by clicking outside returns focus to the toggle', () => {
  const nav = read('src/components/UnderlayNav.jsx');
  assert.match(nav, /const overlayClick = \(\) => \{\s*if \(!isOpen\) return;\s*toggle\(\);[\s\S]*?toggleBtn\.focus\(\{ preventScroll: true \}\);\s*\};/);
});
