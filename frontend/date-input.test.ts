// The shared date box (frontend/date-input.ts, on core.widgets.DayInput and MomentInput): what a person types is put the
// European way, dd.mm.yyyy and HH:MM, the way the server reads it (owner rule); what is not a date is left as typed, for the
// server to refuse.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { tidy } from './date-input.js';

test('a day is put as dd.mm.yyyy', () => {
  for (const [typed, put] of [['6.11.2026', '06.11.2026'], ['06.11.2026', '06.11.2026'], ['6/11/2026', '06.11.2026'],
    ['6-11-2026', '06.11.2026'], ['06112026', '06.11.2026'], [' 6.11.26 ', '06.11.2026'], ['2026-11-06', '06.11.2026']]) {
    assert.equal(tidy(typed, false), put, typed);
  }
});

test('a moment is put as dd.mm.yyyy HH:MM on the 24-hour clock', () => {
  for (const [typed, put] of [['6.11.2026 9:19', '06.11.2026 09:19'], ['06.11.2026 09.19', '06.11.2026 09:19'],
    ['6.11.2026 0919', '06.11.2026 09:19'], ['2026-11-06T09:19', '06.11.2026 09:19'], ['6.11.2026', '06.11.2026']]) {
    assert.equal(tidy(typed, true), put, typed);
  }
});

test('what is not a day stays as typed, and an empty box stays empty', () => {
  for (const typed of ['', '31.02.2026', '6.13.2026', 'tomorrow', '6.11.2026 25:00', '6.11.2026 9:19']) {
    assert.equal(tidy(typed, false), typed.trim(), typed);
  }
  assert.equal(tidy('6.11.2026 24:10', true), '6.11.2026 24:10');
});
