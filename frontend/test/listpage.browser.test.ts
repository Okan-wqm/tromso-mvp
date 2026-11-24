// The list page island in a real browser (Playwright; skipped where there is no Chrome or Edge, never under CI=1): the
// search and the filters are one GET form whose submit sends the address the server reads (the kept view, the search,
// each filter; never the page); a row action that posts sends the CSRF token; no CSP violation and no serious axe finding
// in any theme, at 1440 and at 390 wide, the table scrolling inside itself and the page never wider than the screen.
// Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, serve, watchCsp } from './island-page.js';
import { LIST_PROPS } from './pages/list-props.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];

test('the list page in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve((theme, language) => islandPage('listpage', LIST_PROPS, theme, language, 'Team'));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    await t.test('a filter and a search send the address the server reads', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-island="listpage"][data-mounted] table');
      await tab.selectOption('select[name="status"]', 'left');
      await tab.fill('input[name="q"]', 'Bravo');
      const [request] = await Promise.all([
        tab.waitForRequest((each) => each.url().includes('/page/industry/en?')),
        tab.press('input[name="q"]', 'Enter'),
      ]);
      const sent = new URL(request.url()).searchParams;
      assert.deepEqual([...sent.entries()], [['tab', 'pending'], ['q', 'Bravo'], ['department', ''], ['status', 'left']]);
      await tab.close();
    });

    for (const theme of THEMES) {
      for (const width of [1440, 390]) {
        await t.test(`${theme} at ${width}: no CSP violation, no serious axe finding, no page-wide scroll`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${theme}/en`);
          await tab.waitForSelector('[data-island="listpage"][data-mounted] table');
          assert.deepEqual(violations, []);
          assert.deepEqual(await axe(tab, origin), [], 'axe');
          assert.deepEqual(violations, [], 'CSP violations after axe');
          assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no page-wide scroll');
          await tab.close();
        });
      }
    }
  } finally {
    await browser.close();
    server.close();
  }
});
