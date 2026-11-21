import test from 'node:test';
import assert from 'node:assert/strict';
import { safeAppNavigation } from '../src/lib/safeUrl.js';

const origin = 'https://indago.test';
for (const path of ['/\\outside.test', '//outside.test', '/%5coutside.test', '/%2foutside.test',
  '/%255coutside.test', '/%252foutside.test', '/\noutside.test', '/%0doutside.test',
  'javascript:alert(1)', 'https://outside.test', '/broken%escape', null, {}]) {
  test(`untrusted navigation rejects ${JSON.stringify(path)}`, () => {
    assert.equal(safeAppNavigation(path, origin), null);
  });
}

for (const path of ['/', '/Reports', '/CompanyProfile?code=7203&tab=financials',
  '/Query?prompt=%5Cexample', '/DeepResearch?c=conv_test&r=res_test', '/Reports#sources']) {
  test(`same-app navigation preserves ${path}`, () => {
    assert.equal(safeAppNavigation(path, origin), path);
    assert.equal(new URL(safeAppNavigation(path, origin), origin).origin, origin);
  });
}

test('legacy bearer query is not forwarded to app navigation', () => {
  assert.equal(safeAppNavigation('/Reports?t=private&code=7203', origin), '/Reports?code=7203');
});
