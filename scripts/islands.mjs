// Builds the islands (vite.config.mjs) with the pinned Vite of package.json; nothing is served and nothing is fetched.
//   node scripts/islands.mjs                 frontend/islands/*.tsx into static/islands (npm run build:islands, part of
//                                            npm run build); with no island yet it writes an empty manifest, so the
//                                            server's check (core.W001) and the template tag read "no islands", not "no build"
//   node scripts/islands.mjs --gallery       the browser tests' component gallery, frontend/test/gallery/*.tsx into
//                                            .build/gallery (never shipped)
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'vite';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** The licence texts of every package the islands may ship (package-lock.json, not dev), served beside the bundles as
 *  static/islands/THIRD_PARTY_NOTICES.txt: MIT and Apache-2.0 ask for their notice to travel with the code. */
export function notices(root = ROOT) {
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  const parts = ['Third-party software in the browser bundles of static/islands (THIRD_PARTY.md lists it; scripts/islands.mjs',
    'writes this file from package-lock.json at every build). Each package with its licence text.', ''];
  for (const [path, entry] of Object.entries(lock.packages ?? {}).sort(([a], [b]) => a.localeCompare(b))) {
    if (!path.startsWith('node_modules/') || entry.dev) continue;
    const folder = join(root, path);
    if (!existsSync(folder)) continue;
    const manifest = JSON.parse(readFileSync(join(folder, 'package.json'), 'utf8'));
    const file = readdirSync(folder).find((name) => /^(licen[cs]e|copying|notice)(\.|$)/i.test(name));
    parts.push('='.repeat(100), `${manifest.name} ${manifest.version} (${manifest.license ?? 'see below'})`, '='.repeat(100),
      file ? readFileSync(join(folder, file), 'utf8').trim() : `No licence file in the package; its package.json says ${manifest.license}.`, '');
  }
  return `${parts.join('\n')}\n`;
}
const gallery = process.argv.includes('--gallery');
const source = join(ROOT, gallery ? 'frontend/test/gallery' : 'frontend/islands');
const target = join(ROOT, gallery ? '.build/gallery' : 'static/islands');

const islands = readdirSync(source).filter((name) => name.endsWith('.tsx') && !name.endsWith('.test.tsx'));
if (islands.length) {
  process.chdir(ROOT);
  await build({ configFile: join(ROOT, 'vite.config.mjs'), mode: gallery ? 'gallery' : 'production' });
} else {
  rmSync(target, { recursive: true, force: true });
  mkdirSync(target, { recursive: true });
  writeFileSync(join(target, 'manifest.json'), '{}\n');
}
if (!gallery) writeFileSync(join(target, 'THIRD_PARTY_NOTICES.txt'), notices());
process.stdout.write(`islands: ${islands.length} built into ${target.slice(ROOT.length + 1).replaceAll('\\', '/')}\n`);
