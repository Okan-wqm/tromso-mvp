// The islands' component library, rendered to markup (react-dom/server, no browser): each component draws the design
// system's classes and states, names what it must name, and writes no style attribute and no markup string. The browser
// test (frontend/test/islands.browser.test.ts) holds the look, the focus, the CSP and axe. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { renderToStaticMarkup } from 'react-dom/server';

import {
  Acknowledge, AuditItem, Button, ChartFrame, Checkbox, FileField, LinkList, PermissionMatrix, RadioGroup, RemoveBox, RowGrid, CheckboxGroup, Chip, EmptyState, ErrorState, Icon, IconButton, LinkButton, LinkTabs, List, ListItem, LoadingState,
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
  assert.match(html(<IconButton icon="trash" label="Delete Test Site North" tone="danger" />),
    /class="icon-button icon-button-danger"[^>]*aria-label="Delete Test Site North"|aria-label="Delete Test Site North"[^>]*class="icon-button icon-button-danger"/);
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
  assert.match(tile, /<span class="sr-only">Critical: <\/span><span class="ui-tile-label-text" title="Open alarms">Open alarms<\/span>/);
});

test('a tile label sits in its own slot and keeps its whole text as its title, so a clamped label is never lost', () => {
  const label = 'QoS 0 messages dropped on a full queue of the ingest';
  const tile = html(<Tile label={label} figure="0" />);
  assert.match(tile, new RegExp(`<span class="ui-tile-label"><span class="ui-tile-label-text" title="${label}">${label}</span></span>`));
  assert.match(tile, /<span class="ui-tile-figure" data-figure="" title="0">0<\/span>/);
});

test('a table is a named, scrolling region with its figures right, its row status and its sticky actions', () => {
  const rows = [{ code: 'SI-02', name: 'Silo 2', kg: '251.8' }, { code: 'FS-01', name: 'Feed store 1', kg: '63,089.3' }];
  const table = html(<Table label="Storage" rows={rows} rowKey={(row) => row.code}
    columns={[{ key: 'name', label: 'Location', rowHeader: true }, { key: 'kg', label: 'On hand (kg)', numeric: true }]}
    rowStatus={(row) => (row.code === 'SI-02' ? 'warning' : undefined)} actions={() => <IconButton icon="pencil" label="Edit" />}
    actionsLabel="Actions" />);
  assert.match(table, /^<div class="ui-table-wrap" tabindex="0" role="region" aria-label="Storage"><table class="ui-table">/);
  assert.match(table, /<th scope="col" class="num">On hand \(kg\)<\/th>/);
  assert.match(table, /<tr data-status="warning"><th scope="row"><span class="ui-row-status"><svg[^>]*>.*?<\/svg><\/span>Silo 2<\/th><td class="num">251\.8<\/td><td class="ui-actions">/);
  assert.match(table, /<th scope="col" class="ui-actions"><span class="sr-only">Actions<\/span><\/th>/);
  // a row's status is a glyph and a word in its first cell too, never the edge colour alone (WCAG 1.4.1)
  const marked = html(<Table label="Storage" rows={rows} rowKey={(row) => row.code} columns={[{ key: 'name', label: 'Location', rowHeader: true }]}
    rowStatus={(row) => (row.code === 'SI-02' ? 'warning' : undefined)} statusLabels={{ critical: 'Critical', warning: 'Warning' }} />);
  assert.match(marked, /<tr data-status="warning"><th scope="row"><span class="ui-row-status"><svg[^>]*>.*?<\/svg><span class="sr-only">Warning: <\/span><\/span>Silo 2<\/th>/);
  assert.match(marked, /<tr><th scope="row">Feed store 1<\/th>/);
});

test('tabs are React Aria\'s, drawn as ui-tabs; link tabs mark the current view', () => {
  const tabs = html(<Tabs label="Leave" items={[{ id: 'a', label: 'Pending', count: '2', content: 'x' }, { id: 'b', label: 'All', content: 'y' }]} />);
  assert.match(tabs, /role="tablist"[^>]*class="ui-tabs"|class="ui-tabs"[^>]*role="tablist"/);
  // the selected tab is the first, and only it (review M7: an either-or pattern let the selection go unchecked)
  const selected = [...tabs.matchAll(/<div[^>]*role="tab"[^>]*>/g)].map(([tag]) => /aria-selected="true"/.test(tag));
  assert.deepEqual(selected, [true, false]);
  assert.match(tabs, />Pending<span class="ui-count">2<\/span>/);
  assert.match(html(<LinkTabs label="Views" tabs={[{ href: '?s=open', label: 'Open', current: true }]} />), /aria-current="page"/);
});

