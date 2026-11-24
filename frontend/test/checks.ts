// The checks every island page in a browser is held to (frontend/test/islands.browser.test.ts, the gallery;
// frontend/test/production.browser.test.ts, the Production and Sensors pages): the Content-Security-Policy violations a
// page raises, the text under 4.5:1 on what it stands on, and the critical or serious axe findings. Test code only.
import type { Page } from 'playwright-core';

import { policy } from './csp.js';

// The product's policy (config/settings.py, SECURE_CSP, read by frontend/test/csp.ts), without a nonce: a page of islands
// runs no inline script.
export const CSP = policy();
export async function watchCsp(tab: Page): Promise<string[]> {
  const violations: string[] = [];
  tab.on('console', (message) => { if (/Content.Security.Policy|Refused to/i.test(message.text())) violations.push(message.text()); });
  await tab.exposeFunction('__cspViolation', (text: string) => { violations.push(text); });
  await tab.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (event) => {
      (window as unknown as { __cspViolation: (text: string) => void }).__cspViolation(`${event.violatedDirective} ${event.blockedURI} ${event.sample}`);
    });
  });
  return violations;
}

// [selector of a text element, its text colour, the colour of the ground it stands on, contrast] for every low pair
export async function lowContrast(tab: Page): Promise<string[]> {
  return tab.evaluate(() => {
    const parse = (value: string): number[] => (value.match(/[\d.]+/g) ?? []).map(Number);
    const lum = ([r = 0, g = 0, b = 0]: number[]): number => {
      const c = [r, g, b].map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * (c[0] ?? 0) + 0.7152 * (c[1] ?? 0) + 0.0722 * (c[2] ?? 0);
    };
    const ground = (element: Element): number[] => {
      for (let at: Element | null = element; at; at = at.parentElement) {
        const value = parse(getComputedStyle(at).backgroundColor);
        if (value.length === 3 || (value[3] ?? 0) > 0.5) return value.slice(0, 3);
      }
      return parse(getComputedStyle(document.body).backgroundColor).slice(0, 3);
    };
    const low: string[] = [];
    const selector = '.ui-btn:not(:disabled):not([aria-disabled="true"]), .ui-btn[data-pending], .ui-chip > span, .ui-tile-label, .ui-tile-figure, .ui-tile-sub, .ui-tile-source, .ui-notice-body, .ui-plate-head h2, .ui-plate-meta, .ui-plate-link, .help, .errorlist li, .ui-table th, .ui-table td, .ui-tab, .ui-empty-text, .ui-chart-caption, .field label';
    for (const element of document.querySelectorAll(selector)) {
      if (!element.textContent?.trim()) continue;
      const fore = parse(getComputedStyle(element).color).slice(0, 3);
      const back = ground(element);
      const [high, lower] = [lum(fore), lum(back)].sort((a, b) => b - a);
      const ratio = ((high ?? 0) + 0.05) / ((lower ?? 0) + 0.05);
      if (ratio < 4.5) low.push(`${element.className || element.tagName} "${element.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
    }
    return low;
  });
}

/** The critical and serious axe findings of the page (axe-core served from `origin`/axe.js, as the policy allows); `within`:
 *  a selector, the part of the page held to it (a server page's own content, not the shell around it, whose own tests hold it). */
export async function axeFindings(tab: Page, origin: string, within?: string): Promise<string[]> {
  await tab.addScriptTag({ url: `${origin}/axe.js` });
  return tab.evaluate(async (selector) => {
    const axe = (window as unknown as { axe: { run: (context: unknown, options: unknown) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe;
    const result = await axe.run(selector ? document.querySelector(selector) : document, { resultTypes: ['violations'] });
    return result.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious').map((v) => `${v.id} (${v.nodes.length})`);
  }, within);
}
