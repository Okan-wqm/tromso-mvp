// The delete confirmation in a real browser (Playwright; skipped where there is no Chrome or Edge, never in CI). It holds
// (review F4): a plan with blockers keeps its Delete button off, whatever the busy form does; an open plan's button posts
// once and is busy until the page comes back from history; no CSP violation and no serious axe finding in any theme, at
// 1440 and at 390 wide, blocked and open. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, serve, watchCsp } from './island-page.js';
import { BLOCKED_PROPS, OPEN_PROPS } from './pages/delete-props.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];

test('the delete confirmation in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  // /page/<theme>/en is the blocked plan, /page/<theme>/nb the open one (the server's language is the test's switch)
  const server = await serve((theme, language) => islandPage('confirmdelete', language === 'nb' ? OPEN_PROPS : BLOCKED_PROPS, theme, 'en', 'Delete leave type'));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  const state = (tab: import('playwright-core').Page) => tab.evaluate(() => {
    const button = document.querySelector('button[type="submit"]') as HTMLButtonElement;
    return { disabled: button.disabled, busy: button.getAttribute('aria-busy') };
  });
  try {
    await t.test('a blocked plan keeps its Delete button off', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-island="confirmdelete"][data-mounted] form');
      assert.deepEqual(await state(tab), { disabled: true, busy: null });
      await tab.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
      assert.deepEqual(await state(tab), { disabled: true, busy: null }, 'still off after a return from history');
      await tab.close();
    });

    await t.test('an open plan posts once, busy until the page comes back from history', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry/nb`);
      await tab.waitForSelector('[data-island="confirmdelete"][data-mounted] form');
      assert.deepEqual(await state(tab), { disabled: false, busy: null });
      await tab.evaluate(() => { document.querySelector('form')?.addEventListener('submit', (event) => event.preventDefault()); });
      await tab.click('button[type="submit"]');
      await tab.waitForFunction(() => (document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled, undefined, { polling: 50 });
      assert.deepEqual(await state(tab), { disabled: true, busy: 'true' });
      await tab.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
      await tab.waitForFunction(() => !(document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled, undefined, { polling: 50 });
      assert.deepEqual(await state(tab), { disabled: false, busy: null });
      await tab.close();
    });

    for (const theme of THEMES) {
      for (const [width, which] of [[1440, 'en'], [390, 'nb']] as const) {
        await t.test(`${theme} at ${width} (${which === 'en' ? 'blocked' : 'open'}): no CSP violation, no serious axe finding`, async () => {
          const tab = await browser.newPage({ viewport: { width, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${theme}/${which}`);
          await tab.waitForSelector('[data-island="confirmdelete"][data-mounted] form');
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