test('kept mounted, every panel is in the page and an unselected one is inert (hidden by ds.css)', () => {
  const items = [{ id: 'a', label: 'General', content: <input name="title" /> }, { id: 'b', label: 'Where', content: <input name="site" /> }];
  const kept = html(<Tabs label="Task" items={items} keepMounted />);
  assert.match(kept, /name="title"/);
  assert.match(kept, /name="site"/);
  assert.match(kept, /class="ui-tab-panel"[^>]*inert=""[^>]*data-inert="true"|data-inert="true"[^>]*inert=""/);
  assert.equal((kept.match(/data-inert="true"/g) ?? []).length, 1);
  assert.doesNotMatch(html(<Tabs label="Task" items={items} />), /name="site"/);
  const css = readFileSync(resolve('static/css/ds.css'), 'utf8');
  assert.match(css, /\.ui-tab-panel\[data-inert\] \{ display: none; \}/);
});

test('a layout puts the panels where the page wants them: a form round some, others after it, each still a tab', () => {
  const items = [{ id: 'a', label: 'General', content: <input name="title" /> }, { id: 'b', label: 'Contacts', content: <input name="contacts-0-name" /> }];
  const laid = html(<Tabs label="Site" items={items} keepMounted layout={(panel) => <><form id="record">{panel('a')}</form><form id="rows">{panel('b')}</form></>} />);
  // what the page draws (React Aria builds its collection from a <template> copy, which is never in the document)
  const drawn = laid.slice(laid.indexOf('</template>'));
  assert.match(drawn, /<form id="record"><div[^>]*role="tabpanel"[^>]*><input name="title"\/><\/div><\/form><form id="rows"><div class="ui-tab-panel"[^>]*inert=""[^>]*><input name="contacts-0-name"\/>/);
  assert.equal(html(<Tabs label="Site" items={items} layout={(panel) => panel('missing')} />).includes('role="tabpanel"'), false);
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
  assert.match(html(<SelectField name="s" label="Site" options={[{ value: '1', label: 'Test Site North' }]} />), /<select[^>]*><option value="1">Test Site North<\/option><\/select>/);
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
  const described = html(<ChartFrame title="Oxygen" label="Oxygen, 24 h" values={[['Latest', '6.50 mg/L at 13:42']]}>x</ChartFrame>);
  const id = /aria-describedby="([^"]+)"/.exec(described)?.[1] ?? '';
  assert.match(described, new RegExp(`<dl class="sr-only" id="${id}"><div><dt>Latest<\\/dt><dd>6\\.50 mg\\/L at 13:42<\\/dd><\\/div><\\/dl>`));
});

