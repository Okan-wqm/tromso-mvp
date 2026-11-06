// What the monitoring wall says aloud when a card gets worse (frontend/announce.ts): only a rise of the state, never a
// fall, a first load or a card that comes into view; a critical card in the assertive region, the others politely; at
// most one announcement per region in a window, the rest said as a count.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Limiter, pollNotice, rises, sentences } from './announce.js';

test('a rise is a card whose state got worse; better, the same, new and gone cards are not', () => {
  const before = new Map([['a', 'ok'], ['b', 'warning'], ['c', 'critical'], ['d', 'note'], ['gone', 'ok']]);
  const after = new Map([['a', 'critical'], ['b', 'ok'], ['c', 'critical'], ['d', 'blind'], ['new', 'critical']]);
  assert.deepEqual(rises(before, after), [{ key: 'a', from: 'ok', to: 'critical', stale: false },
                                         { key: 'd', from: 'note', to: 'blind', stale: true }]);
  assert.deepEqual(rises(new Map([['a', 'empty']]), new Map([['a', 'ok']])), []);       // fish stocked is not worse
  assert.deepEqual(rises(new Map([['a', 'ok']]), new Map([['a', 'weird']])), []);       // an unknown word says nothing
});

test('the sentences: the first rise in full, the rest as a count, critical apart', () => {
  const words = { critical: 'Critical', warning: 'Warning', blind: 'No recent data' };
  const found = sentences([{ key: 'a', from: 'ok', to: 'critical', stale: false },
                           { key: 'b', from: 'ok', to: 'warning', stale: false },
                           { key: 'c', from: 'ok', to: 'blind', stale: true }],
                          (key) => ({ a: 'T-01', b: 'T-02', c: 'T-03' })[key] ?? key, words,
                          '{unit}: {state}', '{count} more cards got worse');
  assert.deepEqual(found, { assertive: 'T-01: Critical', polite: 'T-02: Warning 1 more cards got worse' });
  assert.deepEqual(sentences([], () => '', words, '', ''), { assertive: '', polite: '' });
});

test('a limiter lets one announcement through per window and keeps the latest for after it', () => {
  const limiter = new Limiter(5000);
  assert.equal(limiter.take('one', 1000), 'one');
  assert.equal(limiter.take('two', 2000), null);
  assert.equal(limiter.take('three', 3000), null);
  assert.equal(limiter.pending(), 'three');
  assert.equal(limiter.take('', 6100), 'three');                   // the window passed: the held one goes out
  assert.equal(limiter.take('four', 7000), null);
  assert.equal(limiter.take('five', 11200), 'five');
});

test('a card that loses sight of its water is said: old, blind or with no limit, whatever its rank was (F-244)', () => {
  const before = new Map([['a', 'critical'], ['b', 'critical'], ['c', 'note'], ['d', 'critical:stale'],
                          ['e', 'unjudged'], ['f', 'blind']]);
  const after = new Map([['a', 'critical:stale'], ['b', 'blind'], ['c', 'unjudged'], ['d', 'critical:stale'],
                         ['e', 'ok'], ['f', 'critical:stale']]);
  assert.deepEqual(rises(before, after), [
    { key: 'a', from: 'critical', to: 'critical', stale: true },
    { key: 'b', from: 'critical', to: 'blind', stale: true },
    { key: 'c', from: 'note', to: 'unjudged', stale: false },
    { key: 'f', from: 'blind', to: 'critical', stale: true },
  ]);
});

test('an old critical card is said with its state and that its data is old, in the assertive region', () => {
  const words = { critical: 'Critical', blind: 'No recent data', unjudged: 'No limit' };
  const found = sentences([{ key: 'a', from: 'critical', to: 'critical', stale: true },
                           { key: 'b', from: 'ok', to: 'blind', stale: true }],
                          (key) => ({ a: 'T-01', b: 'T-02' })[key] ?? key, words, '{unit}: {state}', '{count} more',
                          'no recent data');
  assert.deepEqual(found, { assertive: 'T-01: Critical, no recent data', polite: 'T-02: No recent data' });
});

test('the grid says aloud when it can no longer be updated, when it is gone and when it is live again', () => {
  const texts = { stale: 'Not updated', gone: 'Signed out', live: 'Up to date again' };
  assert.equal(pollNotice('live', 'stale', texts), 'Not updated');
  assert.equal(pollNotice('stale', 'gone', texts), 'Signed out');
  assert.equal(pollNotice('stale', 'live', texts), 'Up to date again');
  assert.equal(pollNotice('live', 'live', texts), '');                  // nothing changed
  assert.equal(pollNotice(undefined, 'live', texts), '');               // the first load says nothing
});
