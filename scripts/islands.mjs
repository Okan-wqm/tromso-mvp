// Builds the islands (vite.config.mjs) with the pinned Vite of package.json; nothing is served and nothing is fetched.
//   node scripts/islands.mjs                 frontend/islands/*.tsx into static/islands (npm run build:islands, part of
//                                            npm run build); with no island yet it writes an empty manifest, so the
//                                            server's check (core.W001) and the template tag read "no islands", not "no build"
//   node scripts/islands.mjs --gallery       the browser tests' component gallery, frontend/test/gallery/*.tsx into
//                                            .build/gallery (never shipped)
import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'vite';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const gallery = process.argv.includes('--gallery');
const source = join(ROOT, gallery ? 'frontend/test/gallery' : 'frontend/islands');
const target = join(ROOT, gallery ? '.build/gallery' : 'static/islands');

const islands = readdirSync(source).filter((name) => name.endsWith('.tsx') && !name.endsWith('.test.tsx'));
if (islands.length) {
  process.chdir(ROOT);
  await build({ configFile: join(ROOT, 'vite.config.mjs'), mode: gallery ? 'gallery' : 'production' });
} else {
  rmSync(target, { recursive: true, force: true });
  mkdirSync(join(target, '.vite'), { recursive: true });
  writeFileSync(join(target, '.vite', 'manifest.json'), '{}\n');
}
process.stdout.write(`islands: ${islands.length} built into ${target.slice(ROOT.length + 1).replaceAll('\\', '/')}\n`);
