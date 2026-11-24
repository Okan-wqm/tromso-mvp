// The npm licence gate (scripts/licence-gate.mjs) and the islands' icon set (scripts/icons.mjs): the product passes both,
// and the gate refuses a licence that is not on its list. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const GATE = resolve('scripts/licence-gate.mjs');

test('every installed npm package has an allowed or reviewed licence', () => {
  const run = spawnSync(process.execPath, [GATE], { encoding: 'utf8' });
  assert.equal(run.status, 0, `${run.stdout}${run.stderr}`);
});

test('the gate refuses AGPL, a non-commercial or a missing licence, and reads OR and AND', async () => {
  const { allowed, gate } = await import(`file://${GATE.replaceAll('\\', '/')}`) as {
    allowed: (expression: string) => boolean;
    gate: (root: string) => { problems: string[] };
  };
  assert.equal(allowed('MIT'), true);
  assert.equal(allowed('(MIT OR GPL-3.0)'), true);
  assert.equal(allowed('MIT AND CC-BY-NC-4.0'), false);
  for (const bad of ['AGPL-3.0', 'SSPL-1.0', 'BUSL-1.1', 'CC-BY-NC-4.0', '']) assert.equal(allowed(bad || '-'), false, bad);
  const tree = resolve('.build', 'licence-gate');
  rmSync(tree, { recursive: true, force: true });
  const lock = { packages: { '': {}, 'node_modules/good': {}, 'node_modules/bad': {}, 'node_modules/none': {}, 'node_modules/axe-core': {} } };
  mkdirSync(tree, { recursive: true });
  writeFileSync(join(tree, 'package-lock.json'), JSON.stringify(lock));
  const manifests: Record<string, object> = {
    good: { license: 'MIT' }, bad: { license: 'AGPL-3.0-only' }, none: {}, 'axe-core': { license: 'GPL-2.0' },
  };
  for (const [name, manifest] of Object.entries(manifests)) {
    mkdirSync(join(tree, 'node_modules', name), { recursive: true });
    writeFileSync(join(tree, 'node_modules', name, 'package.json'), JSON.stringify(manifest));
  }
  try {
    assert.deepEqual(gate(tree).problems, ['bad: AGPL-3.0-only', 'none: no licence', 'axe-core: GPL-2.0 (reviewed as MPL-2.0)']);
  } finally {
    rmSync(tree, { recursive: true, force: true });
  }
});

test('the islands\' icon set is what templates/icons builds', () => {
  const run = spawnSync(process.execPath, ['scripts/icons.mjs', '--check'], { encoding: 'utf8' });
  assert.equal(run.status, 0, `${run.stdout}${run.stderr}`);
});
