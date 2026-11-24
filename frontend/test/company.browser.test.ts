// Company › Overview's island in a real browser (Playwright on the machine's own Chrome or Edge; skipped where there is
// none, never under CI=1), mounted with props recorded from the demonstration company (frontend/test/pages/
// company-props-<language>.json, config/company_props.py's answer), on the product's style sheets and under the product's
// Content-Security-Policy (frontend/test/island-page.ts), in the new look, in every theme and every language. It holds: no
// CSP violation, no critical or serious axe finding, every text at 4.5:1, every block the props carry drawn, and no
// sideways scroll at 390 px. With SHOTS=<folder> it writes screenshots at 1440 and 390 px. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, lowContrast, serve, watchCsp } from './island-page.js';

const THEMES = ['industry', 'fjord', 'polarnatt', 'nordlys', 'tang', 'laks'];
const LANGUAGES = ['en', 'nb', 'tr'];
const TEXTS = '.ui-chip > span, .ui-tile-label, .ui-tile-figure, .ui-tile-sub, .ui-tile-source, .ui-notice-body, .ui-plate-head h2, '
  + '.ui-plate-meta, .ui-plate-link, .ui-table th, .ui-table td, .ui-list-main, .ui-list-meta, .ui-cell-sub, .ui-audit-record, '
  + '.ui-audit-who, .ui-empty-title';

function props(language: string): unknown {
  return JSON.parse(readFileSync(resolve(`frontend/test/pages/company-props-${language}.json`), 'utf8'));
}

test('Company › Overview\'s island in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  const server = await serve((theme, language) => islandPage('company', props(language), theme, language, 'Overview'));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  try {
    for (const theme of THEMES) {
      for (const language of LANGUAGES) {
        await t.test(`${theme}, ${language}: every block drawn, no CSP violation, no serious axe finding, text at 4.5:1`, async () => {
          const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
          const violations = await watchCsp(tab);
          await tab.goto(`${origin}/page/${theme}/${language}`);
          await tab.waitForSelector('[data-island="company"][data-mounted] .ui-plate');
          const given = props(language) as Record<string, { title?: string } | null>;
          const titles = await tab.locator('.ui-plate-head h2').allTextContents();
          for (const [key, block] of Object.entries(given)) {
            if (block && block.title) assert.ok(titles.includes(block.title), `${key}: "${block.title}" drawn`);
          }
          assert.deepEqual(violations, [], 'CSP violations');
          assert.deepEqual(await lowContrast(tab, TEXTS), [], 'text under 4.5:1');
          assert.deepEqual(await axe(tab, origin), [], 'axe');
          assert.deepEqual(violations, [], 'CSP violations after axe');
          await tab.close();
        });
      }
    }
    for (const width of [1440, 390]) {
      await t.test(`${width} px: nothing scrolls sideways${process.env.SHOTS ? ', screenshot written' : ''}`, async () => {
        const tab = await browser.newPage({ viewport: { width, height: 900 } });
        await tab.goto(`${origin}/page/industry/en`);
        await tab.waitForSelector('[data-mounted] .ui-plate');
        assert.equal(await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
        if (process.env.SHOTS) {
          mkdirSync(process.env.SHOTS, { recursive: true });
          await tab.screenshot({ path: join(process.env.SHOTS, `company-island-${width}.png`), fullPage: true });
        }
        await tab.close();
      });
    }
  } finally {
    await browser.close();
    server.close();
  }
});
