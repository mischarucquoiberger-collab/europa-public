// Mobile gate (2026-09-02): phones get a desktop-required screen in place of
// every dense surface; Home, Query and the sign-in/invitation screens stay reachable.
// Pure-rule tests import the real module; wiring/design contracts are pinned
// against the source so a refactor cannot silently drop them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React from "react";
import { transformSync } from "esbuild";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "src", p), "utf8");

// useIsPhone.js imports react (hooks) — slice the pure rule out and import it
// as a data-URL module, the same idiom queryHandoff.test.js uses.
const hookSrc = src("lib/useIsPhone.js");
const pureStart = hookSrc.indexOf("export const PHONE_MAX_SHORT_SIDE");
const pureEnd = hookSrc.indexOf("function computeIsPhone");
assert.ok(pureStart > 0 && pureEnd > pureStart, "pure block present in useIsPhone.js");
const { isPhoneSize, PHONE_MAX_SHORT_SIDE } = await import(
  "data:text/javascript;base64," + Buffer.from(hookSrc.slice(pureStart, pureEnd)).toString("base64")
);

test("phone rule: narrow viewports are phones regardless of pointer", () => {
  assert.equal(PHONE_MAX_SHORT_SIDE, 640);
  assert.equal(isPhoneSize(390, 844, true), true);   // portrait phone
  assert.equal(isPhoneSize(430, 932, true), true);   // large phone
  assert.equal(isPhoneSize(500, 844, false), true);  // narrow desktop window at phone width
});

test("phone rule: a SHORT viewport is a phone only when it is also not wide AND touch-driven", () => {
  assert.equal(isPhoneSize(844, 390, true), true);    // landscape phone (coarse pointer)
  assert.equal(isPhoneSize(932, 430, true), true);    // large phone landscape
  // review-caught regression: short DESKTOP viewports must NOT be gated
  assert.equal(isPhoneSize(1366, 620, false), false); // 1366×768 laptop minus browser chrome
  assert.equal(isPhoneSize(1440, 500, false), false); // half-height window / docked DevTools
  assert.equal(isPhoneSize(844, 390, false), false);  // short but mouse-driven → desktop
  assert.equal(isPhoneSize(1366, 620, true), false);  // wide touch laptop/tablet → not a phone
});

test("phone rule: tablets and laptops pass, bogus reads fail OPEN", () => {
  assert.equal(isPhoneSize(768, 1024, true), false);  // iPad portrait
  assert.equal(isPhoneSize(1024, 768, true), false);  // iPad landscape
  assert.equal(isPhoneSize(1280, 800, false), false); // small laptop
  assert.equal(isPhoneSize(1440, 900, false), false);
  assert.equal(isPhoneSize(0, 0, true), false);       // detached / thumbnailer → desktop
  assert.equal(isPhoneSize(0, 844, true), false);
  assert.equal(isPhoneSize(undefined, undefined), false);
});

test("hook reads the coarse-pointer media query and fails open", () => {
  const hook = src("lib/useIsPhone.js");
  assert.match(hook, /matchMedia\("\(pointer: coarse\)"\)/);
  assert.match(hook, /isPhoneSize\(window\.innerWidth \|\| 0, window\.innerHeight \|\| 0,\s*primaryPointerIsCoarse\(\)\)/);
});

// Layout's phone allow-list, read from the source the gate actually uses.
function mobileAllowedPaths() {
  const m = src("Layout.jsx").match(/const MOBILE_ALLOWED_PATHS = new Set\(\[([\s\S]*?)\]\)/);
  assert.ok(m, "MOBILE_ALLOWED_PATHS declared");
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
}

test("Layout: exact mobile allow-list (Home, Deep Research, root) and the gate replaces children", () => {
  const layout = src("Layout.jsx");
  const allowed = mobileAllowedPaths().sort();
  assert.deepEqual(allowed, ["/", "/Home", "/DeepResearch"].sort());
  assert.match(layout, /const mobileGated = isPhone && !isMobileAllowed\(path\)/);
  // the gate renders INSTEAD of the page (no heavy effects fire on a phone)
  assert.match(layout, /\{mobileGated \? <MobileGate pageName=\{currentPageName\} \/> : children\}/);
  assert.match(layout, /export default function Layout\(\{ children, currentPageName \}\)/);
});

