import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Owner 2026-10-13: "everywhere take off this modern format" (the wide, tracked
// Michroma capitals on page titles, heroes, steps and labels) and "take off these
// thing" (the "● TOKYO 10:21 JST · OPEN" status line on every page header). The
// pages are back in their own plain type; only the Deep Research opening keeps
// Michroma for its DEEP RESEARCH lockup.
const srcDir = fileURLToPath(new URL("../src/", import.meta.url));
const read = (p) => readFileSync(path.join(srcDir, p), "utf8");

function sourceFiles(dir = srcDir) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.(jsx?|css)$/.test(name) ? [full] : [];
  });
}
const rel = (full) => path.relative(srcDir, full).split(path.sep).join("/");

test("no status line anywhere: the component and its Tokyo clock are gone, nothing imports them", () => {
  assert.equal(existsSync(path.join(srcDir, "components/StatusLine.jsx")), false);
  assert.equal(existsSync(path.join(srcDir, "components/StatusLine.css")), false);
  assert.equal(existsSync(path.join(srcDir, "lib/tokyoSession.js")), false);
  for (const file of sourceFiles()) {
    assert.doesNotMatch(readFileSync(file, "utf8"), /StatusLine|tokyoSession|useTokyoSession|sl--dark/, rel(file));
  }
});

test("Michroma is left only in the Deep Research opening (and its one font face)", () => {
  const allowed = new Set(["index.css", "pages/DrSplash.jsx", "pages/DrSplash.css", "lib/drSplashLusion.js"]);
  const users = sourceFiles().map(rel).filter((f) => /Michroma/.test(read(f)));
  assert.deepEqual(users.filter((f) => !allowed.has(f)), []);
  assert.match(read("index.css"), /@font-face \{\s*font-family: "Michroma";/);
});

test("titles and labels that wore the wide capitals are in plain type again", () => {
  const runs = read("pages/Home.jsx").match(/className="rr-recent-runs"[\s\S]*?style=\{\{([\s\S]*?)\}\}/);
  assert.ok(runs);
  assert.doesNotMatch(runs[1], /fontFamily|letterSpacing|textTransform/);
  const kbd = read("components/home/SearchBar.jsx").match(/className="search-bar__kbd"[\s\S]*?style=\{\{([\s\S]*?)\}\}/);
  assert.ok(kbd);
  assert.doesNotMatch(kbd[1], /fontFamily/);
});

