// Builds static/css/tw.css from frontend/tailwind.css and the class names of the templates (docs/design/system/tailwind.md),
// with the pinned Tailwind CLI of package.json; nothing is fetched and nothing runs in the browser.
//   node scripts/tailwind.mjs          write static/css/tw.css (npm run build:css, part of npm run build)
//   node scripts/tailwind.mjs --check  fail when static/css/tw.css is not what the source and the templates build now
//                                      (npm run check:css; CI runs it before the build, and npm test runs it too)
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = join(ROOT, 'frontend', 'tailwind.css');
const OUTPUT = join(ROOT, 'static', 'css', 'tw.css');

function cli() {
  const require = createRequire(join(ROOT, 'package.json'));
  const manifest = require.resolve('@tailwindcss/cli/package.json');
  const { bin } = JSON.parse(readFileSync(manifest, 'utf8'));
  return join(dirname(manifest), typeof bin === 'string' ? bin : bin.tailwindcss);
}

function build(target) {
  const run = spawnSync(process.execPath, [cli(), '--input', SOURCE, '--output', target], { cwd: ROOT, encoding: 'utf8' });
  if (run.status !== 0) {
    process.stderr.write(run.stderr || run.stdout || 'tailwindcss failed\n');
    process.exit(run.status ?? 1);
  }
}

const normal = (text) => text.replace(/\r\n/g, '\n');

if (process.argv.includes('--check')) {
  const folder = mkdtempSync(join(tmpdir(), 'tw-'));
  try {
    const fresh = join(folder, 'tw.css');
    build(fresh);
    if (!existsSync(OUTPUT) || normal(readFileSync(OUTPUT, 'utf8')) !== normal(readFileSync(fresh, 'utf8'))) {
      process.stderr.write('static/css/tw.css is out of date: run `npm run build:css` and commit the result.\n');
      process.exit(1);
    }
    process.stdout.write('static/css/tw.css is up to date.\n');
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
} else {
  build(OUTPUT);
}
