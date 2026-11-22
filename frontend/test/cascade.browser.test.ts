// The cascade of the product's style sheets in a real browser (Playwright on the machine's own Chrome or Edge; skipped
// where there is none, never under CI=1), on the sheets in the order the templates link them (frontend/test/sheets.ts) and
// on what the real templates print (frontend/test/pages/*.html, core/layout_pages.py) or, where no part is drawn yet, on a
// copy of a template's markup that is checked against the template. It holds what review of slice 1a found lost when the
// patterns moved into ds.css: the rail's collapse button (hidden on a phone, readable on the rail in all five themes), a
// link card's focus ring, a tab strip that keeps its current tab on a phone, the charts' text size, and the rules of a
// page for one element of a pattern that must still win over the pattern (the printed report's Print button and tables, a
// chip's size and link colour, a toolbar control's weight, the search icon). Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import { join, resolve } from 'node:path';

import { chromium, type Page } from 'playwright-core';

import { BROWSERS, skipWithout } from './browsers.js';
import { linksOf, mirrors } from './sheets.js';

const PAGES = resolve('frontend/test/pages');
const THEMES = ['fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];
const part = (name: string): string => readFileSync(join(PAGES, `${name}.html`), 'utf8');
const ICON = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';

// Markup copied from templates, each opening tag checked against its template (`copied` below).
const TOGGLE = `<button type="button" class="icon-button rail-toggle" data-nav-toggle aria-controls="rail" aria-expanded="true" title="Collapse menu">${ICON}<span class="sr-only">Collapse menu</span></button>`;
const TILE = `<ul class="tiles" role="list"><li><a class="tile" href="#"><span class="tile-count">12</span><span class="tile-label">Tanks</span></a></li></ul>`;
const FILTERS = `<form method="get" class="monitor-toolbar ui-toolbar" role="search"><div class="monitor-filters">
<label>Site<select name="site" data-autosubmit><option value="">All sites</option><option>Bergen</option></select></label>
<label class="monitor-search">Search<input type="search" name="q" value="" placeholder="Search unit"></label></div></form>`;
const SEARCH = `<div class="ui-toolbar units-toolbar"><form method="get" class="ui-search units-search" role="search">${ICON.replace('M4 6h16M4 12h16M4 18h16', 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5')}<label class="sr-only" for="units-search">Search unit, batch or species</label><input id="units-search" type="search" name="q" value="" placeholder="Search unit, batch or species"></form></div>`;
const CHARTS = `<div id="chart-box"><div class="calc-card" id="ph-card"><svg class="ph-chart" viewBox="0 0 400 300" role="img" aria-label="pH plot">
<g class="ph-ticks"><text x="20" y="290">6</text><text x="200" y="290">7.5</text></g><text class="ph-axis" x="200" y="270">pH (NBS)</text><text class="ph-label" x="120" y="100">pH 7</text></svg></div>
<figure class="deffeyes" id="deffeyes-card"><svg class="deffeyes-chart" viewBox="0 0 600 600" role="img" aria-label="Water quality management chart">
<g class="deffeyes-ticks"><text x="20" y="590">0</text><text x="300" y="590">3</text></g><text class="deffeyes-axis" x="300" y="570">DIC (mmol/L)</text><text class="deffeyes-ph" x="200" y="200">pH 8.5</text></svg></figure></div>`;
const REPORT = `<header class="report-head"><div><h1 class="report-title">Water chemistry report</h1></div>
<button type="button" class="button button-inline report-print" data-print>${ICON}Print</button></header>
<div class="table-wrap"><table class="data-table report-table"><caption>Values</caption><tbody><tr><th scope="row">Temperature</th><td class="num">12</td></tr></tbody></table></div>`;

const copied: [string, string[]][] = [
  ['app_base.html', ['<button type="button" class="icon-button rail-toggle" data-nav-toggle aria-controls="rail" aria-expanded="true"']],
  ['_overview_tiles.html', ['<ul class="tiles" role="list">', '<li><a class="tile" href="{{ tile.url }}"><span class="tile-count">']],
  ['monitoring/monitor.html', ['<form method="get" class="monitor-toolbar ui-toolbar" role="search">', '<div class="monitor-filters">',
    '<label class="monitor-search">', '<select name="site" data-autosubmit>']],
  ['farm/production_units.html', ['<div class="ui-toolbar units-toolbar">', '<form method="get" class="ui-search units-search" role="search">']],
  ['farm/water_calculator_report.html', ['<button type="button" class="button button-inline report-print"', '<table class="data-table report-table">']],
];

function app(): string {
  return `<!doctype html><html lang="en" data-theme="fjord"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>cascade</title>
${linksOf('app_base.html', ['monitor'])}</head><body><div class="shell"><aside class="rail" id="rail"><div class="rail-head ui-rail-head">${TOGGLE}</div>
<nav class="rail-nav"><a class="rail-link" id="rail-units" href="#" data-area="water">${ICON}<span class="rail-label">Production units</span></a></nav></aside>
<div class="console"><header class="topbar"></header><main class="content" id="content" data-measure="fluid">
<section id="part-tiles">${TILE}<a class="ui-card" id="link-card" href="#">A link card</a></section>
<section id="part-tabs">${part('tabs')}</section><section id="part-report-tabs">${part('report-tabs')}</section>
<section id="part-filters">${FILTERS}${SEARCH}</section><section id="part-charts">${CHARTS}</section>
<section id="part-meal">${part('meal')}</section><section id="part-overview">${part('overview')}</section>
</main></div></div></body></html>`;
}

// The printed report is a page of its own: its own link list (farm/water_calculator_report.html).
function report(): string {
  return `<!doctype html><html lang="en" data-theme="fjord"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>report</title>
${linksOf('farm/water_calculator_report.html')}</head><body class="report">${REPORT}</body></html>`;
}

const SERVED: [string, string, string][] = [['/css/', resolve('static/css'), 'text/css'], ['/fonts/', resolve('static/fonts'), 'font/woff2']];

function serve(): Promise<Server> {
  const server = createServer((request, response) => {
    const url = request.url ?? '';
    if (url === '/' || url === '/report') {
      return void response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(url === '/' ? app() : report());
    }
    for (const [prefix, root, type] of SERVED) {
      const file = join(root, url.slice(prefix.length));
      if (url.startsWith(prefix) && file.startsWith(root) && existsSync(file)) {
        return void response.writeHead(200, { 'Content-Type': type }).end(readFileSync(file));
      }
    }
    response.writeHead(404).end();
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done(server)));
}

type Rgba = [number, number, number, number];
const colours = (css: string): Rgba[] => [...css.matchAll(/rgba?\(([^)]+)\)/g)].map((found) => {
  const [r = 0, g = 0, b = 0, a = 1] = (found[1] ?? '').split(/[ ,/]+/).filter(Boolean).map(Number);
  return [r, g, b, a];
});
const luminance = ([r, g, b]: Rgba): number => {
  const lin = (value: number): number => { const c = value / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
};
const contrast = (a: Rgba, b: Rgba): number => {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
};
const over = (top: Rgba, under: Rgba): Rgba => [0, 1, 2].map((i) => top[3] * (top[i] ?? 0) + (1 - top[3]) * (under[i] ?? 0)).concat(1) as Rgba;

/** What the token `value` (a CSS value written with var()) is on screen for `property`, as the browser computes it. */
const resolved = (tab: Page, property: string, value: string): Promise<string> => tab.evaluate(([name, css]) => {
  const probe = document.createElement('i');
  probe.style.setProperty(name as string, css as string);
  document.body.append(probe);
  const out = getComputedStyle(probe).getPropertyValue(name as string);
  probe.remove();
  return out;
}, [property, value]);

test('the cascade of the product\'s sheets', { skip: skipWithout(BROWSERS) }, async (t) => {
  await t.test('the markup these tests copy is still what the templates print', () => {
    for (const [template, tags] of copied) assert.deepEqual(mirrors(template, ...tags), [], template);
  });

  const server = await serve();
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await chromium.launch({ executablePath: BROWSERS[0], headless: true });
  try {
    const tab = await browser.newPage({ reducedMotion: 'reduce' });
    await tab.goto(`${origin}/`);
    await tab.evaluate(async () => {
      await Promise.all(['400 15px "Atkinson Hyperlegible Next"', '600 24px "Bricolage Grotesque"'].map((face) => document.fonts.load(face)));
      await document.fonts.ready;
    });

    await t.test('the rail\'s collapse button is hidden below 1024 px and readable on the rail at 1280 px in all five themes, at rest and hovered', async () => {
      await tab.setViewportSize({ width: 390, height: 900 });
      assert.equal(await tab.locator('.rail-toggle').evaluate((button) => getComputedStyle(button).display), 'none', 'the rail is a sheet on a phone: no collapse button');
      await tab.setViewportSize({ width: 1280, height: 900 });
      for (const theme of THEMES) {
        await tab.evaluate((name) => { document.documentElement.dataset.theme = name; }, theme);
        await tab.mouse.move(2, 2);
        const rest = await tab.evaluate(() => {
          const button = document.querySelector('.rail-toggle')!;
          const rail = getComputedStyle(document.querySelector('.rail')!);
          return { display: getComputedStyle(button).display, color: getComputedStyle(button).color, backdrop: `${rail.backgroundColor} ${rail.backgroundImage}` };
        });
        assert.notEqual(rest.display, 'none', theme);
        const [ink] = colours(rest.color) as [Rgba];
        for (const under of colours(rest.backdrop)) {          // the rail's colour and every stop of its gradient
          assert.ok(contrast(ink, under) >= 3, `${theme}: the collapse icon is ${contrast(ink, under).toFixed(2)}:1 on the rail (3:1 needed)`);
        }
        await tab.hover('.rail-toggle');
        const hovered = await tab.evaluate(() => {
          const style = getComputedStyle(document.querySelector('.rail-toggle')!);
          return { color: style.color, background: style.backgroundColor, token: getComputedStyle(document.documentElement).getPropertyValue('--rail-hover') };
        });
        assert.deepEqual(colours(hovered.background), colours(hovered.token), `${theme}: the hover is the rail's own hover tone, not the light surface of a page's icon button`);
        const [strong] = colours(hovered.color) as [Rgba];
        for (const under of colours(rest.backdrop)) {
          assert.ok(contrast(strong, over(colours(hovered.background)[0] as Rgba, under)) >= 3, `${theme}: the hovered collapse icon`);
        }
      }
      await tab.evaluate(() => { document.documentElement.dataset.theme = 'fjord'; });
    });

    await t.test('a link card keeps the page\'s focus ring: its own shadow does not replace it', async () => {
      await tab.setViewportSize({ width: 1280, height: 900 });
      const ring = await resolved(tab, 'box-shadow', 'var(--ring-focus)');
      assert.match(ring, /\d+px/, 'the ring token has a value');
      for (const selector of ['a.tile', 'a.ui-card']) {
        await tab.keyboard.press('Shift');
        await tab.focus(selector);
        const focused = await tab.locator(selector).evaluate((link) => ({ visible: link.matches(':focus-visible'), shadow: getComputedStyle(link).boxShadow }));
        assert.ok(focused.visible, `${selector} takes focus by the keyboard`);
        assert.ok(focused.shadow.startsWith(ring), `${selector} shows the focus ring: its shadow is ${focused.shadow}, the ring ${ring}`);
        await tab.locator(selector).evaluate((link) => (link as HTMLElement).blur());
      }
    });

    await t.test('every link, button and field of the parts shows when it has the focus', async () => {
      await tab.setViewportSize({ width: 1280, height: 900 });
      await tab.keyboard.press('Shift');
      const found = await tab.locator('main a[href], main button:not([hidden]), main select, main input:not([type=hidden]), main summary, aside a[href], aside button').evaluateAll((elements) => {
        const mark = (element: Element): string => {
          const style = getComputedStyle(element);
          return [style.boxShadow, style.outlineStyle === 'none' ? '' : `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor}`, style.borderTopColor, style.backgroundColor, style.color].join('|');
        };
        const lost: string[] = [];
        for (const element of elements as HTMLElement[]) {
          const rect = element.getBoundingClientRect();
          if (!rect.width || !rect.height || getComputedStyle(element).visibility === 'hidden') continue;
          const frame = element.closest('.ui-search') ?? element;          // (a search field is bare: its frame shows the focus)
          const before = mark(element) + mark(frame);
          element.focus();
          const shown = element.matches(':focus-visible') && mark(element) + mark(frame) !== before;
          element.blur();
          if (!shown) lost.push(`${element.tagName.toLowerCase()}.${element.className} "${(element.textContent ?? '').trim().slice(0, 24)}"`);
        }
        return { count: elements.length, lost };
      });
      assert.ok(found.count > 20, `${found.count} focusable elements in the parts`);
      assert.deepEqual(found.lost, [], 'these do not look different when they have the focus');
    });

    await t.test('a phone\'s tab strip shows every tab and so the current one: /reports/?kind=smolt at 390 and 320 px, Norwegian tabs too', async () => {
      for (const width of [390, 320]) {
        await tab.setViewportSize({ width, height: 900 });
        for (const strip of ['#part-report-tabs nav', '#part-tabs nav']) {
          const state = await tab.locator(strip).evaluate((nav) => {
            const room = document.documentElement.clientWidth;
            const frame = nav.getBoundingClientRect();
            const tabs = [...nav.querySelectorAll('.ui-tab')].map((each) => each.getBoundingClientRect());
            const current = nav.querySelector('[aria-current="page"]')!.getBoundingClientRect();
            return { sideways: nav.scrollWidth - nav.clientWidth, hiddenBelow: nav.scrollHeight - nav.clientHeight,
              outside: tabs.filter((box) => box.left < -1 || box.right > room + 1 || box.top < frame.top - 1 || box.bottom > frame.bottom + 1).length,
              currentIn: current.left >= 0 && current.right <= room && current.top >= frame.top - 1 && current.bottom <= frame.bottom + 1, tabs: tabs.length };
          });
          assert.ok(state.tabs >= 6, `${strip}: ${state.tabs} tabs`);
          assert.equal(state.sideways, 0, `${strip} at ${width} px scrolls ${state.sideways} px sideways: its tabs lie out of sight`);
          assert.equal(state.hiddenBelow, 0, `${strip} at ${width} px hides something below`);
          assert.equal(state.outside, 0, `${strip} at ${width} px: ${state.outside} tabs outside the window`);
          assert.ok(state.currentIn, `${strip} at ${width} px: the current tab is on the screen`);
        }
      }
    });

    await t.test('a pH plot\'s text is 12-15.6 px on screen at every card width from 200 px; the Deffeyes chart\'s, from a 640 px figure up to 5200 px', async () => {
      await tab.setViewportSize({ width: 1280, height: 900 });
      const measure = (box: string, svg: string, texts: string, width: number): Promise<{ min: number; max: number }> => tab.evaluate(([boxId, svgSel, textSel, w]) => {
        (document.getElementById(boxId as string) as HTMLElement).style.width = `${w}px`;
        const chart = document.querySelector(svgSel as string) as SVGSVGElement;
        const scale = chart.getBoundingClientRect().width / chart.viewBox.baseVal.width;
        const sizes = [...chart.querySelectorAll(textSel as string)].map((text) => parseFloat(getComputedStyle(text).fontSize) * scale);
        return { min: Math.min(...sizes), max: Math.max(...sizes) };
      }, [box, svg, texts, width]);
      await tab.evaluate(() => { for (const id of ['ph-card', 'deffeyes-card']) (document.getElementById(id) as HTMLElement).style.margin = '0'; });
      // a card is a size container: its width is the chart's room (the card's own padding and border are in the 34 px)
      for (let width = 234; width <= 5200; width += width < 1400 ? 9 : 97) {
        const plot = await measure('chart-box', 'svg.ph-chart', '.ph-ticks text, .ph-axis, .ph-label', width);
        assert.ok(plot.min >= 11.9 && plot.max <= 15.7, `a pH plot in a ${width - 34} px card: text ${plot.min.toFixed(2)}-${plot.max.toFixed(2)} px`);
        if (width - 34 >= 640) {
          const deffeyes = await measure('chart-box', 'svg.deffeyes-chart', '.deffeyes-ticks text, .deffeyes-axis, .deffeyes-ph', width);
          assert.ok(deffeyes.min >= 11.9 && deffeyes.max <= 15.7, `the Deffeyes chart in a ${width - 34} px figure: text ${deffeyes.min.toFixed(2)}-${deffeyes.max.toFixed(2)} px`);
        }
      }
    });

    await t.test('a page\'s rule for one element of a pattern wins over the pattern: size, weight, link colour, icon alignment', async () => {
      await tab.setViewportSize({ width: 1280, height: 900 });
      const action = await resolved(tab, 'color', 'var(--action)');
      const chip = await resolved(tab, 'font-size', '.875rem');
      const state = await tab.evaluate(() => {
        const style = (selector: string) => getComputedStyle(document.querySelector(selector)!);
        const centre = (element: Element) => { const r = element.getBoundingClientRect(); return (r.top + r.bottom) / 2; };
        const search = document.querySelector('.units-search')!;
        return {
          chip: style('#part-overview .wq-status').fontSize,
          badgeColour: style('#part-meal a.badge-experimental').color, badgeLine: style('#part-meal a.badge-experimental').textDecorationLine,
          select: style('.monitor-filters select').fontWeight, input: style('.monitor-filters input').fontWeight,
          searchDisplay: getComputedStyle(search).display, searchIcon: centre(search.querySelector('.icon')!) - centre(search),
          searchInput: centre(search.querySelector('input')!) - centre(search),
        };
      });
      assert.equal(state.chip, chip, 'a water status chip is 14 px (components.css .wq-status), not the chip pattern\'s 13');
      assert.equal(state.badgeColour, action, 'a placement chip that is a link in a table\'s row head keeps the link colour');
      assert.equal(state.badgeLine, 'underline', 'and its underline');
      assert.equal(state.select, '400', 'a filter\'s select is not bold like its label');
      assert.equal(state.input, '400', 'a filter\'s search is not bold like its label');
      assert.notEqual(state.searchDisplay, 'contents', 'the search form is the frame of its icon and field');
      assert.ok(Math.abs(state.searchIcon) <= 1, `the search icon is ${state.searchIcon.toFixed(1)} px off the frame's middle`);
      assert.ok(Math.abs(state.searchInput) <= 1, `the search field is ${state.searchInput.toFixed(1)} px off the frame's middle`);
    });

    await t.test('the printed report: the Print button is not printed, its tables keep their small text, and it has the patterns\' rules at all', async () => {
      const printed = await browser.newPage({ reducedMotion: 'reduce' });
      try {
        await printed.setViewportSize({ width: 1280, height: 900 });
        await printed.goto(`${origin}/report`);
        const small = await resolved(printed, 'font-size', 'var(--fs-small)');
        const screen = await printed.evaluate(() => ({
          table: getComputedStyle(document.querySelector('.report-table')!).fontSize,
          button: getComputedStyle(document.querySelector('.report-print')!).backgroundColor,
          frame: getComputedStyle(document.querySelector('.table-wrap')!).borderTopWidth,
          cell: getComputedStyle(document.querySelector('.report-table td')!).paddingTop,
        }));
        assert.equal(screen.table, small, 'a report table\'s text is --fs-small, not the table pattern\'s body size');
        assert.notEqual(screen.button, 'rgba(0, 0, 0, 0)', 'the Print button is drawn as a button: the page loads the pattern sheet');
        assert.equal(screen.frame, '1px', 'a table frame is drawn');
        assert.notEqual(screen.cell, '0px', 'a table cell has its padding');
        await printed.emulateMedia({ media: 'print' });
        const print = await printed.evaluate(() => getComputedStyle(document.querySelector('.report-print')!).display);
        assert.equal(print, 'none', 'the Print button does not print');
      } finally {
        await printed.close();
      }
    });
  } finally {
    await browser.close();
    server.close();
  }
});
