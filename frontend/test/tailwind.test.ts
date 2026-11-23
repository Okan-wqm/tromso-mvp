// static/css/tw.css is committed: it must be what frontend/tailwind.css and the templates' tw: classes build now with the
// pinned CLI (scripts/tailwind.mjs --check, also run by CI before the build writes it again). Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('static/css/tw.css is what the Tailwind source and the templates build now', () => {
  const run = spawnSync(process.execPath, ['scripts/tailwind.mjs', '--check'], { encoding: 'utf8' });
  assert.equal(run.status, 0, `${run.stderr}${run.stdout}`);
});
