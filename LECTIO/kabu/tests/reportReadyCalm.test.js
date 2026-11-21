// Owner 11-22: the report-ready screen must appear calmly and at once — no light
// sweep across the preview card ("the white thing swinging"), no slide/scale of
// the card, no spring or pulse ring on the check, no staggered delays, nothing
// under prefers-reduced-motion, and no horizontal overflow from the entrance.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages/GenerateReport.jsx", import.meta.url), "utf8");
const between = (from, to) => {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a + 1);
  assert.ok(a >= 0 && b > a, `source anchors ${from} … ${to} must exist`);
  // Code only: comments may describe what was removed.
  return source.slice(a, b).replace(/\{?\/\*[\s\S]*?\*\/\}?/g, "");
};
const complete = between("COMPLETE STATE", "ERROR STATE");
const card = between("{/* ── Report preview card ──", "{/* Bottom actions */}");

test("ready state has no light sweep, spring, pulse ring or staggered delays", () => {
  assert.doesNotMatch(complete, /Light sweep|Pulse ring/);
  assert.doesNotMatch(complete, /"300%"|"-100%"/, "nothing may travel across the card");
  assert.doesNotMatch(complete, /type:\s*"spring"/);
  assert.doesNotMatch(complete, /delay\s*:/, "no element may wait before appearing");
  assert.doesNotMatch(complete, /\by:\s*-?\d{2,}/, "no slide of more than 6 px");
  assert.equal((complete.match(/\binitial=/g) || []).length, 1, "only the block itself has an entrance");
  assert.match(complete, /key="complete"\s+initial=\{readyEnter\}\s+animate=\{\{ opacity: 1 \}\}\s+transition=\{readyFade\}/);
});

test("preview card neither moves nor scales, on entrance or on hover", () => {
  assert.doesNotMatch(card, /motion\./);
  assert.doesNotMatch(card, /scale|translate|whileHover/);
  assert.match(card, /group-hover:opacity-100/, "the Open Full Screen hint still answers the pointer");
  assert.match(card, /style=\{\{ height: "clamp\(40vh, 60vh, 70vh\)"/, "card height is fixed before the iframe loads");
});

test("entrance is one short opacity fade, and none with reduced motion", () => {
  assert.match(source, /import \{[^}]*\buseReducedMotion\b[^}]*\} from "framer-motion"/);
  assert.match(source, /const reduceMotion = useReducedMotion\(\);/);
  assert.match(source, /const readyEnter = reduceMotion \? false : \{ opacity: 0 \};/);
  const fade = source.match(/const readyFade = \{ duration: ([\d.]+), ease: "easeOut" \};/);
  assert.ok(fade, "readyFade must be a plain duration + ease");
  assert.ok(Number(fade[1]) <= 0.25, "fade is at most 0.25 s");
});

test("nothing moves the ready block after it mounts", () => {
  // Leaving running/error is a quick fade (no shrink/blur that holds the ready state back).
  assert.doesNotMatch(source, /blur\(8px\)/);
  const exit = source.match(/const stateExit = \{ opacity: 0, transition: \{ duration: reduceMotion \? 0 : ([\d.]+) \} \};/);
  assert.ok(exit, "stateExit must be an opacity-only fade");
  // The sidebar auto-collapse finishes within that fade, so the centred block never slides sideways.
  const side = source.match(/duration: reduceMotion \? 0 : isComplete \? ([\d.]+) : 0\.3, ease/);
  assert.ok(side, "sidebar collapse on completion is short, and instant with reduced motion");
  assert.ok(Number(side[1]) <= Number(exit[1]));
  // The top progress bar snaps on completion instead of sliding during the entrance.
  assert.match(source, /transition=\{\{ duration: reduceMotion \|\| isComplete \? 0 : 0\.6, ease: "easeOut" \}\}/);
});
