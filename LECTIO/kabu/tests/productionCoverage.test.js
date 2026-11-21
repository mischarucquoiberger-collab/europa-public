import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import ts from 'typescript';
import { ESLint } from 'eslint';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

test('all production JavaScript is included in typecheck and ESLint', async () => {
  const source = join(root, 'src');
  const files = readdirSync(source, { recursive: true })
    .filter((name) => /\.(?:jsx?|mjs|cjs)$/.test(name))
    .map((name) => join(source, name));
  assert.ok(files.length > 30, 'production source inventory must be present');
  const config = ts.readConfigFile(join(root, 'jsconfig.json'), ts.sys.readFile);
  assert.equal(config.error, undefined);
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root);
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.options.checkJs, true);
  assert.equal(parsed.options.noEmit, true);
  const included = new Set(parsed.fileNames.map((name) => resolve(name)));
  const lint = new ESLint({ cwd: root });
  for (const path of files) {
    assert.ok(included.has(resolve(path)), `typecheck excludes ${path}`);
    const rules = (await lint.calculateConfigForFile(path))?.rules;
    assert.equal(rules?.['no-undef']?.[0], 2, `lint excludes ${path}`);
    assert.equal(rules?.['react-hooks/rules-of-hooks']?.[0], 2, `hook checks exclude ${path}`);
  }
});

