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

    // What the browser itself posts (review B1, B3): every POST of the page is caught (Playwright routing, no server).
    const caught = async (tab: Page) => {
      const sent: { url: string; body: URLSearchParams }[] = [];
      await tab.route('**/*', async (route) => {
        if (route.request().method() !== 'POST') return route.continue();
        sent.push({ url: new URL(route.request().url()).pathname, body: new URLSearchParams(route.request().postData() ?? '') });
        return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>sent</title>sent' });
      });
      return sent;
    };
    const press = async (tab: Page, panel: string | null, button: string) => {
      if (panel) await tab.click(`[role="tab"][data-key="${panel}"]`);
      await tab.locator(`button[type="submit"]:visible:has-text("${button}")`).first().click();
      await tab.waitForFunction(() => document.title === 'sent');
    };

    for (const [label, expected] of [['Randomise', ['action', 'randomise']], ['Save places', ['action', 'save']],
      ['Add factor', ['_draft', 'add_factor']]] as const) {
      await t.test(`the experiment's ${label} posts ${expected.join('=')} from a real browser`, async () => {
        const name = names.find((each) => each.startsWith('ExperimentResource edit'));
        assert.ok(name);
        const { tab } = await open(name);
        const sent = await caught(tab);
        await press(tab, label === 'Add factor' ? 'design' : 'places', label);
        assert.equal(sent.length, 1);
        assert.deepEqual(sent[0]?.body.getAll(expected[0]), [expected[1]]);
        assert.ok(sent[0]?.body.get('version'), 'the record\'s version goes with it');
        await tab.close();
      });
    }

    await t.test('a list saved apart, the record\'s form and a one-button form each post their own fields', async () => {
      const name = names.find((each) => each.startsWith('SiteResource edit'));
      assert.ok(name);
      const { tab } = await open(name);
      const sent = await caught(tab);
      await press(tab, 'contact', 'Save contacts');
      const rows = sent.at(-1);
      assert.match(rows?.url ?? '', /contacts\/$/);
      assert.equal(rows?.body.get('contacts-TOTAL_FORMS'), '1');
      assert.ok(rows?.body.get('contacts-0-name') && rows.body.get('version') && rows.body.get('csrfmiddlewaretoken'));
      assert.equal(rows?.body.get('name'), null, 'nothing of the record\'s form');
      await tab.close();
      const entry = names.find((each) => each.startsWith('KnowledgeEntryResource edit'));
      assert.ok(entry);
      const review = await open(entry);
      const posted = await caught(review.tab);
      await press(review.tab, 'review', 'Mark as reviewed');
      assert.equal(posted.at(-1)?.body.get('status'), 'reviewed');
      assert.ok(posted.at(-1)?.body.get('version'));
      await review.tab.close();
    });

    await t.test('a draft refresh of a form of its own posts its marker once; back from history the marker is gone', async () => {
      const name = names.find((each) => each.startsWith('FeedingProtocolResource edit'));
      assert.ok(name);
      const { tab } = await open(name);
      const sent = await caught(tab);
      await tab.click('[role="tab"][data-key="table"]');
      await tab.fill('input[name="temperatures"]', '8 12 16');
      await tab.locator('input[name="temperatures"]').dispatchEvent('change');
      await tab.waitForFunction(() => document.title === 'sent');
      assert.deepEqual(sent.at(-1)?.body.getAll('_draft'), ['temperatures']);
      await tab.close();
      // the same, the browser's sending held, so the page stays as a return from history finds it
      const again = await open(name);
      await again.tab.evaluate(() => document.querySelectorAll('form').forEach((form) => form.addEventListener('submit', (event) => event.preventDefault())));
      await again.tab.click('[role="tab"][data-key="table"]');
      await again.tab.fill('input[name="temperatures"]', '8 12 16');
      await again.tab.locator('input[name="temperatures"]').dispatchEvent('change');
      assert.equal(await again.tab.locator('input[name="_draft"]').count(), 1);
      await again.tab.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
      await again.tab.waitForFunction(() => !document.querySelector('input[name="_draft"]'));
      await again.tab.close();
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