test('no component writes a style attribute or a markup string (the islands\' own rule, scripts/check-ds.mjs)', () => {
  const folder = resolve('frontend/islands/ui');
  for (const name of readdirSync(folder).filter((file) => file.endsWith('.tsx') && !file.endsWith('.test.tsx'))) {
    const source = readFileSync(join(folder, name), 'utf8');
    assert.doesNotMatch(source, /\bstyle=\{|dangerouslySetInnerHTML|innerHTML/, name);
  }
});

test('a list is the design system\'s ui-list: its rows with their sub-line, meta, chip and status edge', () => {
  const list = html(<List label="Upcoming reports"><ListItem main="Sea lice" sub="10.11.2026 · Overdue" meta="13:40" status="critical" chip={<Chip kind="critical">Overdue</Chip>} /></List>);
  assert.match(list, /^<ul class="ui-list" role="list" aria-label="Upcoming reports"><li class="ui-list-item" data-status="critical">/);
  assert.match(list, /<span class="ui-list-main"><span>Sea lice<\/span><span class="ui-cell-sub">10\.11\.2026 · Overdue<\/span><\/span>/);
  assert.match(list, /<span class="ui-list-meta">13:40<\/span><span class="ui-chip" data-status="critical">/);
  assert.match(html(<List ordered><ListItem main="x" /></List>), /^<ol class="ui-list" role="list"><li class="ui-list-item"><span class="ui-list-main"><span>x<\/span><\/span><\/li><\/ol>$/);
  const entry = html(<AuditItem action="Changed" record="Task · Pond" who="by admin" status="critical" critical={<Chip kind="critical">Critical</Chip>} />);
  assert.match(entry, /^<li class="ui-list-item ui-audit-item" data-status="critical"><span class="ui-audit-head"><strong class="ui-audit-action">Changed<\/strong><span class="ui-chip"/);
  assert.match(entry, /<span class="ui-audit-record">Task · Pond<\/span><span class="ui-audit-who">by admin<\/span>/);
  assert.doesNotMatch(list + entry, /style=/);
});


test('the form parts draw the old page\'s markup, post the old names, and take every word from props', () => {
  const box = html(<Checkbox name="active" label="Active" mark="optional" defaultChecked />);
  assert.match(box, /<label class="check"><input type="checkbox"[^>]*name="active"/);
  assert.match(box, / checked=""/);
  assert.match(box, / value="on"/);
  assert.match(box, /<span class="ui-field-mark">optional<\/span>/);
  const radios = html(<RadioGroup name="placement" label="Placement" options={[{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]} defaultValue="b" />);
  assert.match(radios, /<legend>Placement<\/legend>/);
  assert.match(radios, /name="placement"(?: checked="")? value="b"(?: checked="")?/);
  assert.equal((radios.match(/checked=""/g) ?? []).length, 1);
  const file = html(<FileField name="file" label="PDF" current={{ name: 'x.pdf', href: '/f/', intro: 'Currently:', clearName: 'file-clear', clearLabel: 'Remove the file' }} />);
  assert.match(file, /<p class="file-current">Currently: <a href="\/f\/"[^>]*>x\.pdf<\/a><\/p>/);
  assert.match(file, /name="file-clear"/);
  assert.match(file, /type="file"[^>]*name="file"/);
  const ack = html(<Acknowledge name="ack" title="Before handling" label="Go on" value="f00d">Warned.</Acknowledge>);
  assert.match(ack, /class="ui-notice ui-ack" data-tone="critical"/);
  assert.match(ack, /type="checkbox"[^>]*name="ack"[^>]*value="f00d"/);
  const matrix = html(<PermissionMatrix name="permissions" label="Rights" areaLabel="Area" columns={['Read', 'Create']}
    sections={[{ label: 'Facility', areas: [{ label: 'Sites', notes: ['Note'], cells: [{ action: 'Read', said: 'Sites: Read', value: '1', checked: true, id: 'p-1' }, null] }] }]} />);
  assert.match(matrix, /<table class="matrix">/);
  assert.match(matrix, /name="permissions"[^>]*value="1"/);
  assert.match(matrix, /id="p-1"[^>]*checked=""|checked=""[^>]*id="p-1"/);
  assert.match(matrix, /<span class="sr-only">Sites: Read<\/span>/);
  assert.match(matrix, /class="matrix-note"/);
  const links = html(<LinkList name="systems" label="Systems" columns={['Role']} primary primaryLabel="Primary" primaryWords="%(record)s is the primary one"
    rows={[{ pk: '7', label: 'RAS-1', checked: true, primary: true }]} />);
  assert.match(links, /name="systems"(?: checked="")? value="7"/);
  assert.match(links, /name="systems-primary"(?: checked="")? value="7"/);
  assert.equal((links.match(/checked=""/g) ?? []).length, 2);
  assert.match(links, /RAS-1 is the primary one/);
  const rows = html(<RowGrid prefix="c" management={[{ name: 'c-TOTAL_FORMS', value: '9' }, { name: 'c-INITIAL_FORMS', value: '1' }]}
    rows={[{ head: null, hidden: [{ name: 'c-0-id', value: '4' }], errors: ['Test row error.'], cells: [<input key="n" name="c-0-name" />,
      <RemoveBox key="d" name="c-0-DELETE" label="Remove" />] }]}
    newRow={(index) => ({ head: null, hidden: [], errors: [], cells: [<input key="n" name={`c-${index}-name`} />] })} columns={['Name']}
    legend="Contact" addLabel="Add contact" removeLabel="Remove" emptyText="None" errors={[]} />);
  assert.match(rows, /name="c-TOTAL_FORMS" value="1"/);           // the count is what is drawn, not what was given
  assert.match(rows, /name="c-INITIAL_FORMS" value="1"/);
  assert.ok(rows.includes('<th scope="col">Name</th><th scope="col"><span class="sr-only">Remove</span></th>'), 'the Remove column, named');
  assert.match(rows, /name="c-0-id" value="4"/);
  assert.ok(rows.includes('Test row error.'));
  assert.match(rows, /<label class="icon-button icon-button-danger ui-row-remove" title="Remove"><input type="checkbox" class="sr-only" name="c-0-DELETE"/);
  assert.doesNotMatch(box + radios + file + ack + matrix + links + rows, /style=/);
});

test('a server form is busy while it posts: its submit is switched off and says so, and ready again from history', () => {
  const form = html(<ServerForm action="/x/" csrfToken="t" label="Save" actions={<Button type="submit" variant="primary">Save</Button>} noValidate>x</ServerForm>);
  assert.match(form, /<form[^>]*noValidate=""/i);
  assert.doesNotMatch(form, /aria-busy/);                           // ready until it posts (the browser test presses it)
});

test('a list page: one GET form for the search and the filters, the table with its row actions, the pager; empty, its words', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const page = html(<ListPage {...LIST_PROPS} />);
  const forms = [...page.matchAll(/<form [^>]*>/g)].map((match) => match[0]);
  assert.equal(forms.filter((form) => /method="get"/.test(form)).length, 1, 'the search and the filters are one GET form');
  assert.match(page, /<input type="hidden" name="tab" value="pending"\/>/);
  assert.match(page, /<div class="ui-search"><svg[^]*?<\/svg><label class="sr-only" for="([^"]+)">Search employees<\/label><input id="\1" type="search" placeholder="Search by name or number" name="q" value="Alfa"\/><\/div>/);
  assert.match(page, /<optgroup label="Production departments"><option value="p:1">Hatchery A<\/option><\/optgroup>/);
  assert.match(page, /<option value="current" selected="">Working here<\/option>/);
  assert.match(page, /<a class="ui-tab" href="\?tab=pending" aria-current="page">Pending<span class="ui-count">2<\/span><\/a>/);
  assert.match(page, /<a class="ui-btn" data-variant="primary" href="\/hr\/team\/new\/">/);
  assert.doesNotMatch(page, /data-modal/, 'a list link opens the record\'s page, never the classic dialog');
  assert.match(page, /<span class="ui-cell-strong"><a href="\/hr\/team\/1\/">Ann Alfa<\/a><\/span><span class="ui-cell-sub">E-1<\/span>/);
  assert.match(page, /<tr data-status="warning">/);
  assert.match(page, /<td class="num"><span>0\.5<\/span><\/td>/);
  assert.match(page, /<form action="\/hr\/leave\/1\/cancel\/" method="post"><input type="hidden" name="csrfmiddlewaretoken" value="test-token"\/><input type="hidden" name="next" value="\/hr\/leave\/"\/><button type="submit" class="icon-button icon-button-danger" aria-label="Cancel the request"/);
  assert.match(page, /<a class="icon-button" href="\/hr\/team\/1\/view\/" aria-label="Show Ann Alfa"/);
  assert.match(page, /<nav class="pager list-pager" aria-label="Pages"><span>51–100 of 120<\/span>/);
  assert.match(page, /href="\?q=Alfa&amp;page=3"/);
  assert.match(page, /role="status"[^>]*>.*Two people have no department\./);
  assert.doesNotMatch(page, /style=/);
  const empty = html(<ListPage {...LIST_PROPS} table={{ ...LIST_PROPS.table, rows: [] }} />);
  assert.match(empty, /<div class="ui-empty"><p class="ui-empty-title">No employees match “Zed”<\/p><p class="ui-empty-text">Try another search\. <a href="\/hr\/team\/">Show all employees<\/a><\/p><\/div>/);
  assert.doesNotMatch(empty, /ui-table|list-pager|Showing 2 of 3/, 'no table, pager or line over an empty list');
});

