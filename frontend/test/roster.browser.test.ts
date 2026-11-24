// The roster grid in a real browser (Playwright; skipped where there is no Chrome or Edge, never under CI=1). It holds: the
// arrow keys move between the cells' controls (skipping a day with none), Home and End to the row's ends; the whole paint
// works by keyboard alone (choose a shift in the paint bar, select cells with Space and Enter, Apply) and posts the choice
// and the selected cells with the CSRF token; choosing the same paint again empties the selection; no CSP violation and
// no serious axe finding in any theme, at 1440 and at 390 wide, and the page never wider than the screen. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, serve, watchCsp } from './island-page.js';
import { ROSTER_PROPS } from './pages/roster-props.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];

test('the roster grid in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve((theme, language) => islandPage('rostergrid', ROSTER_PROPS, theme, language, 'Shift schedule'));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  const focused = (tab: import('playwright-core').Page) => tab.evaluate(() => {
    const here = document.activeElement as HTMLElement | null;
    return here?.getAttribute('href') ?? here?.getAttribute('aria-label') ?? here?.textContent ?? '';
  });
  try {
    await t.test('the arrow keys move between the cells, Home and End to the row ends', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-island="rostergrid"][data-mounted] table');
      await tab.focus('a[href="/hr/schedule/7/"]');
      await tab.keyboard.press('ArrowRight');
      assert.equal(await focused(tab), '/hr/schedule/new/?employee=1&day=2026-11-24');
      await tab.keyboard.press('ArrowDown');
      assert.equal(await focused(tab), '/hr/schedule/9/');
      await tab.keyboard.press('ArrowLeft');                 // the day the viewer does not reach has no control: stays
      assert.equal(await focused(tab), '/hr/schedule/9/');
      await tab.keyboard.press('ArrowUp');
      await tab.keyboard.press('End');
      assert.equal(await focused(tab), '/hr/schedule/8/');
      await tab.keyboard.press('Home');
      assert.equal(await focused(tab), '/hr/schedule/7/');
      await tab.close();
    });

    await t.test('paint by keyboard alone: choose, select with Space and Enter, Apply posts the choice and the cells', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-island="rostergrid"][data-mounted] table');
      assert.equal(await tab.isDisabled('button[type="submit"]'), true, 'nothing to apply yet');
      await tab.focus('button.ui-roster-choice:has-text("TD")');
      await tab.keyboard.press('Enter');
      assert.equal(await tab.getAttribute('button.ui-roster-choice:has-text("TD")', 'aria-pressed'), 'true');
      await tab.focus('button.ui-roster-pick[aria-label="Test Person, Mon 23 Nov: TD"]');
      await tab.keyboard.press('Space');
      await tab.keyboard.press('ArrowDown');                 // (Test Second's Monday has no control) next: none; stays
      await tab.keyboard.press('ArrowRight');
      assert.equal(await focused(tab), 'Test Person, Tue 24 Nov');
      await tab.keyboard.press('Enter');
      assert.equal(await tab.getAttribute('button[aria-label="Test Person, Mon 23 Nov: TD"]', 'aria-pressed'), 'true');
      assert.equal(await tab.getAttribute('button[aria-label="Test Person, Tue 24 Nov"]', 'aria-pressed'), 'true');
      await tab.evaluate(() => { document.querySelector('form')?.addEventListener('submit', (event) => event.preventDefault()); });
      await tab.focus('button[type="submit"]');
      await tab.keyboard.press('Enter');
      const sent = await tab.evaluate(() => [...new FormData(document.querySelector('form') as HTMLFormElement).entries()].map(([k, v]) => [k, String(v)]));
      assert.deepEqual(sent, [['csrfmiddlewaretoken', 'test-token'], ['next', '/hr/schedule/?week=2026-11-23'], ['shift', '5'],
        ['cells', '1:2026-11-23'], ['cells', '1:2026-11-24']]);
      await tab.click('button.ui-roster-choice:has-text("TD")');           // the same paint again: nothing chosen, nothing selected
      assert.equal(await tab.locator('[aria-pressed="true"]').count(), 0);
      assert.equal(await tab.locator('button.ui-roster-pick').count(), 0, 'the cells are links again');
      await tab.close();
    });

    for (const theme of THEMES) {
      for (const width of [1440, 390]) {
        await t.test(`${theme} at ${width}: no CSP violation, no serious axe finding, no page-wide scroll`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${theme}/en`);
          await tab.waitForSelector('[data-island="rostergrid"][data-mounted] table');
          await tab.click('button.ui-roster-choice:has-text("Off")');       // the paint's own state, checked too
          await tab.click('button.ui-roster-pick >> nth=0');
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await axe(tab, origin), [], 'axe');
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
