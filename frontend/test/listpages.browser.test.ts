// Every list page the list-page island draws, with the props recorded from the test world (frontend/test/pages/
// list-props-<language>.json and panel-props-<language>.json, scripts/record_test_world.py), in a real browser
// (Playwright; skipped where there is no Chrome or Edge, never under CI=1): in en, nb and tr, at 1440 and at 390 wide,
// no CSP violation, no serious axe finding, no page-wide scroll, and no link of the list that opens the classic dialog.
// Test code only.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, serve, watchCsp } from './island-page.js';

const LANGUAGES = ['en', 'nb', 'tr'];
// the lists of Company and HR (list-props) and of the production panel (panel-props), one set of pages
const pages = (language: string): Record<string, unknown> => Object.assign({}, ...['list', 'panel'].map((set) =>
  JSON.parse(readFileSync(resolve(`frontend/test/pages/${set}-props-${language}.json`), 'utf8')) as Record<string, unknown>));

test('every list page in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  let asked = 'team';
  const server = await serve((theme, language) => islandPage('listpage', pages(language)[asked], theme, language, asked));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const name of Object.keys(pages('en'))) {
      for (const language of LANGUAGES) {
        for (const width of [1440, 390]) {
          await t.test(`${name} ${language} at ${width}`, async () => {
            asked = name;
            const tab = await browser.newPage({ viewport: { width, height: 900 } });
            const violations = await watchCsp(tab);
            await tab.goto(`${origin}/page/industry/${language}`);
            await tab.waitForSelector('[data-island="listpage"][data-mounted] :is(table, .ui-empty)');
            assert.deepEqual(violations, [], 'CSP violations');
            assert.deepEqual(await axe(tab, origin), [], 'axe');
            assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no page-wide scroll');
            assert.equal(await tab.locator('[data-modal]').count(), 0, 'no list link opens the classic dialog');
            await tab.close();
          });
        }
      }
    }
  } finally {
    await browser.close();
    server.close();
  }
});
