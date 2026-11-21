import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Source pins over the ReportViewer binding guard (audit P-10). Moved here from
// the retired calculator pins when the Calc and AI tabs were removed.
const source = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/pages/ReportViewer.jsx"),
  "utf8",
);

test("P-10: mismatch keeps tools unbound but honors the URL display title", () => {
  assert.match(source, /\? \(search\.get\("title"\) \|\| "Report"\)/);
  // The security binding stays: jobId and notesKey are nulled on mismatch.
  assert.match(source, /const jobId = bindingMismatch \? null/);
  assert.match(source, /const notesKey = !bindingMismatch && fileName/);
  assert.equal(
    source.includes("A shared link opens notes only for the account that generated the report."),
    true,
  );
});

test("the panel has only Sources and Notes; retired tabs open Sources", () => {
  assert.doesNotMatch(source, /id: "ai"|id: "calc"|setActiveTab\("ai"\)|setActiveTab\("calc"\)/);
  assert.match(source, /const initTab = requestedTab \? \(requestedTab === "notes" \? "notes" : "sources"\) : null;/);
});
