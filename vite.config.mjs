// The islands' build (README, Frontend: islands; F:\dev\balik-notes\live-arch\PLAN-SPEED-FRONTEND.md, B4): every
// frontend/islands/<name>.tsx is one island, a React root a Django page mounts with `{% island "<name>" props %}`
// (core/templatetags/assets.py), built by `vite build` (scripts/islands.mjs: npm run build:islands, part of npm run build)
// into static/islands/.
//   - Production build only: there is no dev server and no hot reload (a dev server's injected scripts and styles break
//     the Content-Security-Policy, script-src and style-src 'self'). Nothing is ever served by Vite.
//   - Hashed file names, so a browser never keeps a stale copy; the manifest (static/islands/.vite/manifest.json) maps an
//     island to its file and the chunks it imports, and the template tag reads it.
//   - No source maps (core/test_no_chemistry_in_browser.py refuses them) and no inlined assets (no data: URL): every
//     asset is a file of its own.
//   - No module-preload polyfill: it is an inline script. The tag writes <link rel="modulepreload"> itself.
//   - JSX by Vite's own transformer (oxc), React's automatic runtime; no Babel, no CSS-in-JS. The islands draw with the
//     design system's classes (static/css/ds.css), so they import no stylesheet of their own.
// `--mode gallery` builds the component gallery of the browser tests instead (frontend/test/gallery/*.tsx into
// .build/gallery): the same pipeline, never shipped.
import { readdirSync } from 'node:fs';
import { defineConfig } from 'vite';

const entries = (folder) => Object.fromEntries(readdirSync(folder)
  .filter((name) => name.endsWith('.tsx') && !name.endsWith('.test.tsx'))
  .map((name) => [name.slice(0, -'.tsx'.length), `${folder}/${name}`]));

export default defineConfig(({ mode }) => ({
  root: '.',
  base: './',
  publicDir: false,
  clearScreen: false,
  logLevel: 'warn',
  oxc: { jsx: { runtime: 'automatic' } },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: mode === 'gallery' ? '.build/gallery' : 'static/islands',
    emptyOutDir: true,
    manifest: true,
    sourcemap: false,
    assetsInlineLimit: 0,
    cssCodeSplit: true,
    modulePreload: { polyfill: false },
    target: 'es2022',
    reportCompressedSize: false,
    rolldownOptions: {
      input: entries(mode === 'gallery' ? 'frontend/test/gallery' : 'frontend/islands'),
      output: {
        entryFileNames: '[name]-[hash].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
}));
