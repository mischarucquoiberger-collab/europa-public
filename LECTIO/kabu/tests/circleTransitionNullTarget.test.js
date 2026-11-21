// CLICKQA 2026-10-06: navigateWithReveal(promise) without animation must not
// navigate when the promise settles to no target. SearchBar's launchReport
// resolves null after a failed /start (it shows its own error); navigate(null)
// pushed a duplicate history entry for the current page with its query
// dropped, so Back needed two presses.
// Behavioural: bundles the real component with esbuild and stub modules.
import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const entry = path.join(here, '..', 'src', 'components', 'CircleTransition.jsx');

const STUBS = {
  react: `export const createContext = (v) => ({ v });
    export const useContext = (c) => c.v;
    export const useState = (v) => [v, () => {}];
    export const useRef = (v) => ({ current: v });
    export const useCallback = (f) => f;
    export const useEffect = () => {};`,
  'react/jsx-runtime': `export const jsx = (type, props) => { if (props && 'value' in props) globalThis.__ctxValue = props.value; return null; };
    export const jsxs = jsx; export const Fragment = 'F';`,
  'react-router-dom': `export const useNavigate = () => (to) => globalThis.__navigations.push(to);`,
  gsap: `export const gsap = {};`,
  '@/components/FlowFieldBackground': `export default function F() { return null; }`,
};

async function loadProvider() {
  const out = await build({
    entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'neutral',
    jsx: 'automatic', logLevel: 'silent',
    plugins: [{
      name: 'stubs',
      setup(b) {
        b.onResolve({ filter: /^(react|react\/jsx-runtime|react-router-dom|gsap|@\/components\/FlowFieldBackground)$/ },
          (a) => ({ path: a.path, namespace: 'stub' }));
        b.onLoad({ filter: /.*/, namespace: 'stub' }, (a) => ({ contents: STUBS[a.path], loader: 'js' }));
      },
    }],
  });
  const code = out.outputFiles[0].text;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}

async function api() {
  globalThis.__navigations = [];
  globalThis.__ctxValue = undefined;
  const mod = await loadProvider();
  mod.CircleTransitionProvider({ children: null });
  assert.ok(globalThis.__ctxValue?.navigateWithReveal, 'provider exposes navigateWithReveal');
  return globalThis.__ctxValue.navigateWithReveal;
}

const settle = () => new Promise((r) => setTimeout(r, 0));

test('a promise that resolves to no target does not navigate (no junk history entry)', async () => {
  const go = await api();
  go(Promise.resolve(null));
  go(Promise.resolve(''));
  go(Promise.reject(new Error('start failed')));
  await settle();
  assert.deepEqual(globalThis.__navigations, []);
});

test('a string or a promise of a target still navigates', async () => {
  const go = await api();
  go('/Query');
  go(Promise.resolve('/GenerateReport?jobId=abc'));
  await settle();
  assert.deepEqual(globalThis.__navigations, ['/Query', '/GenerateReport?jobId=abc']);
});
