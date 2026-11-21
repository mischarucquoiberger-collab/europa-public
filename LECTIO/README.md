# LECTIO

LECTIO (codenamed **Europa**) turns a company ticker into a sourced research
report, with a Deep Research workspace for the heavy lifting.

## Stack

- React 18 + Vite 6, hash routing, Tailwind
- Deep Research workspace bundled under `public/xyz` and served UI-only in dev
- Node's built-in test runner for the shell, routing and report-flow suites

## Run

```bash
cd kabu
npm install
npm run dev        # http://localhost:3000
```

The UI expects the report backend on `/api` (same origin or a dev proxy).

## Checks

```bash
npm test           # 230 tests
npm run lint
npm run build
```

## Layout

```
kabu/src/pages       Home, Reports, GenerateReport, ReportViewer, DeepResearch
kabu/src/components  navigation, splash, planet mark, report UI
kabu/public/xyz      Deep Research workspace bundle
kabu/tests           node:test suites
```
