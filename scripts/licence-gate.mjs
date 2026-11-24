// The npm licence gate (frontend redesign, decision 8; THIRD_PARTY.md): every package npm installs from package-lock.json,
// for the browser or for the build, has a licence on the allow-list, or is a reviewed exception named here with why.
// It reads the installed package.json of each (the lockfile carries no licence). Anything else fails until it is reviewed:
// AGPL, SSPL, BUSL, a non-commercial licence, an unknown one, a missing one.
//   node scripts/licence-gate.mjs           (npm run check:licences; CI and npm test run it)
//   node scripts/licence-gate.mjs --list    every package with its licence
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export const ALLOWED = new Set(['MIT', 'Apache-2.0', 'ISC', 'BSD-2-Clause', 'BSD-3-Clause', '0BSD']);

// Reviewed exceptions: [package, licence as it says it, why it may be used]. A new version that changes the licence fails.
export const REVIEWED = [
  ['axe-core', 'MPL-2.0', 'test only: the accessibility rules of the browser tests, unmodified, never shipped'],
  ['lightningcss', 'MPL-2.0', 'build only: the CSS transformer inside Tailwind and Vite, used unmodified, never shipped'],
  ['lightningcss-*', 'MPL-2.0', 'build only: the prebuilt lightningcss binary of one platform (npm installs the one of the machine)'],
  ['graceful-fs', 'BlueOak-1.0.0', 'build only (Tailwind): a permissive licence (Blue Oak Model License), never shipped'],
];

/** The SPDX expression is allowed when one side of an OR is allowed, or every side of an AND. */
export function allowed(expression) {
  const text = expression.trim().replace(/^\((.*)\)$/, '$1');
  if (/\sOR\s/i.test(text)) return text.split(/\s+OR\s+/i).some(allowed);
  if (/\sAND\s/i.test(text)) return text.split(/\s+AND\s+/i).every(allowed);
  return ALLOWED.has(text);
}

export function licenceOf(manifest) {
  if (typeof manifest.license === 'string') return manifest.license;
  if (manifest.license && typeof manifest.license.type === 'string') return manifest.license.type;
  if (Array.isArray(manifest.licenses)) return manifest.licenses.map((entry) => entry.type ?? entry).join(' OR ');
  return '';
}

export function gate(root = ROOT) {
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  const found = [];
  const problems = [];
  for (const [path, entry] of Object.entries(lock.packages ?? {})) {
    if (!path.startsWith('node_modules/')) continue;
    const name = path.slice(path.lastIndexOf('node_modules/') + 'node_modules/'.length);
    const file = join(root, path, 'package.json');
    if (!existsSync(file)) {
      if (!entry.optional) problems.push(`${name}: not installed (run npm ci)`);
      continue;                    // another platform's prebuilt binary: npm did not install it here
    }
    const licence = licenceOf(JSON.parse(readFileSync(file, 'utf8')));
    found.push([name, licence]);
    const reviewed = REVIEWED.find(([pkg]) => (pkg.endsWith('*') ? name.startsWith(pkg.slice(0, -1)) : pkg === name));
    if (allowed(licence || '-')) continue;
    if (reviewed && reviewed[1] === licence) continue;
    problems.push(`${name}: ${licence || 'no licence'}${reviewed ? ` (reviewed as ${reviewed[1]})` : ''}`);
  }
  return { found, problems };
}

if (resolve(process.argv[1] ?? '') === fileURLToPath(import.meta.url)) {
  const { found, problems } = gate();
  if (process.argv.includes('--list')) for (const [name, licence] of found) process.stdout.write(`${name}\t${licence}\n`);
  if (problems.length) {
    process.stderr.write(`${problems.map((line) => `  ${line}`).join('\n')}\n${problems.length} package(s) with a licence not allowed `
      + '(scripts/licence-gate.mjs: review it, then add it to REVIEWED and THIRD_PARTY.md)\n');
    process.exit(1);
  }
  process.stdout.write(`licence gate: ${found.length} packages, every licence allowed or reviewed\n`);
}
