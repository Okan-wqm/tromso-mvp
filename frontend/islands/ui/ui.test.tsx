// The islands' component library, rendered to markup (react-dom/server, no browser): each component draws the design
// system's classes and states, names what it must name, and writes no style attribute and no markup string. The browser
// test (frontend/test/islands.browser.test.ts) holds the look, the focus, the CSP and axe. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { renderToStaticMarkup } from 'react-dom/server';

import {
  Button, ChartFrame, CheckboxGroup, Chip, EmptyState, ErrorState, Icon, IconButton, LinkButton, LinkTabs, LoadingState,
  Notice, Plate, SelectField, ServerForm, Table, Tabs, TextField, Tile, Tiles,
} from './index.js';
import { ICONS } from './icon-shapes.js';

const html = (node: Parameters<typeof renderToStaticMarkup>[0]): string => renderToStaticMarkup(node);

test('a button is the design system\'s ui-btn in every variant, and busy keeps its label', () => {
  assert.match(html(<Button>Print</Button>), /^<button[^>]*class="ui-btn"[^>]*>Print<\/button>$/);
  assert.doesNotMatch(html(<Button>Print</Button>), /data-variant/);          // secondary is the default, no attribute
  for (const variant of ['primary', 'ghost', 'danger', 'danger-text', 'link'] as const) {
    assert.match(html(<Button variant={variant}>Go</Button>), new RegExp(`data-variant="${variant}"`));
  }
  const busy = html(<Button variant="primary" icon="plus" busy>Save</Button>);
  assert.match(busy, /aria-disabled="true"/);
  assert.match(busy, /data-pending="true"/);
  assert.match(busy, /class="ui-spinner"/);
  assert.doesNotMatch(busy, /<svg/);                                            // the ring stands in for the icon
  assert.match(busy, />Save</);
  assert.match(html(<Button isDisabled>Start</Button>), / disabled=""/);
  assert.match(html(<Button size="coarse">Record meal</Button>), /data-size="coarse"/);
});

test('an icon button is named by its label; a link button is a link', () => {
  assert.match(html(<IconButton icon="trash" label="Delete Bergen Hatchery" tone="danger" />),
    /class="icon-button icon-button-danger"[^>]*aria-label="Delete Bergen Hatchery"|aria-label="Delete Bergen Hatchery"[^>]*class="icon-button icon-button-danger"/);
  assert.match(html(<LinkButton href="/sites/new/" variant="primary" icon="plus">Add site</LinkButton>),
    /^<a class="ui-btn" data-variant="primary" href="\/sites\/new\/">/);
});

test('an icon is drawn from the templates\' icon set, decorative, as elements', () => {
  const svg = html(<Icon name="octagon" />);
  assert.match(svg, /^<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7\.86 2h8/);
  const files = readdirSync(resolve('templates/icons')).filter((name) => name.endsWith('.svg')).map((name) => name.slice(0, -4));
  assert.deepEqual(Object.keys(ICONS).sort(), files.sort());
});

test('a chip carries its glyph and its word for every status', () => {
  assert.match(html(<Chip kind="critical">Critical</Chip>), /data-status="critical"><svg[^>]*>.*<\/svg><span>Critical<\/span>/);
  assert.match(html(<Chip kind="stale">No recent data</Chip>), /data-state="stale"/);
  assert.match(html(<Chip kind="nodata">Not measured</Chip>), /data-state="nodata"><span>Not measured/);
  for (const kind of ['ok', 'warning', 'critical', 'hold', 'stale'] as const) {
    assert.match(html(<Chip kind={kind}>x</Chip>), /<svg/, kind);
  }
});

test('a plate has its head, its safety line and its span; a tile its status edge in words', () => {
  const plate = html(<Plate title="Open alarms" meta="13:42" link={{ href: '/alarms/', label: 'Alarms' }} span={4} safety="Nothing is sent yet.">x</Plate>);
  assert.match(plate, /^<section class="ui-plate" data-span="4">/);
  assert.match(plate, /<h2>Open alarms<\/h2>/);
  assert.match(plate, /<a class="ui-plate-link" href="\/alarms\/">Alarms <span aria-hidden="true">→<\/span><\/a>/);
  assert.match(plate, /class="ui-notice" data-tone="warning"/);
  const tile = html(<Tiles><Tile label="Open alarms" figure="3" status="critical" statusLabel="Critical" href="/alarms/" /></Tiles>);
  assert.match(tile, /<a class="ui-tile" href="\/alarms\/" data-status="critical">/);
  assert.match(tile, /<span class="sr-only">Critical: <\/span>Open alarms/);
});

