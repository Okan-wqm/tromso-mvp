// The browser tests' skip rule (frontend/test/browsers.ts, F-127): without Chrome or Edge they are skipped and say why;
// under CI=1 they are never skipped, so a CI without a browser fails instead of passing quietly. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { skipWithout } from './browsers.js';

test('a browser test is skipped only where there is no browser and this is not CI', () => {
  assert.equal(skipWithout(['C:/chrome.exe'], {}), false);
  assert.equal(skipWithout([], {}), 'no Chrome or Edge on this machine');
  assert.equal(skipWithout([], { CI: '1' }), false);                    // CI: run, and fail for want of a browser
  assert.equal(skipWithout([], { CI: '0' }), 'no Chrome or Edge on this machine');
});

test('CI=true (as GitHub Actions sets it) is CI too: a missing browser fails there, never skips', () => {
  assert.equal(skipWithout([], { CI: 'true' }), false);
  for (const value of ['', 'false', 'TRUE', 'yes']) {
    assert.equal(skipWithout([], { CI: value }), 'no Chrome or Edge on this machine', `CI=${value}`);
  }
});
