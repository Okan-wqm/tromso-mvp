// A field note's place (frontend/field-note.ts placeNote): under its control, above it when there is no room below,
// never past the window's sides. The showing and hiding are held in a browser (frontend/test/calculator.pages.ts). Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { NOTE_DELAY_MS, placeNote } from './field-note.js';

const control = { left: 100, top: 200, right: 300, bottom: 234 };

test('a note stands under its control, at its left edge', () => {
  assert.deepEqual(placeNote(control, 320, 90, 1440, 900), { left: 100, top: 240, above: false });
});

test('a note with no room below stands above its control', () => {
  assert.deepEqual(placeNote({ ...control, top: 780, bottom: 814 }, 320, 90, 1440, 900), { left: 100, top: 684, above: true });
});

test('a note never leaves the window at the sides, and stays below when it fits nowhere else', () => {
  assert.equal(placeNote({ ...control, left: 300 }, 360, 120, 390, 844).left, 22);         // 390 - 8 - 360
  assert.equal(placeNote({ ...control, left: -40 }, 200, 40, 390, 844).left, 8);
  assert.equal(placeNote({ ...control, top: 20, bottom: 54 }, 320, 900, 1440, 900).above, false);
});

test('the mouse rests a second before a note shows', () => {
  assert.equal(NOTE_DELAY_MS, 1000);
});
