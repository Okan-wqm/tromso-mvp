// The tokens' stylesheets are built from one source, docs/design/system/tokens.json (scripts/tokens.mjs): the design
// system's tokens.css and the served static/css/tokens.css must be what it builds now. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('tokens.css is what tokens.json builds now', () => {
  const run = spawnSync(process.execPath, ['scripts/tokens.mjs', '--check'], { encoding: 'utf8' });
  assert.equal(run.status, 0, `${run.stderr}${run.stdout}`);
});