test('a gauge: the bar as long as the share (full from 100), the share in words beside it, the bar hidden, no style', async () => {
  const { Gauge } = await import('./index.js');
  const gauge = html(<Gauge value={12.5} text="12 % of capacity" />);
  assert.match(gauge, /^<span class="ui-gauge"><svg class="ui-gauge-track" viewBox="0 0 100 1" preserveAspectRatio="none" aria-hidden="true" focusable="false"><rect class="ui-gauge-fill" width="12\.5" height="1"><\/rect><\/svg><span class="ui-gauge-text">12 % of capacity<\/span><\/span>$/);
  const over = html(<Gauge value={124} text="124 % of capacity" status="critical" />);
  assert.match(over, /<span class="ui-gauge" data-status="critical">/);
  assert.match(over, /width="100"/, 'a share above the whole fills the bar; its text says it whole');
  assert.match(html(<Gauge value={-3} text="0 %" />), /width="0"/);
  assert.doesNotMatch(gauge + over, /style=/);
});

test('a list cell with a gauge draws its text and sub-lines, then the gauge under them', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const rows = [{ key: '1', cells: { name: { text: 'TT-01', strong: true },
    density: { text: '7.4 kg/m³', sub: ['Over'], gauge: { value: 12, text: '12 % of capacity', status: null } } }, actions: [] }];
  const page = html(<ListPage {...LIST_PROPS} table={{ ...LIST_PROPS.table, rows,
    columns: [{ key: 'name', label: 'Unit' }, { key: 'density', label: 'Density · capacity' }] }} />);
  assert.match(page, /<td><span>7\.4 kg\/m³<\/span><span class="ui-cell-sub">Over<\/span><span class="ui-cell-sub"><span class="ui-gauge">[^]*?<span class="ui-gauge-text">12 % of capacity<\/span><\/span><\/span><\/td>/);
});

