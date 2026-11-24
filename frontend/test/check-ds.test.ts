// The design-system gate (scripts/check-ds.mjs, docs/design/system/README.md "The gate"): the product passes it, and every
// kind of one-off style it is there to stop is planted in a throwaway tree (under .build/, never committed) and caught.
// Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const TREE = resolve('.build', 'ds-gate');

type Tree = { css?: Record<string, string>; templates?: Record<string, string>; islands?: Record<string, string>; ratchet?: object };

function gate(tree: Tree): { status: number | null; out: string } {
  rmSync(TREE, { recursive: true, force: true });
  mkdirSync(join(TREE, 'static', 'css'), { recursive: true });
  mkdirSync(join(TREE, 'templates'), { recursive: true });
  mkdirSync(join(TREE, 'docs', 'design', 'system'), { recursive: true });
  const css = { 'ds.css': '.ui-btn { font-size: var(--fs-body); border-radius: var(--radius-control); }\n', ...tree.css };
  for (const [name, text] of Object.entries(css)) writeFileSync(join(TREE, 'static', 'css', name), text);
  for (const [name, text] of Object.entries(tree.templates ?? {})) writeFileSync(join(TREE, 'templates', name), text);
  mkdirSync(join(TREE, 'frontend', 'islands', 'ui'), { recursive: true });
  for (const [name, text] of Object.entries(tree.islands ?? {})) writeFileSync(join(TREE, 'frontend', 'islands', name), text);
  if (tree.ratchet) writeFileSync(join(TREE, 'docs', 'design', 'system', 'ds-ratchet.json'), JSON.stringify(tree.ratchet));
  const run = spawnSync(process.execPath, ['scripts/check-ds.mjs', '--root', TREE], { encoding: 'utf8' });
  return { status: run.status, out: `${run.stdout}${run.stderr}` };
}

/** A template's head: one `<link>` per sheet name, as the product's templates write them. */
const page = (sheets: string[]): string => sheets.map((name) => `<link rel="stylesheet" href="{% asset 'css/${name}.css' %}">`).join('\n');

const CLEAN = '.a { font-size: var(--fs-small); border-radius: var(--radius-chip); color: var(--text-1); }\n';
const RATCHET = { css: { 'a.css': { fontSizes: 0, radii: 0 } }, legacy: {}, twArbitrarySizes: 0 };
/** A clean tree with one island source, frontend/islands/ui/X.tsx (or the name given). */
const island = (code: string, name = 'ui/X.tsx'): Tree => ({ css: { 'a.css': CLEAN }, islands: { [name]: code }, ratchet: RATCHET });

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
      ['a page that loads the pattern sheet after the sheets that refine it',
        { css: { 'a.css': CLEAN }, templates: { 'p.html': page(['fonts', 'tokens', 'base', 'app', 'components', 'ds', 'tw']) }, ratchet: RATCHET }, 'p.html: app.css comes before ds.css'],
      ['a page that loads the pattern sheet before base.css',
        { css: { 'a.css': CLEAN }, templates: { 'p.html': page(['fonts', 'tokens', 'ds', 'base', 'components']) }, ratchet: RATCHET }, 'p.html: base.css comes after ds.css'],
      ['a page that loads base.css and no pattern sheet',
        { css: { 'a.css': CLEAN }, templates: { 'p.html': page(['fonts', 'tokens', 'base', 'components']) }, ratchet: RATCHET }, 'p.html: loads base.css but not ds.css'],
      ['an island that writes a style attribute', island('export const X = () => <p style={{ color: "var(--ok)" }}>x</p>;'), 'ui/X.tsx:1 writes a style attribute'],
      ['an island that sets element.style', island('export function x(e: HTMLElement) { e.style.width = "3px"; }'), 'ui/X.tsx:1 writes a style attribute'],
      ['an island that writes a markup string', island('export const X = () => <p dangerouslySetInnerHTML={{ __html: "<b>" }} />;'), 'ui/X.tsx:1 writes a markup string'],
      ['an island that writes a colour', island('const ink = "#1d1f20";'), 'ui/X.tsx:1 writes a colour'],
      ['an island that uses an old class name', island('export const X = () => <a className="button">Go</a>;'), 'ui/X.tsx:1 uses the old class name "button"'],
      ['an island with an arbitrary Tailwind size', island('export const X = () => <p className="tw:text-[13px]">x</p>;'), 'arbitrary Tailwind size tw:text-[13px]'],
    ];
    for (const [name, tree, message] of faults) {
      await t.test(name, () => {
        const run = gate(tree);
        assert.equal(run.status, 1, `${name} passed the gate:\n${run.out}`);
        assert.ok(run.out.includes(message), `${name}: expected "${message}" in\n${run.out}`);
      });
    }
    await t.test('the order of the product: fonts, tokens, base, ui, ds, app, components, the page sheets, tw; a page that only adds a sheet, and a comment that names one, pass', () => {
      const run = gate({ css: { 'a.css': CLEAN }, ratchet: RATCHET, templates: {
        'base.html': `${page(['fonts', 'tokens', 'base', 'ui', 'ds', 'app', 'components'])}{% block page_styles %}{% endblock %}${page(['tw'])}{# css/app.css would come first #}`,
        'report.html': page(['fonts', 'tokens', 'base', 'ds', 'app', 'components']),
        'hr.html': `{% block extra_head %}${page(['hr'])}{% endblock %}` } });
      assert.equal(run.status, 0, run.out);
    });
    await t.test('a clean island passes: classes only, and a comment may name what is forbidden', () => {
      const run = gate(island('// never style={{}} here\nexport const Ok = () => <button className="ui-btn" data-variant="primary">Go</button>;\n'));
      assert.equal(run.status, 0, run.out);
    });
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
