// The record form island in a real browser (Playwright; skipped where there is no Chrome or Edge, never under CI=1), with a
// two-tab form whose second tab came back from the server with an error. It holds: the tab with the error is open and the
// first invalid field has the focus; the other tab's panel is in the page but hidden and out of the focus order; the
// fields of every tab are posted; a submit is busy (its button off and aria-busy) until the browser comes back to the
// page from its history (pageshow); no CSP violation and no serious axe finding in any theme. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, serve, watchCsp } from './island-page.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];
const field = (name: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
  name, label, help: null, required: true, disabled: false, fieldset: false, errors: [], initial: null,
  widget: { kind, name, value: '', attrs: { required: true }, ...extra }, ...('errors' in extra ? { errors: extra.errors } : {}),
});
const PROPS = {
  form: {
    action: '/save', multipart: false, errors: [], hidden: [{ name: 'version', value: 3, kind: 'hidden' }],
    tabs: [
      { key: 'general', label: 'General', help: null, hasErrors: false, fieldsets: [{ label: '', help: null, fields: [
        { ...field('title', 'Title', 'text'), widget: { kind: 'text', name: 'title', value: 'Clean the pond', attrs: { required: true, maxlength: 200 } } },
      ] }] },
      { key: 'where', label: 'Where', help: null, hasErrors: true, fieldsets: [{ label: '', help: null, fields: [
        { ...field('site', 'Site', 'select'), errors: ['Choose a site.'], widget: { kind: 'select', name: 'site', value: [''], attrs: { required: true },
          groups: [{ label: null, options: [{ value: '', label: '---------', selected: true, attrs: {} }, { value: '1', label: 'Bergen Hatchery', selected: false, attrs: {} }] }] } },
      ] }] },
    ],
  },
  csrfToken: 'test-token', submit: 'Create task', cancel: { href: '/tasks/', label: 'Cancel' }, optional: 'optional',
  tabsLabel: 'Task form sections', hasErrors: '(has errors)', delete: null, history: null,
};

test('the record form in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve((theme, language) => islandPage('recordform', PROPS, theme, language, 'New task'));

  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    await t.test('the tab with the error is open, the invalid field has the focus, the other tab is hidden and inert', async () => {
      const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-island="recordform"][data-mounted] form');
      assert.equal(await tab.getAttribute('[role="tab"][data-key="where"], [role="tab"]:nth-child(2)', 'aria-selected'), 'true');
      assert.equal(await tab.evaluate(() => document.activeElement?.getAttribute('name')), 'site');
      const hidden = await tab.evaluate(() => [...document.querySelectorAll('.ui-tab-panel')].map((panel) => [
        panel.hasAttribute('inert'), getComputedStyle(panel).display === 'none', Boolean(panel.querySelector('[name="title"]'))]));
      assert.deepEqual(hidden.find((each) => each[2]), [true, true, true], 'the General panel is in the page, inert and hidden');
      for (let press = 0; press < 12; press += 1) {
        await tab.keyboard.press('Tab');
        assert.notEqual(await tab.evaluate(() => document.activeElement?.getAttribute('name')), 'title', 'Tab never reaches a hidden tab');
      }
      const data = await tab.evaluate(() => [...new FormData(document.querySelector('form') as HTMLFormElement).keys()].sort());
      assert.deepEqual(data, ['csrfmiddlewaretoken', 'site', 'title', 'version'], 'every tab\'s fields are posted');
      await tab.close();
    });

    await t.test('a submit is busy until the page comes back from history', async () => {
      const tab = await browser.newPage();
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-mounted] form');
      await tab.selectOption('select[name="site"]', '1');
      // the browser's own sending is held (a listener on the form runs before React's at the root, which still sees the
      // submit), so the page stays to be looked at; what is sent is the first test's FormData
      await tab.evaluate(() => { document.querySelector('form')?.addEventListener('submit', (event) => event.preventDefault()); });
      await tab.click('button[type="submit"]');
      const state = () => tab.evaluate(() => {
        const button = document.querySelector('button[type="submit"]') as HTMLButtonElement;
        return [button.disabled, button.getAttribute('aria-busy')];
      });
      await tab.waitForFunction(() => (document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled, undefined, { polling: 50 });
      assert.deepEqual(await state(), [true, 'true']);
      await tab.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
      await tab.waitForFunction(() => !(document.querySelector('button[type="submit"]') as HTMLButtonElement).disabled, undefined, { polling: 50 });
      assert.deepEqual(await state(), [false, null]);
      await tab.close();
    });

    for (const theme of THEMES) {
      await t.test(`${theme}: no CSP violation, no serious axe finding`, async () => {
        const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        const violations = await watchCsp(tab);
        await tab.goto(`${origin}/page/${theme}/en`);
        await tab.waitForSelector('[data-mounted] form');
        await tab.click('[role="tab"] >> nth=0');
        assert.deepEqual(violations, [], 'CSP violations');
        assert.deepEqual(await axe(tab, origin), [], 'axe');
        assert.deepEqual(violations, [], 'CSP violations after axe');
        await tab.close();
      });
    }
  } finally {
    await browser.close();
    server.close();
  }
});