test('a list page with groups draws a plate per group, its head and its own table of the shared columns', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const row = (key: string, text: string) => ({ key, cells: { name: { text, strong: true } }, actions: [] });
  const table = { ...LIST_PROPS.table, columns: [{ key: 'name', label: 'Channel' }], rows: [row('1', 'PH'), row('2', 'O2'), row('3', 'TEMP')] };
  const groups = [
    { key: 'a', title: 'PROBE-A · Probe A', chips: [{ kind: 'hold' as const, text: 'Simulated' }], meta: 'Site North · 2 channels', rows: ['1', '3'] },
    { key: 'b', title: 'PROBE-B · Probe B', meta: null, rows: ['2'] },
  ];
  const page = html(<ListPage {...LIST_PROPS} table={table} groups={groups} />);
  const plates = page.split('<section class="ui-plate"').slice(1);
  assert.equal(plates.length, 2);
  assert.match(plates[0] ?? '', /<h2>PROBE-A · Probe A<\/h2><span class="ui-chip"[^>]*>[^]*?Simulated[^]*?<span class="ui-plate-meta">Site North · 2 channels<\/span>/);
  assert.match(plates[0] ?? '', /aria-label="PROBE-A · Probe A"[^]*?PH[^]*?TEMP/);
  assert.doesNotMatch(plates[0] ?? '', />O2</);
  assert.match(plates[1] ?? '', /<h2>PROBE-B · Probe B<\/h2>[^]*?>O2</);
  assert.equal((html(<ListPage {...LIST_PROPS} table={table} />).match(/<table/g) ?? []).length, 1, 'without groups: one table');
});

test('a list page notice may end in a link; one without is as before', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const page = html(<ListPage {...LIST_PROPS} notices={[
    { key: 'none', tone: 'warning', text: '2 systems are not in any production department.', link: { href: '?production_department=none', label: 'Show them' } },
    { key: 'plain', tone: 'neutral', text: 'A plain line.' },
  ]} />);
  assert.match(page, /2 systems are not in any production department\. <a href="\?production_department=none">Show them<\/a><\/div>/);
  assert.match(page, /A plain line\.<\/div>/);
});

test('a list cell may be a closed disclosure; a labelled action shows its word beside its icon', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const rows = [{ key: '1', cells: {
    topic: { text: 'test/probe' },
    payload: { text: null, details: { summary: '{"ts":17954…', lines: ['{"ts":1795440480000}', '7b227473', '21 bytes'] } },
  }, actions: [
    { kind: 'post' as const, href: '/sensors/dead/1/resolve/', label: 'Resolve', icon: 'check-circle' as const, labelled: true },
    { kind: 'link' as const, href: '/x/', label: 'Edit x', icon: 'pencil' as const },
  ] }];
  const page = html(<ListPage {...LIST_PROPS} table={{ ...LIST_PROPS.table, rows,
    columns: [{ key: 'topic', label: 'Topic' }, { key: 'payload', label: 'Payload' }] }} />);
  assert.match(page, /<details class="ui-cell-details"><summary>\{&quot;ts&quot;:17954…<\/summary><span class="ui-cell-sub">\{&quot;ts&quot;:1795440480000\}<\/span><span class="ui-cell-sub">7b227473<\/span><span class="ui-cell-sub">21 bytes<\/span><\/details>/);
  assert.doesNotMatch(page, /<details[^>]* open/, 'closed');
  assert.match(page, /<button type="submit" class="ui-btn"><svg[^]*?<\/svg>Resolve<\/button>/);
  assert.match(page, /<a class="icon-button" href="\/x\/" aria-label="Edit x"/, 'an unlabelled action is the icon button as before');
});

