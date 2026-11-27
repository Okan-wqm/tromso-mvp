// The chart's frame on a phone (frontend/chartframe.ts): the water's mark in the middle of the frame, never a scroll
// before the picture's start or past its end. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { centred } from './chartframe.js';

test('the mark stands in the middle of the frame', () => {
  assert.equal(centred(300, 800, 400), 250);
  assert.equal(centred(300, 544, 272), 122);
});

test('never before the start nor past the end', () => {
  assert.equal(centred(300, 544, 40), 0);              // a mark near the left edge: no scroll
  assert.equal(centred(300, 544, 540), 244);           // near the right edge: the end of the picture, no further
  assert.equal(centred(600, 544, 300), 0);             // a frame as wide as the picture: nothing to scroll
});
