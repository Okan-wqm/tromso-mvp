// The status strip's announcer (frontend/strip.ts): only a rise is said. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { rose } from './strip.js';

test('a rise is said, a fall, the same and the first answer are not', () => {
  assert.equal(rose('', 'warning'), true);
  assert.equal(rose('', 'critical'), true);
  assert.equal(rose('warning', 'critical'), true);
  assert.equal(rose('critical', 'warning'), false);
  assert.equal(rose('warning', ''), false);
  assert.equal(rose('critical', 'critical'), false);
  assert.equal(rose(null, 'critical'), false);           // the first answer after the page was drawn
  assert.equal(rose('', null), false);                    // the item is gone (the person may no longer see alarms)
});