// The allow-list check itself, sliced from Layout.jsx (pure JS, no JSX) and run.
async function layoutAllowRule() {
  const layout = src("Layout.jsx");
  const start = layout.indexOf("const MOBILE_ALLOWED_PATHS");
  const end = layout.indexOf("\n", layout.indexOf("const isMobileAllowed"));
  assert.ok(start >= 0 && end > start, "allow-list block present in Layout.jsx");
  const code = layout.slice(start, end) + "\nexport { isMobileAllowed };";
  return (await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"))).isMobileAllowed;
}

test("Layout: the phone allow-list matches paths case-insensitively, like the router (#/home, #/deepresearch)", async () => {
  const isMobileAllowed = await layoutAllowRule();
  for (const allowed of mobileAllowedPaths()) {
    assert.equal(isMobileAllowed(allowed), true, allowed);
    assert.equal(isMobileAllowed(allowed.toLowerCase()), true, allowed.toLowerCase());
    assert.equal(isMobileAllowed(allowed.toUpperCase()), true, allowed.toUpperCase());
  }
  for (const typed of ["/home", "/HOME", "/deepresearch", "/DEEPRESEARCH"]) {
    assert.equal(isMobileAllowed(typed), true, typed);
  }
  // Dense surfaces stay gated whatever the case.
  for (const gated of ["/Reports", "/reports", "/GenerateReport", "/Viewer", "/viewer", "/Homepage"]) {
    assert.equal(isMobileAllowed(gated), false, gated);
  }
});

test("App passes the page key through Layout and gives every route the loading fallback", () => {
  const app = src("App.jsx");
  const start = app.indexOf("const LayoutWrapper =");
  const end = app.indexOf("function AppRoutes", start);
  assert.ok(start >= 0 && end > start, "the route wrapper is present");
  const { code } = transformSync(app.slice(start, end), { loader: "jsx", jsxFactory: "React.createElement" });
  const Layout = () => null;
  const RouteBoundary = () => null;
  const RouteLoading = () => null;
  const LayoutWrapper = new Function("React", "Layout", "RouteBoundary", "Suspense", "RouteLoading",
    `${code}\nreturn LayoutWrapper;`)(React, Layout, RouteBoundary, React.Suspense, RouteLoading);
  const children = React.createElement("main", null, "Selected page");
  for (const currentPageName of ["Home", "Reports", "GenerateReport", "Viewer", "DeepResearch"]) {
    const element = LayoutWrapper({ currentPageName, children });
    assert.equal(element.type, Layout);
    assert.equal(element.props.currentPageName, currentPageName);
    const boundary = element.props.children;
    assert.equal(boundary.type, RouteBoundary);
    assert.equal(boundary.key, currentPageName);
    const suspense = boundary.props.children;
    assert.equal(suspense.type, React.Suspense);
    assert.equal(suspense.props.children, children);
    assert.equal(suspense.props.fallback.type, RouteLoading);
  }
});

test("MobileGate: restrained design contract — no decorative animation, copy handoff, both mobile surfaces linked", () => {
  const gate = src("components/MobileGate.jsx");
  assert.doesNotMatch(gate, /mg-ring|mg-aurora|mg-blob|mgPulse|mgDrift/, "no radar/aurora decoration");
  assert.match(gate, /Copy link for desktop/);
  assert.match(gate, /Link copied/);
  assert.match(gate, /navigator\.clipboard/);
  assert.match(gate, /execCommand\("copy"\)/, "legacy clipboard fallback present");
  assert.match(gate, /to="\/DeepResearch"/);
  assert.match(gate, /to="\/Home"/);
  assert.match(gate, /prefers-reduced-motion: reduce/);
  // short-landscape branch exists so both CTAs fit in ~390 px without scrolling
  assert.match(gate, /@media \(max-height: 470px\)/);
  // the visitor's deep link code is surfaced read-only, never navigated on
  assert.match(gate, /params\.get\("code"\)/);
  assert.doesNotMatch(gate, /navigate\(|location\.assign|location\.replace/);
});

test("MobileGate labels every gated page key registered in pages.config", () => {
  const cfg = src("pages.config.js");
  const keys = [...cfg.matchAll(/^\s*"([A-Za-z][A-Za-z0-9-]*)":\s*[A-Za-z][A-Za-z0-9]*,?/gm)].map((x) => x[1]);
  assert.deepEqual(keys, ["Home", "Reports", "GenerateReport", "Viewer", "DeepResearch"], "the registered pages");
  const gate = src("components/MobileGate.jsx");
  const labelled = [...gate.matchAll(/^\s*([A-Za-z]+): "[^"]+",?$/gm)].map((x) => x[1]);
  // Pages on the phone allow-list are never gated, so they need no label.
  const exempt = new Set(mobileAllowedPaths().map((p) => p.slice(1)));
  for (const k of keys) {
    if (exempt.has(k)) continue;
    assert.ok(labelled.includes(k), `PAGE_LABELS is missing a label for gated page "${k}"`);
  }
});

// ── 2026-10-12: a full-page capture reports a 1×1 viewport for a moment; the
// gate replaced (unmounted) the open company page, which then lost its header
// and refetched every pane. Degenerate sizes are not phones, and entering the
// gate waits for the phone size to hold.
const { createPhoneGate, PHONE_GATE_SETTLE_MS, PHONE_MIN_REAL_SIDE } = await import(
  "data:text/javascript;base64," + Buffer.from(hookSrc.slice(pureStart, pureEnd)).toString("base64")
);

test("phone rule: a degenerate 1×1 / sub-200 px read is not a phone", () => {
  assert.equal(PHONE_MIN_REAL_SIDE, 200);
  assert.equal(isPhoneSize(1, 1, false), false);
  assert.equal(isPhoneSize(1, 1, true), false);
  assert.equal(isPhoneSize(150, 900, true), false);
  assert.equal(isPhoneSize(320, 568, true), true);   // the smallest real phone still gates
});

function fakeTimers() {
  const pending = new Map(); let next = 1;
  return {
    setTimer: (fn, ms) => { const id = next++; pending.set(id, { fn, ms }); return id; },
    clearTimer: (id) => { pending.delete(id); },
    flush() { for (const [id, t] of [...pending]) { pending.delete(id); t.fn(); } },
    get size() { return pending.size; },
  };
}

test("phone gate: a transient phone-sized read never unmounts the page", () => {
  const timers = fakeTimers(); const writes = []; let size = [1440, 1000];
  const gate = createPhoneGate({ compute: () => isPhoneSize(size[0], size[1], false), set: (v) => writes.push(v), ...timers });
  size = [500, 1000]; gate.update();          // a window dragged narrow for a moment
  assert.deepEqual(writes, []);                 // nothing yet: the size must hold
  size = [1440, 1000]; gate.update();         // back before the settle time
  assert.deepEqual(writes, [false]);            // stays desktop; the pending flip is cancelled
  assert.equal(timers.size, 0);
  timers.flush();
  assert.deepEqual(writes, [false]);
});

test("phone gate: a phone size that holds gates after the settle time; desktop returns at once", () => {
  const timers = fakeTimers(); const writes = []; let size = [390, 844];
  const gate = createPhoneGate({ compute: () => isPhoneSize(size[0], size[1], true), set: (v) => writes.push(v), ...timers });
  gate.update();
  assert.equal(PHONE_GATE_SETTLE_MS, 400);
  timers.flush();
  assert.deepEqual(writes, [true]);
  size = [1440, 1000]; gate.update();
  assert.deepEqual(writes, [true, false]);
  gate.dispose();
});