test('a timeline: a lane per place, each span placed in % and said in words, the lane a named picture, no style', async () => {
  const { Timeline } = await import('./index.js');
  const page = html(<Timeline label="Where OXYGEN was bound over time" ticks={[{ x: 0, label: '01.11' }, { x: 50, label: '12.11' }, { x: 100, label: 'now' }]}
    lanes={[
      { key: 'rt', label: 'Research hall › RT-03', spans: [{ key: 'a', x: 0, width: 22.5, tone: 'primary', open: false, label: 'Primary · 01.11.2026 08:00 – 06.11.2026 08:02' }] },
      { key: 'bio', label: 'Biofilter loop', spans: [{ key: 'b', x: 22.5, width: 77.5, tone: 'backup', open: true, label: 'Backup · 06.11.2026 08:02 – now' }] },
    ]} />);
  assert.match(page, /^<figure class="ui-timeline" aria-label="Where OXYGEN was bound over time">/);
  assert.match(page, /<svg class="ui-timeline-track" role="img" aria-label="Research hall › RT-03: Primary · 01\.11\.2026 08:00 – 06\.11\.2026 08:02">/);
  assert.match(page, /<svg x="22\.5%" width="77\.5%" y="4" height="20" class="ui-timeline-span" data-tone="backup" data-open="">/);
  assert.match(page, /<title>Backup · 06\.11\.2026 08:02 – now<\/title>/);
  assert.match(page, /text-anchor="end">now<\/text>/);
  assert.doesNotMatch(page, /style=/);
});

test('a list page draws its timeline in a plate above the table; without one, as before', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const timeline = { title: 'OXYGEN #186 · SIM-BIO-1 · History', label: 'Where OXYGEN was bound', ticks: [{ x: 0, label: '01.11' }],
    lanes: [{ key: 'a', label: 'Loop', spans: [] }] };
  const page = html(<ListPage {...LIST_PROPS} timeline={timeline} />);
  assert.match(page, /<h2>OXYGEN #186 · SIM-BIO-1 · History<\/h2><\/div><figure class="ui-timeline"[^]*<table/);
  assert.doesNotMatch(html(<ListPage {...LIST_PROPS} />), /ui-timeline/);
});

test('a stacked bar: each part a segment as long as its share on the whole, every part in words, no style', async () => {
  const { StackedBar } = await import('./index.js');
  const bar = html(<StackedBar label="Planned today: 6" parts={[
    { key: 'here', label: 'Here now', value: 3, figure: '3', tone: 'ok' },
    { key: 'absent', label: 'Absent', value: 0, figure: '0', tone: 'critical' },
    { key: 'leave', label: 'On leave', value: 3, figure: '3', tone: 'note' },
  ]} />);
  assert.match(bar, /<svg class="ui-stack-bar" viewBox="0 0 6 1" preserveAspectRatio="none" role="img" aria-label="Planned today: 6\. Here now 3, Absent 0, On leave 3">/);
  assert.match(bar, /<rect class="ui-stack-seg" data-tone="ok" x="0" y="0" width="3" height="1"><\/rect><rect class="ui-stack-seg" data-tone="note" x="3" y="0" width="3" height="1"><\/rect><\/svg>/);
  assert.match(bar, /<li data-tone="critical"><span class="ui-stack-swatch" aria-hidden="true"><\/span><strong class="ui-stack-figure">0<\/strong><span>Absent<\/span><\/li>/);
  assert.doesNotMatch(bar, /style=/);
  const empty = html(<StackedBar label="Planned today: 0" empty="Nobody is expected today" parts={[{ key: 'here', label: 'Here now', value: 0, figure: '0', tone: 'ok' }]} />);
  assert.doesNotMatch(empty, /<svg/);
  assert.match(empty, /<p class="ui-stack-empty">Nobody is expected today<\/p>/);
});

test('an organisation tree: nested lists in a named frame, the people behind a native disclosure, words from props', async () => {
  const { OrgTree } = await import('./index.js');
  const tree = html(<OrgTree label="Organization chart" describedBy="s c" nodes={[
    { key: 'a', kind: 'office', name: 'Test Office', kindLabel: 'Office', count: '1 person · 3 in all',
      manager: { label: 'Manager:', name: 'Test Lead', title: 'Test coordinator' },
      people: { summary: 'Show 1 person', list: [{ key: 'p', name: 'Test Person', title: null }] },
      children: [{ key: 'b', kind: 'office', name: 'Test Accounts', kindLabel: 'Office', count: '2 people', children: [] }] },
    { key: 'c', kind: 'production_root', name: 'Production', href: '/production/team/org/', kindLabel: 'Production', count: '4 people', children: [] },
  ]} />);
  assert.match(tree, /^<div class="ui-org-frame" role="region" tabindex="0" aria-label="Organization chart" aria-describedby="s c"><ul class="ui-org-tree" role="list">/);
  assert.match(tree, /<span class="sr-only">Manager: <\/span>Test Lead<span class="ui-cell-sub">Test coordinator<\/span>/);
  assert.match(tree, /<details class="ui-org-people"><summary>Show 1 person<\/summary>/);
  assert.match(tree, /<ul class="ui-org-level" role="list"><li class="ui-org-node" data-kind="office">.*Test Accounts/);
  assert.match(tree, /<a href="\/production\/team\/org\/">Production<\/a>/);
  assert.doesNotMatch(tree, /style=/);
});

