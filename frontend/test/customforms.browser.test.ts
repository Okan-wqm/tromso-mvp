// Every form with a template of its own that the record-form island draws (core/formpanels.py: a site's contacts, a
// feeder's calibrations, a device's channels, a credential's Replace the secret, a knowledge entry's review), with the props
// recorded from the test world (frontend/test/pages/form-props-<language>.json, scripts/record_test_world.py), in a real
// browser (Playwright; skipped where there is no Chrome or Edge, never under CI=1). It holds, in en, nb and tr, at 1440 and
// 390 wide: no CSP violation, no serious axe finding on every tab of the page, no page-wide scroll. And the parts that
// behave: a list saved apart is a form of its own after the record's (it posts its rows, its management form and the
// record's version, nothing of the record's form), a row added takes the focus and counts in TOTAL_FORMS, the record's
// Save is out of sight on a list's own tab, and ticking a second primary contact unticks the first. With SHOTS=<folder>
// it writes a screenshot of each page at 1440 and 390. Test code only.
import { mkdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { Page } from 'playwright-core';

import { BROWSERS, browser as launch, skipWithout } from './browsers.js';
import { axe, islandPage, serve, watchCsp } from './island-page.js';

const LANGUAGES = ['en', 'nb', 'tr'];
type Props = { panels: { key: string; label: string | null; tab: string | null }[]; form: { tabs: { key: string }[] } };
const pages = (language: string): Record<string, Props> =>
  JSON.parse(readFileSync(resolve(`frontend/test/pages/form-props-${language}.json`), 'utf8')) as Record<string, Props>;

/** Every tab of the page opened in turn, axe on each: a panel's content is only in sight on its own tab. */
async function everyTab(tab: Page, origin: string): Promise<string[]> {
  const found: string[] = [];
  const count = await tab.locator('[role="tab"]').count();
  for (let index = 0; index < Math.max(count, 1); index += 1) {
    if (count) await tab.click(`[role="tab"] >> nth=${index}`);
    found.push(...(await axe(tab, origin)).map((each) => `tab ${index}: ${JSON.stringify(each)}`));
  }
  return found;
}

test('every form with panels of its own in a browser', { skip: skipWithout(BROWSERS) }, async (t) => {
  let asked = '';
  const server = await serve((theme, language) => islandPage('recordform', pages(language)[asked], theme, language, asked));
  const address = server.address();
  const origin = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
  const browser = await launch();
  const open = async (name: string, width = 1440, language = 'en', theme = 'industry') => {
    asked = name;
    const tab = await browser.newPage({ viewport: { width, height: 900 } });
    const violations = await watchCsp(tab);
    await tab.goto(`${origin}/page/${theme}/${language}`);
    await tab.waitForSelector('[data-island="recordform"][data-mounted] form');
    return { tab, violations };
  };
  try {
    const names = Object.keys(pages('en'));
    assert.ok(names.length >= 20, `recorded: ${names.join(', ')}`);
    for (const name of names) {
      for (const language of LANGUAGES) {
        for (const width of [1440, 390]) {
          await t.test(`${name} ${language} at ${width}`, async () => {
            const { tab, violations } = await open(name, width, language);
            assert.deepEqual(violations, [], 'CSP violations');
            assert.deepEqual(await everyTab(tab, origin), [], 'axe');
            assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no page-wide scroll');
            if (process.env.SHOTS && language === 'en') {
              mkdirSync(process.env.SHOTS, { recursive: true });
              // the page on the tab its own template adds (a panel's own tab, or the record's tab a panel stands on)
              const shown = pages(language)[name]?.panels[0];
              const key = shown ? shown.tab ?? shown.key : null;
              if (await tab.locator('[role="tab"]').count()) {
                await tab.click(key && await tab.locator(`[role="tab"][data-key="${key}"]`).count()
                  ? `[role="tab"][data-key="${key}"]` : '[role="tab"] >> nth=0');
              }
              await tab.screenshot({ path: join(process.env.SHOTS, `${name.replace(/\W+/g, '-')}-${width}.png`), fullPage: true });
            }
            await tab.close();
          });
        }
      }
    }

    await t.test('a list saved apart: its own form, a row added, the record\'s Save out of sight on its tab', async () => {
      const name = names.find((each) => each.startsWith('EquipmentResource edit'));
      assert.ok(name, 'the feeder of the test world is recorded');
      const { tab } = await open(name);
      await tab.click('[role="tab"]:has-text("Feed calibration")');
      const rows = tab.locator('form:has(input[name="calibrations-TOTAL_FORMS"])');
      assert.equal(await rows.count(), 1, 'the list is one form');
      assert.equal(await tab.locator('form:has(input[name="calibrations-TOTAL_FORMS"]) input[name="name"]').count(), 0,
        'the record\'s fields are not in it');
      assert.equal(await tab.locator('form:has(input[name="name"])').isVisible(), false, 'the record\'s form is out of sight');
      await tab.click('button:has-text("Add calibration")');
      assert.equal(await tab.evaluate(() => document.activeElement?.getAttribute('name')), 'calibrations-1-feed_size_mm');
      const sent = await rows.evaluate((form) => [...new FormData(form as HTMLFormElement).keys()]);
      assert.equal(await rows.evaluate((form) => (form.querySelector('input[name="calibrations-TOTAL_FORMS"]') as HTMLInputElement).value), '2');
      assert.ok(sent.includes('version') && sent.includes('csrfmiddlewaretoken') && sent.includes('calibrations-0-id'), sent.join(' '));
      assert.ok(sent.every((key) => key.startsWith('calibrations-') || ['version', 'csrfmiddlewaretoken'].includes(key)), sent.join(' '));
      await tab.click('[role="tab"] >> nth=0');
      assert.equal(await tab.locator('form:has(input[name="name"])').isVisible(), true, 'back on a record tab, its form');
      await tab.close();
    });

    await t.test('contacts on the record\'s own tab, after its form: one primary at a time', async () => {
      const name = names.find((each) => each.startsWith('SiteResource edit'));
      assert.ok(name);
      const { tab } = await open(name);
      await tab.click('[role="tab"]:has-text("Contact")');
      const contacts = tab.locator('form:has(input[name="contacts-TOTAL_FORMS"])');
      assert.equal(await contacts.isVisible(), true, 'the contacts stand on the Contact tab');
      await tab.click('button:has-text("Add contact")');
      await tab.check('input[name="contacts-1-is_primary"]');
      assert.equal(await tab.isChecked('input[name="contacts-0-is_primary"]'), false, 'the first primary is unticked');
      await tab.click('[role="tab"] >> nth=0');
      assert.equal(await contacts.isVisible(), false, 'out of sight on another tab');
      await tab.close();
    });
  } finally {
    await browser.close();
    server.close();
  }
});