test('a table is a named, scrolling region with its figures right, its row status and its sticky actions', () => {
  const rows = [{ code: 'SI-02', name: 'Silo 2', kg: '251.8' }, { code: 'FS-01', name: 'Feed store 1', kg: '63,089.3' }];
  const table = html(<Table label="Storage" rows={rows} rowKey={(row) => row.code}
    columns={[{ key: 'name', label: 'Location', rowHeader: true }, { key: 'kg', label: 'On hand (kg)', numeric: true }]}
    rowStatus={(row) => (row.code === 'SI-02' ? 'warning' : undefined)} actions={() => <IconButton icon="pencil" label="Edit" />}
    actionsLabel="Actions" />);
  assert.match(table, /^<div class="ui-table-wrap" tabindex="0" role="region" aria-label="Storage"><table class="ui-table">/);
  assert.match(table, /<th scope="col" class="num">On hand \(kg\)<\/th>/);
  assert.match(table, /<tr data-status="warning"><th scope="row">Silo 2<\/th><td class="num">251\.8<\/td><td class="ui-actions">/);
  assert.match(table, /<th scope="col" class="ui-actions"><span class="sr-only">Actions<\/span><\/th>/);
});

test('tabs are React Aria\'s, drawn as ui-tabs; link tabs mark the current view', () => {
  const tabs = html(<Tabs label="Leave" items={[{ id: 'a', label: 'Pending', count: '2', content: 'x' }, { id: 'b', label: 'All', content: 'y' }]} />);
  assert.match(tabs, /role="tablist"[^>]*class="ui-tabs"|class="ui-tabs"[^>]*role="tablist"/);
  assert.match(tabs, /aria-selected="true"[^>]*>Pending<span class="ui-count">2<\/span>|>Pending<span class="ui-count">2<\/span>/);
  assert.match(html(<LinkTabs label="Views" tabs={[{ href: '?s=open', label: 'Open', current: true }]} />), /aria-current="page"/);
});

test('a field with the server\'s errors is invalid, says them in words and is described by them', () => {
  const field = html(<TextField name="org" label="Organisation number" help="Nine digits." errors={['Enter nine digits.']} />);
  assert.match(field, /^<div class="field has-error">/);
  assert.match(field, /aria-invalid="true"/);
  const id = /<input id="([^"]+)"/.exec(field)?.[1] ?? '';
  assert.match(field, new RegExp(`aria-describedby="${id}-help ${id}-errors"`));
  assert.match(field, /<ul class="errorlist" id="[^"]+-errors"><li class="ui-field-error"><svg[^>]*>.*<\/svg>Enter nine digits\.<\/li><\/ul>/);
  assert.doesNotMatch(html(<TextField name="n" label="Name" />), /aria-invalid|has-error/);
  assert.match(html(<TextField name="c" label="Capacity" unit="kg" numeric />), /<span class="ui-unit"><input[^>]*inputMode="decimal"[^>]*><span class="ui-unit-label">kg<\/span>/);
  assert.match(html(<SelectField name="s" label="Site" options={[{ value: '1', label: 'Bergen' }]} />), /<select[^>]*><option value="1">Bergen<\/option><\/select>/);
  assert.match(html(<CheckboxGroup name="x" label="Supplies" options={[{ value: 'f', label: 'Feed' }]} />), /^<fieldset class="field field-set"><legend>Supplies<\/legend>/);
  const form = html(<ServerForm action="/save/" csrfToken="t0k" formErrors={['Two people changed it.']} actions={<Button type="submit">Save</Button>}>x</ServerForm>);
  assert.match(form, /<input type="hidden" name="csrfmiddlewaretoken" value="t0k"\/>/);
  assert.match(form, /role="alert"/);
});

test('the states say in words what is missing, loading or wrong', () => {
  assert.match(html(<EmptyState title="No alarm recipients yet">Nobody is notified.</EmptyState>), /class="ui-empty"><p class="ui-empty-title">No alarm recipients yet/);
  const loading = html(<LoadingState label="Loading the cards…" lines={2} />);
  assert.match(loading, /role="status"/);
  assert.match(loading, /Loading the cards…/);
  assert.equal((loading.match(/ui-skeleton/g) ?? []).length, 2);
  assert.match(html(<ErrorState title="Cannot be read" retryLabel="Try again" onRetry={() => undefined} />), /role="alert".*Try again/);
  assert.match(html(<Notice tone="ok" onClose={() => undefined} closeLabel="Close">Saved</Notice>), /aria-label="Close"/);
  const chart = html(<ChartFrame title="Oxygen" now="6.50 mg/L" nowStatus="warning" label="Oxygen, 24 h" keys={[{ label: 'Sensor', series: 1 }]}>x</ChartFrame>);
  assert.match(chart, /<span class="ui-chart-now" data-status="warning">6\.50 mg\/L<\/span>/);
  assert.match(chart, /role="img" aria-label="Oxygen, 24 h"/);
});

test('no component writes a style attribute or a markup string (the islands\' own rule, scripts/check-ds.mjs)', () => {
  const folder = resolve('frontend/islands/ui');
  for (const name of readdirSync(folder).filter((file) => file.endsWith('.tsx') && !file.endsWith('.test.tsx'))) {
    const source = readFileSync(join(folder, name), 'utf8');
    assert.doesNotMatch(source, /\bstyle=\{|dangerouslySetInnerHTML|innerHTML/, name);
  }
});
