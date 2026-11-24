// The machine's own Chrome or Edge for the browser tests (Playwright drives it; nothing is downloaded), and the one rule
// for when such a test is skipped: where there is no browser, saying so, but never in CI (CI=1, or CI=true as GitHub
// Actions sets it: any value but "0" and "false"), where a missing browser is a failure (F-127: a CI that skipped them
// would pass without ever running the wall's or the designer's checks).
// Test code only.
import { existsSync } from 'node:fs';

import { chromium, type Browser } from 'playwright-core';

export const BROWSERS = [
  process.env.CHROME_PATH ?? '',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter((path) => path && existsSync(path));

/** Whether this is a CI run: CI set to anything but "", "0" or "false" (GitHub Actions sets CI=true, others CI=1). */
export function inCi(env: Record<string, string | undefined> = process.env): boolean {
  const value = (env.CI ?? '').trim().toLowerCase();
  return value !== '' && value !== '0' && value !== 'false';
}

/** The `skip` of a browser test: false (run it) when there is a browser or in CI, else why it is skipped. */
export function skipWithout(found: string[], env: Record<string, string | undefined> = process.env): string | false {
  return found.length || inCi(env) ? false : 'no Chrome or Edge on this machine';
}

/** The first browser found, headless; under CI=1 without one, a failure that says what is missing. */
export async function browser(): Promise<Browser> {
  if (!BROWSERS.length) {
    throw new Error('CI needs Chrome or Edge for the browser tests: set CHROME_PATH or install one.');
  }
  return chromium.launch({ executablePath: BROWSERS[0], headless: true });
}
