// Builds the design system's tokens.css from its tokens.json (docs/design/system), and the stylesheet the pages load,
// static/css/tokens.css: the design system's file unchanged with the app's own block after it (core.tests_design_shell,
// TokenSourceTests). tokens.json is the one source: a token is changed there, never in either CSS file.
//   node scripts/tokens.mjs          write both files (npm run build:tokens, part of npm run build)
//   node scripts/tokens.mjs --check  fail when either file is not what tokens.json builds now (npm run check:tokens;
//                                    CI runs it, and npm test runs it too)
// The layout of the file: the default theme's block (`:root, [data-theme="fjord"]`), then one block per other theme with
// every colour and shadow token (a constant repeats its value) and the per-theme gradients, then one `:root` block of the
// theme-independent tokens: type sizes, spacing, radius, sizes, layers, the other gradients and the two families.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = join(ROOT, 'docs', 'design', 'system', 'tokens.json');
const SYSTEM = join(ROOT, 'docs', 'design', 'system', 'tokens.css');
const SERVED = join(ROOT, 'static', 'css', 'tokens.css');
const APP_MARK = '/* App additions (not in tokens.json yet)';

const normal = (text) => text.replace(/\r\n/g, '\n');

export function build(json) {
  const themes = json.color.themes.map((theme) => theme.id);
  const perTheme = (token) => typeof token.value === 'object';
  const valueIn = (token, theme) => (perTheme(token) ? token.value[theme] : token.value);
  const lines = [`/* ${json.name} — generated from tokens.json by scripts/tokens.mjs. Themes via <html data-theme>: `
    + `${themes.map((id, i) => (i ? id : `${id} (default)`)).join(', ')}. */`];
  const themed = [...json.color.tokens, ...json.shadow.tokens, ...json.gradient.tokens.filter(perTheme)];
  for (const [index, theme] of themes.entries()) {
    lines.push(index === 0 ? `:root, [data-theme="${theme}"] {` : `[data-theme="${theme}"] {`);
    for (const token of themed) {
      const value = valueIn(token, theme);
      if (value === undefined) throw new Error(`tokens.json: ${token.name} has no value for the theme ${theme}`);
      lines.push(`  --${token.name}: ${value};`);
    }
    lines.push('}');
  }
  lines.push(':root {');
  for (const group of json.type.groups) {
    for (const style of group.styles) lines.push(`  --fs-${style.name}: ${style.fontSize};`);
  }
  for (const key of ['spacing', 'radius', 'size', 'zIndex']) {
    for (const token of json[key].tokens) lines.push(`  --${token.name}: ${token.value};`);
  }
  for (const token of json.gradient.tokens.filter((token) => !perTheme(token))) lines.push(`  --${token.name}: ${token.value};`);
  for (const [name, value] of Object.entries(json.type.families)) lines.push(`  --font-${name}: ${value};`);
  lines.push('}');
  return `${lines.join('\n')}\n`;
}

function appBlock(served) {
  const at = served.indexOf(APP_MARK);
  if (at < 0) throw new Error(`static/css/tokens.css has no app block (${APP_MARK} …)`);
  return served.slice(at);
}

const json = JSON.parse(readFileSync(SOURCE, 'utf8'));
const system = build(json);
const served = `${system}\n${appBlock(normal(readFileSync(SERVED, 'utf8')))}`;

if (process.argv.includes('--check')) {
  const stale = [[SYSTEM, system], [SERVED, served]].filter(([file, text]) => normal(readFileSync(file, 'utf8')) !== text);
  if (stale.length) {
    process.stderr.write(`${stale.map(([file]) => file.slice(ROOT.length + 1)).join(' and ')} not what tokens.json builds: `
      + 'run `npm run build:tokens` and commit the result.\n');
    process.exit(1);
  }
  process.stdout.write('tokens.css is what tokens.json builds.\n');
} else {
  writeFileSync(SYSTEM, system);
  writeFileSync(SERVED, served);
}
