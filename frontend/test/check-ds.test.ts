// The design-system gate (scripts/check-ds.mjs, docs/design/system/README.md "The gate"): the product passes it, and every
// kind of one-off style it is there to stop is planted in a throwaway tree (under .build/, never committed) and caught.
// Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const TREE = resolve('.build', 'ds-gate');

type Tree = { css?: Record<string, string>; templates?: Record<string, string>; ratchet?: object };

function gate(tree: Tree): { status: number | null; out: string } {
  rmSync(TREE, { recursive: true, force: true });
  mkdirSync(join(TREE, 'static', 'css'), { recursive: true });
  mkdirSync(join(TREE, 'templates'), { recursive: true });
  mkdirSync(join(TREE, 'docs', 'design', 'system'), { recursive: true });
  const css = { 'ds.css': '.ui-btn { font-size: var(--fs-body); border-radius: var(--radius-control); }\n', ...tree.css };
  for (const [name, text] of Object.entries(css)) writeFileSync(join(TREE, 'static', 'css', name), text);
  for (const [name, text] of Object.entries(tree.templates ?? {})) writeFileSync(join(TREE, 'templates', name), text);
  if (tree.ratchet) writeFileSync(join(TREE, 'docs', 'design', 'system', 'ds-ratchet.json'), JSON.stringify(tree.ratchet));
  const run = spawnSync(process.execPath, ['scripts/check-ds.mjs', '--root', TREE], { encoding: 'utf8' });
  return { status: run.status, out: `${run.stdout}${run.stderr}` };
}

const CLEAN = '.a { font-size: var(--fs-small); border-radius: var(--radius-chip); color: var(--text-1); }\n';
const RATCHET = { css: { 'a.css': { fontSizes: 0, radii: 0 } }, legacy: {}, twArbitrarySizes: 0 };

test('the product passes the design-system gate', () => {
  const run = spawnSync(process.execPath, ['scripts/check-ds.mjs'], { encoding: 'utf8' });
  assert.equal(run.status, 0, `${run.stdout}${run.stderr}`);
});

test('a clean tree passes, and a planted fault of each kind fails it', async (t) => {
  try {
    await t.test('clean', () => {
      const run = gate({ css: { 'a.css': CLEAN }, templates: { 'p.html': '<a class="ui-btn" data-variant="primary">Go</a>' }, ratchet: RATCHET });
      assert.equal(run.status, 0, run.out);
    });
    const faults: [string, Tree, string][] = [
      ['a hex colour', { css: { 'a.css': `${CLEAN}.b { color: #ff0000; }\n` }, ratchet: RATCHET }, 'a colour outside tokens.css: a.css:2'],
      ['an rgb() colour', { css: { 'a.css': `${CLEAN}.b { box-shadow: 0 0 2px rgba(0, 0, 0, .3); }\n` }, ratchet: RATCHET }, 'a colour outside tokens.css'],
      ['a named colour', { css: { 'a.css': `${CLEAN}.b { background: white; }\n` }, ratchet: RATCHET }, 'a colour outside tokens.css'],
      ['a raw font size', { css: { 'a.css': `${CLEAN}.b { font-size: 14px; }\n` }, ratchet: RATCHET }, 'up: a.css raw font sizes: 1, the ratchet allows 0'],
      ['a raw font size in rem', { css: { 'a.css': `${CLEAN}.b { font-size: .875rem; }\n` }, ratchet: RATCHET }, 'up: a.css raw font sizes'],
      ['a raw radius', { css: { 'a.css': `${CLEAN}.b { border-top-left-radius: 7px; }\n` }, ratchet: RATCHET }, 'up: a.css raw radii: 1'],
      ['a raw size in the component layer', { css: { 'a.css': CLEAN, 'ds.css': '.ui-chip { font-size: 13px; }\n' }, ratchet: RATCHET }, 'ds.css reads only tokens: ds.css:1'],
      ['a new sheet with a raw size', { css: { 'a.css': CLEAN, 'new.css': '.c { font-size: 11px; }\n' }, ratchet: RATCHET }, 'up: new.css raw font sizes: 1, the ratchet allows 0'],
      ['an old class name', { css: { 'a.css': CLEAN }, templates: { 'p.html': '<a class="button button-ghost" href="/">Go</a>' }, ratchet: RATCHET }, 'up: templates: class "button": 1'],
      ['an old class name in a condition', { css: { 'a.css': CLEAN }, templates: { 'p.html': '<p class="x{% if a %} badge{% endif %}">y</p>' }, ratchet: RATCHET }, 'up: templates: class "badge": 1'],
      ['an old table class', { css: { 'a.css': CLEAN }, templates: { 'p.html': '<div class="table-wrap"><table class="data-table"></table></div>' }, ratchet: RATCHET }, 'up: templates: class "data-table": 1'],
      ['an arbitrary Tailwind size', { css: { 'a.css': CLEAN }, templates: { 'p.html': '<p class="tw:text-[13px]">x</p>' }, ratchet: RATCHET }, 'up: templates: arbitrary Tailwind sizes: 1'],
      ['a count that went down with the ratchet left high',
        { css: { 'a.css': CLEAN }, ratchet: { ...RATCHET, css: { 'a.css': { fontSizes: 2, radii: 0 } } } }, 'down, lower the ratchet'],
    ];
    for (const [name, tree, message] of faults) {
      await t.test(name, () => {
        const run = gate(tree);
        assert.equal(run.status, 1, `${name} passed the gate:\n${run.out}`);
        assert.ok(run.out.includes(message), `${name}: expected "${message}" in\n${run.out}`);
      });
    }
    await t.test('a raw size the ratchet still allows passes', () => {
      const run = gate({ css: { 'a.css': `${CLEAN}.b { font-size: 14px; }\n` }, ratchet: { ...RATCHET, css: { 'a.css': { fontSizes: 1, radii: 0 } } } });
      assert.equal(run.status, 0, run.out);
    });
    await t.test('a class that only starts with an old name is not one (card-head, tabular, badge-note)', () => {
      const run = gate({ css: { 'a.css': CLEAN }, templates: { 'p.html': '<a class="buttons ui-btn tabular card-head badge-note">Go</a>' }, ratchet: RATCHET });
      assert.equal(run.status, 0, run.out);
    });
  } finally {
    rmSync(TREE, { recursive: true, force: true });
  }
});