test('a roster: a week of people, a cell its plan as a link, an empty day "+", findings in words; the paint bar first', async () => {
  const { RosterGrid } = await import('./index.js');
  const { ROSTER_PROPS } = await import('../../test/pages/roster-props.js');
  const page = html(<RosterGrid {...ROSTER_PROPS} />);
  assert.match(page, /<form class="ui-roster-paint" action="\/hr\/schedule\/plan\/" method="post"><input type="hidden" name="csrfmiddlewaretoken" value="test-token"\/><input type="hidden" name="next" value="\/hr\/schedule\/\?week=2026-11-23"\/><input type="hidden" name="shift" value=""\/>/);
  assert.match(page, /<div role="group" aria-label="Paint" class="ui-roster-choices">/);
  assert.match(page, /<button type="button" class="ui-roster-choice" aria-pressed="false" data-kind="shift" data-tone="1" title="Test day shift">TD<\/button>/);
  assert.match(page, /<th scope="col">Mon 23.11.2026<\/th>/);
  assert.match(page, /<a class="ui-roster-link" href="\/hr\/schedule\/7\/" title="Test day shift 07:00–15:00"><span class="ui-roster-plan" data-kind="shift" data-tone="1">TD<\/span>/);
  assert.match(page, /<a class="ui-roster-add" href="\/hr\/schedule\/new\/\?employee=1&amp;day=2026-11-24" aria-label="Plan this day" title="Plan this day">/);
  assert.match(page, /<td data-roster-cell="" data-finding="block">.*Less than 11 h of rest before this shift\./);
  assert.match(page, /<span class="ui-cell-sub">Test holiday<\/span>/);
  assert.match(page, /<td class="num">45<span class="ui-roster-finding">.*More than the standard week/);
  assert.doesNotMatch(page, /ui-roster-pick/, 'cells are links until a paint is chosen');
  assert.doesNotMatch(page, /style=/);
});

test('a server form posts the CSRF token, says the form\'s errors in an alert, and its submit is ready until it posts', () => {
  const form = html(<ServerForm action="/x/" csrfToken="t" label="Save" formErrors={['Choose a site.']}
    actions={<Button type="submit" variant="primary">Save</Button>} noValidate>x</ServerForm>);
  assert.match(form, /<form aria-label="Save" noValidate="" action="\/x\/" method="post">/);
  assert.match(form, /<input type="hidden" name="csrfmiddlewaretoken" value="t"\/>/);
  assert.match(form, /<div class="ui-notice" data-tone="critical" role="alert">.*<li>Choose a site\.<\/li>/);
  assert.doesNotMatch(form, /disabled/);
  const get = html(<ServerForm action="/x/" csrfToken="t" label="Find" method="get" actions={null}>x</ServerForm>);
  assert.doesNotMatch(get, /csrfmiddlewaretoken/, 'a GET form never carries the token into the address');
});

test('a blocked delete: the plan\'s reasons are said and its Delete button is off (review F4); an open plan\'s is on', async () => {
  const { ConfirmDelete } = await import('../pages/ConfirmDelete.js');
  const { BLOCKED_PROPS, OPEN_PROPS } = await import('../../test/pages/delete-props.js');
  const blocked = html(<ConfirmDelete {...BLOCKED_PROPS} />);
  assert.match(blocked, /<button[^>]*type="submit"[^>]*disabled=""[^>]*>Delete leave type<\/button>|<button[^>]*disabled=""[^>]*type="submit"[^>]*>Delete leave type<\/button>/);
  assert.match(blocked, /This leave type cannot be deleted yet\..*2 leave requests use it\./);
  const open = html(<ConfirmDelete {...OPEN_PROPS} />);
  assert.doesNotMatch(open, /<button[^>]*disabled/);
});

