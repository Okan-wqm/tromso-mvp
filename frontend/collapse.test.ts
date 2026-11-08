// A folded part of the rail (Setup, frontend/collapse.ts): it stays as the person left it on the next page, folded the
// first time; the page it holds always opens it, whatever was saved.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { opened } from './collapse.js';

test('folded until the person opens it, then as they left it', () => {
  assert.equal(opened(null, false), false);
  assert.equal(opened('open', false), true);
  assert.equal(opened('closed', false), false);
});

test('open on a page it holds, whatever was saved', () => {
  for (const saved of [null, 'open', 'closed']) assert.equal(opened(saved, true), true, String(saved));
});

test('a value it never wrote counts as nothing saved', () => {
  assert.equal(opened('yes', false), false);
});
