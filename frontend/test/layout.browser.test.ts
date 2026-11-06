// The page layout rules of static/css in a real browser (Playwright on the machine's own Chrome or Edge; skipped where
// there is none), on the markup the templates print: a page never scrolls sideways at a phone's, a tablet's or a desktop's
// width; a wide table scrolls in its own frame and shows that more of it lies to a side; a table's text column keeps a
// readable width; row actions stand apart; a water value's origin and age stand on a line of their own and break only
// between the two; a form shows one primary button, last, on the row of its other buttons. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { chromium, type Page } from 'playwright-core';

const BROWSERS = [
  process.env.CHROME_PATH ?? '',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter((path) => path && existsSync(path));
const CSS = resolve('static/css');
const WIDTHS = [390, 1024, 1440];

const cells = (count: number, text: string): string => Array.from({ length: count }, (_, i) => `<td>${text} ${i}</td>`).join('');
const head = (count: number): string => Array.from({ length: count }, (_, i) => `<th scope="col">Column ${i}</th>`).join('');
const options = '<option>All production departments</option><option>Bergen Hatchery · Hatchery hall A · the long name</option>';

// What the templates print, one block per kind of part that once widened a page (Production › Team leave, Equipment,
// Feeding records, the role form, a report draft, the card designer, Health events, a filed report).
const MARKUP = `
<nav class="view-tabs" aria-label="Views"><a class="view-tab" href="#" aria-current="page">Pending 3</a><a class="view-tab" href="#">Approved 12</a>
  <a class="view-tab" href="#">Declined 2</a><a class="view-tab" href="#">Cancelled 1</a><a class="view-tab" href="#">Recurring tasks</a><a class="view-tab" href="#">All 19</a></nav>
<div class="toolbar"><form class="search"><input type="search" placeholder="Search"></form>
  <form method="get" class="toolbar-filter feeding-filters"><select>${options}</select><select>${options}</select><select>${options}</select>
    <label class="date-filter">From <input type="date"></label><label class="date-filter">To <input type="date"></label></form></div>
<div class="toolbar"><form method="get" class="toolbar-filter"><select>${options}</select><select>${options}</select></form></div>
<div class="notice notice-error" role="alert"><strong>Notify Mattilsynet</strong> A listed disease is suspected.
  <ul><li><a href="#">Pancreas disease (PD) · 2026-10-20 · Tromsø Grow-out</a> · Tromsø Grow-out · Suspected</li></ul></div>
<p>Content hash: <code>9deb58267921dd0780e377df9559947b92ce63d6aa0f3c2b9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8</code> · <a href="#">The values to type</a></p>
<div class="detail"><section class="detail-section"><h2>As filed</h2><dl class="audit-changes"><div><dt>Organisation number</dt>
  <dd>/units/f62e32a3-1c4d-4b7e-9a2f-0e8d7c6b5a49/avg_weight_g_and_some_more_of_the_same_unbroken_key</dd></div></dl></section></div>
<div class="form-grid form-grid-design"><div class="field"><label>Layout</label><div class="designer-bar"><div class="designer-palette">
  <button type="button" class="button button-ghost">Value</button><button type="button" class="button button-ghost">Value against its limits and the bands of a parameter</button></div></div></div></div>
<div class="field field-set"><div class="matrix-wrap table-wrap"><table class="matrix"><thead><tr><th>Area</th>${head(9)}</tr></thead>
  <tbody><tr><th scope="row">Production units</th>${Array.from({ length: 9 }, () => '<td><label class="matrix-check"><input type="checkbox"><span class="sr-only">Production units: a long permission name</span></label></td>').join('')}</tr></tbody></table></div></div>

<div class="table-wrap" id="wide"><table class="data-table"><thead><tr>${head(12)}<th scope="col"><span class="sr-only">Actions</span></th></tr></thead>
  <tbody><tr><th scope="row"><span class="row-title">HA-K01</span><span class="row-sub"><span class="chip nowrap">E-2026-002 · EPA+DHA 1.0 %, low density · R1</span></span><span class="row-sub nowrap">Hatchery hall A · Bergen Hatchery</span></th>${cells(11, 'a figure')}
  <td class="row-actions" id="stock-actions"><a class="op-void" href="#">Transfer</a><a class="op-void" href="#">Issue</a><a class="op-void" href="#">Write off</a><a class="op-void" href="#">Return</a></td></tr></tbody></table></div>
<div class="table-wrap" id="narrow"><table class="data-table"><thead><tr>${head(2)}</tr></thead><tbody><tr>${cells(2, 'x')}</tr></tbody></table></div>

<div style="width: min(26rem, 100%)" id="drawer"><div class="table-wrap"><table class="data-table drawer-table"><thead><tr><th scope="col">Batch</th>${head(5)}</tr></thead>
  <tbody><tr><td id="batch-cell"><span class="row-title">B-2026-001</span><span class="row-sub">Smolt · since 23 Oct 2026</span><span class="row-sub">No year class · Farmed or wild-caught not given · <a href="#">Batch details</a></span></td>
  <td class="num">15,830</td><td class="num">66.0 g<span class="row-sub">weighed 3 Nov 2026</span></td><td class="num">1,045 kg</td><td class="num">99.2 %</td><td class="num">120 kg</td></tr></tbody></table></div></div>

<div class="table-wrap"><table class="data-table water-table"><tbody><tr><th scope="row">HA-K01</th>
  <td class="num wq wq-ok" id="water-value">13.4<span class="wq-source"><span class="wq-origin">unit sensor #1</span> · <span class="wq-age">12 s ago</span></span></td></tr></tbody></table></div>
<article class="monitor-card" style="width: 21rem"><section class="monitor-section monitor-water"><div class="monitor-point"><dl class="metrics">
  <div><dt>CO₂ (mg/L)</dt><dd><span class="wq wq-ok">13.4</span></dd><dd class="row-sub wq-said"><span class="wq-source"><span class="wq-origin" id="card-origin">Meter or test kit</span> · <span class="wq-age" id="card-age">2 d ago</span></span></dd></div>
  <div><dt>pH</dt><dd><span class="wq wq-ok">13.4</span></dd><dd class="row-sub wq-said"><span class="wq-source"><span class="wq-origin">unit sensor #12</span> · <span class="wq-age">just now</span></span></dd></div>
  <div><dt>O₂ (mg/L)</dt><dd><span class="wq wq-ok">13.4</span></dd><dd class="row-sub wq-said"><span class="wq-source"><span class="wq-origin">system sensor #3</span> · <span class="wq-age">40 s ago</span></span></dd></div></dl></div></section></article>

<div class="monitor-grid" lang="nb"><article class="monitor-card monitor-warning" id="nb-card"><div class="monitor-card-head"><h3>HA-K03</h3></div>
  <dl class="metrics"><div><dt>Tap</dt><dd>170</dd><dd class="row-sub">170 døde · 0 utsortert</dd></div><div><dt>Fiskegrupper</dt><dd>1</dd>
  <dd class="row-sub">B-2026-001</dd></div><div><dt>Sist veid</dt><dd>Tilbakeholdelsestid</dd></div></dl>
  <section class="monitor-section monitor-water"><div class="monitor-point"><dl class="metrics">
  <div><dt>O₂ (%)</dt><dd><span class="wq wq-ok">98,6</span></dd><dd class="row-sub wq-said"><span class="wq-source"><span class="wq-origin">enhetssensor #19</span> · <span class="wq-age">akkurat nå</span></span></dd></div>
  <div><dt>CO₂ (mg/L)</dt><dd><span class="wq wq-ok">11,5</span></dd><dd class="row-sub wq-said"><span class="wq-source"><span class="wq-origin">systemsensor #221</span> · <span class="wq-age">akkurat nå</span></span></dd></div>
  <div><dt>Alkalitet (mg/L)</dt><dd><span class="wq wq-ok">90</span></dd><dd class="row-sub wq-said"><span class="wq-source"><span class="wq-origin">systemsensor #224</span> · <span class="wq-age">akkurat nå</span></span></dd></div>
  </dl></div></section></article><article class="monitor-card"><h3>HA-K04</h3></article><article class="monitor-card"><h3>HA-K05</h3></article></div>
<form method="post" class="form" id="approve"><p>Approve the request?</p>
  <div class="form-actions"><a class="button button-ghost" href="#">Cancel</a><button type="submit" class="button">Approve</button></div></form>
<div class="tabs" role="tablist"><button type="button" role="tab" class="tab" data-tab="details">Details</button><button type="button" role="tab" class="tab" data-tab="withdrawal">Withdrawal</button></div>
<form method="post" class="record-form" id="record"><section class="tab-panel" data-panel="details" hidden><p>Name</p></section>
  <div class="form-actions"><a class="button button-ghost" href="#">Cancel</a><button type="submit" class="button button-inline">Save medicine</button></div></form>
<section class="tab-panel row-list" data-panel="withdrawal"><form method="post"><div class="form-actions" id="rows-actions">
  <button type="button" class="button button-ghost">Add species</button><button type="submit" class="button button-inline">Save withdrawal</button></div></form></section>
`;

function page(): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>layout</title>
<link rel="stylesheet" href="/css/base.css"><link rel="stylesheet" href="/css/app.css"><link rel="stylesheet" href="/css/components.css">
<link rel="stylesheet" href="/css/monitor.css"></head><body><div class="shell"><aside class="rail"></aside><div class="console">
<header class="topbar"><div class="title-block"><h1>Layout</h1></div></header><main class="content">${MARKUP}</main></div></div></body></html>`;
}

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const file = join(CSS, (request.url ?? '').replace(/^\/css\//, ''));
    if (request.url === '/') response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page());
    else if (request.url?.startsWith('/css/') && file.startsWith(CSS) && existsSync(file)) {
      response.writeHead(200, { 'Content-Type': 'text/css' }).end(readFileSync(file));
    } else response.writeHead(404).end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

type Box = { left: number; right: number; top: number; bottom: number; width: number };
const box = (tab: Page, selector: string): Promise<Box> => tab.locator(selector).first().evaluate((element) => {
  const r = element.getBoundingClientRect();
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width };
});

// A thin strip at a frame's inner edge, in the header row, left of its first words and right of its last: the cue is what differs there
// between the frame scrolled to its start and to its end.
async function strip(tab: Page, selector: string, side: 'left' | 'right'): Promise<Buffer> {
  await tab.locator(selector).evaluate((element) => element.scrollIntoView({ block: 'center' }));
  const frame = await box(tab, selector);                 // in the window, as the clip is
  const x = side === 'right' ? frame.right - 10 : frame.left + 2;
  return tab.screenshot({ clip: { x, y: frame.top + 12, width: 8, height: 6 } });   // below the rounded corners
}

async function scrollFrame(tab: Page, selector: string, to: 'start' | 'end'): Promise<void> {
  await tab.locator(selector).evaluate((element, end) => { element.scrollLeft = end ? element.scrollWidth : 0; }, to === 'end');
  await tab.waitForTimeout(50);
}

test('the page layout', { skip: BROWSERS.length ? false : 'no Chrome or Edge on this machine' }, async (t) => {
  const server = await serve();
  const address = server.address();
  const browser = await chromium.launch({ executablePath: BROWSERS[0], headless: true });
  try {
    const tab = await browser.newPage();
    await tab.goto(`http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}/`);

    for (const width of WIDTHS) {
      await tab.setViewportSize({ width, height: 900 });
      await tab.waitForTimeout(50);

      await t.test(`no page scrolls sideways at ${width} px`, async () => {
        const [scroll, client, wide] = await tab.evaluate(() => {
          const width = document.documentElement.clientWidth;
          const past = [...document.querySelectorAll('main *')].filter((element) => !element.parentElement?.closest('.table-wrap')
            && element.getBoundingClientRect().right > width + 1);
          const outermost = past.filter((element) => !past.includes(element.parentElement as Element));
          return [document.documentElement.scrollWidth, width, outermost.map((element) => `${element.tagName}.${element.className}`).join(', ')];
        });
        assert.ok(scroll <= client, `the page is ${scroll} px wide in a ${client} px window: ${wide}`);
      });

      await t.test(`a wide table shows at ${width} px that it goes on, on the side it goes on`, async () => {
        const [scroll, client] = await tab.locator('#wide').evaluate((element) => [element.scrollWidth, element.clientWidth]);
        assert.ok(scroll > client, 'the fixture table is wider than its frame');
        await scrollFrame(tab, '#wide', 'start');
        const rightAtStart = await strip(tab, '#wide', 'right');
        const leftAtStart = await strip(tab, '#wide', 'left');
        await scrollFrame(tab, '#wide', 'end');
        assert.notDeepEqual(rightAtStart, await strip(tab, '#wide', 'right'), 'no cue at the right while more lies there');
        assert.notDeepEqual(leftAtStart, await strip(tab, '#wide', 'left'), 'no cue at the left once more lies there');
        await scrollFrame(tab, '#wide', 'start');
        // A table that fits has no cue: both edges read as its middle does.
        assert.deepEqual(await strip(tab, '#narrow', 'right'), await strip(tab, '#narrow', 'left'));
      });

      await t.test(`a table's first column leaves room for the next at ${width} px`, async () => {
        await scrollFrame(tab, '#wide', 'start');
        const frame = await box(tab, '#wide');
        const second = await box(tab, '#wide tbody td');
        // On a phone the first column takes at most about half of the frame, so the next column shows beside it.
        const share = (second.left - frame.left) / frame.width;
        assert.ok(share <= 0.6, `the first column takes ${Math.round(share * 100)} % of the frame`);
      });
    }

    await tab.setViewportSize({ width: 1440, height: 900 });
    await tab.waitForTimeout(50);

    await t.test('nothing of a monitoring card spills out of it, in Norwegian at 390 and 1440 px', async () => {
      for (const width of [390, 1440]) {
        await tab.setViewportSize({ width, height: 900 });
        await tab.waitForTimeout(50);
        const spill = await tab.locator('#nb-card').evaluate((card) => {
          const edge = card.getBoundingClientRect().right;
          return [...card.querySelectorAll('*')].filter((element) => element.getBoundingClientRect().right > edge + 1)
            .map((element) => `${element.tagName}.${element.className} "${(element.textContent ?? '').trim().slice(0, 30)}"`);
        });
        assert.deepEqual(spill, [], `at ${width} px`);
      }
      await tab.setViewportSize({ width: 1440, height: 900 });
      await tab.waitForTimeout(50);
    });

    await t.test('a text cell is not squeezed to a word a line (the unit drawer\'s batches)', async () => {
      const cell = await box(tab, '#batch-cell');
      assert.ok(cell.width >= 150, `the batch cell is ${cell.width} px wide`);
    });

    await t.test('row actions stand apart', async () => {
      const links = await tab.locator('#stock-actions a').evaluateAll((elements) => elements.map((element) => {
        const r = element.getBoundingClientRect();
        return [r.left, r.right];
      }));
      for (let i = 1; i < links.length; i++) {
        assert.ok(links[i][0] - links[i - 1][1] >= 8, `actions ${i - 1} and ${i} are ${links[i][0] - links[i - 1][1]} px apart`);
      }
    });

    await t.test('a water value\'s origin and age stand on a line under the value', async () => {
      const value = await tab.locator('#water-value').evaluate((element) => {
        const range = document.createRange();
        range.setStart(element.firstChild as Node, 0);
        range.setEnd(element.firstChild as Node, (element.firstChild as Text).length);
        return range.getBoundingClientRect().bottom;
      });
      const source = await box(tab, '#water-value .wq-source');
      assert.ok(source.top >= value - 1, `the origin starts at ${source.top}, the value ends at ${value}`);
    });

    await t.test('a monitoring card breaks a value’s origin line only between the origin and the age', async () => {
      for (const selector of ['#card-origin', '#card-age']) {
        const lines = await tab.locator(selector).evaluate((element) => element.getClientRects().length);
        assert.equal(lines, 1, `${selector} runs over ${lines} lines`);
      }
    });

    await t.test('a form\'s primary button is last, on the row of the others', async () => {
      const cancel = await box(tab, '#approve .button-ghost');
      const approve = await box(tab, '#approve button[type=submit]');
      assert.ok(Math.abs(cancel.top - approve.top) < 2, 'Cancel and Approve are on one row');
      assert.ok(approve.left > cancel.right, 'Approve comes after Cancel');
      assert.ok(approve.width < 400, `Approve is ${approve.width} px wide`);
    });

    await t.test('a tab saved on its own shows only its own primary button', async () => {
      const visible = await tab.locator('.button-inline:visible, .form-actions > .button:not(.button-ghost):visible').allTextContents();
      assert.deepEqual(visible.filter((text) => /Save/.test(text)), ['Save withdrawal']);
    });
  } finally {
    await browser.close();
    server.close();
  }
});
