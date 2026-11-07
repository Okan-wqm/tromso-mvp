// The shared date box (frontend/date-input.ts, on core.widgets.DayInput and MomentInput): a date in the European shape,
// dd.mm.yyyy and HH:MM, is put with its leading zeros, the way the server reads it (owner rule); ISO is put so too. Any other
// shape (a slash, a dash, a two-digit year, digits run together) is never reinterpreted: it stays as typed, for the server
// to refuse with the shape it wants, so 11/06/2026 can never silently become 11 June or 6 November. A moment needs its time.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { tidy } from './date-input.js';

test('a day in the European shape or ISO is put as dd.mm.yyyy', () => {
  for (const [typed, put] of [['6.11.2026', '06.11.2026'], ['06.11.2026', '06.11.2026'], [' 6.1.2026 ', '06.01.2026'],
    ['2026-11-06', '06.11.2026']]) {
    assert.equal(tidy(typed, false), put, typed);
  }
});

test('a moment is put as dd.mm.yyyy HH:MM on the 24-hour clock', () => {
  for (const [typed, put] of [['6.11.2026 9:19', '06.11.2026 09:19'], ['06.11.2026 09:19', '06.11.2026 09:19'],
    ['2026-11-06T09:19', '06.11.2026 09:19'], ['2026-11-06 09:19', '06.11.2026 09:19']]) {
    assert.equal(tidy(typed, true), put, typed);
  }
});

test('another shape, a two-digit year, an impossible day or a moment without its time stays as typed', () => {
  for (const typed of ['', '11/06/2026', '6/11/2026', '6-11-2026', '06112026', '6.11.26', '1.2.85', '31.02.2026',
    '6.13.2026', 'tomorrow', '6.11.2026 9:19']) {
    assert.equal(tidy(typed, false), typed.trim(), typed);
  }
  for (const typed of ['6.11.2026', '6.11.2026 24:10', '6.11.2026 0919', '06.11.2026 09.19', '11/06/2026 09:19']) {
    assert.equal(tidy(typed, true), typed, typed);
  }
});
