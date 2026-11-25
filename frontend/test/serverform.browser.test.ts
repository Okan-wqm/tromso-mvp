// A server form in a real browser (Playwright; skipped where there is no Chrome or Edge, never under CI): the button
// pressed reaches the server with its name and value, though the busy state switches every submit button off (review of
// the custom forms, B1: a switched-off button is not sent, and Randomise and Add factor posted nothing); a button without
// a name sends no extra field; back from the browser's history the copy is gone, so the next press sends only its own
// (B2). The request body is read through Playwright's routing, the server never reached. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { islandPage, serve, watchCsp } from './island-page.js';

const PROPS = { buttons: [{ name: 'action', value: 'randomise', label: 'Randomise' }, { name: '_draft', value: 'add_factor', label: 'Add factor' }] };

/** The bodies of the form's posts, each answered without reaching a server. */
async function posts(tab: Page): Promise<string[]> {
  const sent: string[] = [];
  await tab.route('**/sent', async (route) => {
    sent.push(route.request().postData() ?? '');
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>sent</title>sent' });
  });
  return sent;
}

test('a server form in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve((theme, language) => islandPage('serverform', PROPS, theme, language, 'Places'));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const [label, expected] of [['Randomise', 'action=randomise'], ['Add factor', '_draft=add_factor']] as const) {
      await t.test(`${label} posts ${expected}`, async () => {
        const tab = await browser.newPage();
        const violations = await watchCsp(tab);
        const sent = await posts(tab);
        await tab.goto(`${origin}/page/industry/en`);
        await tab.waitForSelector('[data-island="serverform"][data-mounted] form');
        await tab.click(`button:has-text("${label}")`);
        await tab.waitForFunction(() => document.title === 'sent');
        assert.equal(sent.length, 1);
        const fields = new URLSearchParams(sent[0]);
        assert.equal(`${expected.split('=')[0]}=${fields.get(expected.split('=')[0])}`, expected);
        assert.equal(fields.get('note'), 'Test note');
        assert.equal(fields.getAll(expected.split('=')[0]).length, 1, 'said once');
        assert.deepEqual(violations, []);
        await tab.close();
      });
    }

    await t.test('a button without a name adds nothing; a return from history takes the copy away', async () => {
      const tab = await browser.newPage();
      await tab.goto(`${origin}/page/industry/en`);
      await tab.waitForSelector('[data-island="serverform"][data-mounted] form');
      // the browser's own sending is held so the page stays: what it would send is read from the form
      await tab.evaluate(() => { document.querySelector('form')?.addEventListener('submit', (event) => event.preventDefault()); });
      await tab.click('button:has-text("Randomise")');
      assert.equal(await tab.locator('input[type="hidden"][name="action"]').count(), 1);
      await tab.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
      await tab.waitForFunction(() => !document.querySelector('input[name="action"][data-sent]'));
      await tab.click('button:has-text("Save")');
      const keys = await tab.evaluate(() => [...new FormData(document.querySelector('form') as HTMLFormElement).keys()].sort());
      assert.deepEqual(keys, ['csrfmiddlewaretoken', 'note']);
      await tab.close();
    });
  } finally {
    await browser.close();
    server.close();
  }
});