test('a list page notice may have a title, more links and the items it is about; a help sentence has the info glyph', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const page = html(<ListPage {...LIST_PROPS} notices={[
    { key: 'points', tone: 'info', text: 'The points of TT-01.', link: { href: '/sampling-points/', label: 'Show all' },
      more: [{ href: '/sampling-points/new/?unit=1', label: 'Add a point to it' }] },
    { key: 'missing', tone: 'warning', title: 'Fish with no limit', text: 'Add the limits your vet gives.',
      items: ['Atlantic salmon (Any water): Oxygen, pH', 'Lumpfish (Sea water): pH'] },
  ]} />);
  assert.match(page, /<div class="ui-notice" role="status">[^]*?The points of TT-01\. <a href="\/sampling-points\/">Show all<\/a><span> · <a href="\/sampling-points\/new\/\?unit=1">Add a point to it<\/a><\/span><\/div>/);
  assert.doesNotMatch(page, /data-tone="info"/, 'a help sentence is drawn as a neutral notice');
  assert.match(page, /<div class="ui-notice" data-tone="warning" role="status">[^]*?<strong class="ui-notice-title">Fish with no limit<\/strong>Add the limits your vet gives\.<ul class="ui-notice-items"><li>Atlantic salmon \(Any water\): Oxygen, pH<\/li><li>Lumpfish \(Sea water\): pH<\/li><\/ul>/);
});

test('a list page as cards: a card per row of one grid, its title and chip, its facts with nothing empty, its foot and actions', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const row = (key: string, contact: string | null) => ({ key, cells: {
    site: { text: `Site ${key}`, href: `/sites/${key}/edit/`, strong: true, sub: [`S-${key}`] },
    status: { text: null, chip: { kind: 'ok' as const, text: 'Active' } },
    type: { text: 'Sea' }, contact: { text: contact }, created: { text: 'Created 14.03.2026' },
  }, actions: [{ kind: 'link' as const, href: `/sites/${key}/edit/`, label: `Edit Site ${key}`, icon: 'pencil' as const }] });
  const columns = ['site', 'status', 'type', 'contact', 'created'].map((key) => ({ key, label: key[0]?.toUpperCase() + key.slice(1) }));
  const page = html(<ListPage {...LIST_PROPS} table={{ ...LIST_PROPS.table, columns, rows: [row('1', 'a@example.com'), row('2', null)] }}
    cards={{ chip: 'status', foot: ['created'] }} />);
  assert.doesNotMatch(page, /<table/, 'cards, no table');
  const cards = page.split('<li class="ui-list-card"').slice(1);
  assert.equal(cards.length, 2);
  assert.match(cards[0] ?? '', /<h2 class="ui-list-card-title"><a href="\/sites\/1\/edit\/">Site 1<\/a><span class="ui-cell-sub">S-1<\/span><\/h2><span class="ui-chip"[^>]*>[^]*?Active/);
  assert.match(cards[0] ?? '', /<dt>Type<\/dt><dd><span>Sea<\/span><\/dd><\/div><div><dt>Contact<\/dt><dd><span>a@example\.com<\/span><\/dd>/);
  assert.doesNotMatch(cards[1] ?? '', /<dt>Contact<\/dt>/, 'a fact with nothing to say is left out');
  assert.doesNotMatch(cards[0] ?? '', /<dt>Created<\/dt>|<dt>Status<\/dt>/, 'the chip and the foot are not facts');
  assert.match(cards[0] ?? '', /<div class="ui-list-card-foot"><span><span>Created 14\.03\.2026<\/span><\/span><span class="ui-list-card-actions"><a class="icon-button" href="\/sites\/1\/edit\/" aria-label="Edit Site 1"/);
  assert.doesNotMatch(page, /style=/);
});

test('a list filter may be a box ticked or not, named by its words in sight', async () => {
  const { ListPage } = await import('./index.js');
  const { LIST_PROPS } = await import('../../test/pages/list-props.js');
  const toolbar = { ...LIST_PROPS.toolbar, filters: [
    { kind: 'check' as const, name: 'alerts', label: 'Only warnings and criticals', value: '1', checked: true, options: [] }] };
  const page = html(<ListPage {...LIST_PROPS} toolbar={toolbar} />);
  assert.match(page, /<label class="ui-check"><input type="checkbox" name="alerts" value="1" checked=""\/><span>Only warnings and criticals<\/span><\/label>/);
  const off = html(<ListPage {...LIST_PROPS} toolbar={{ ...toolbar, filters: [{ ...toolbar.filters[0]!, checked: false }] }} />);
  assert.doesNotMatch(off, /checked=""/);
});
