# Tailwind

Suderra Platform works with Tailwind as a theme over the same CSS custom properties, so all five themes (Fjord, Polarnatt, Nordlys, Tang, Laks) switch with `data-theme` and no class changes. Load `tokens.css` first; Tailwind only names the variables.

## Tailwind v4 (recommended)

```css
@import "tailwindcss";
@import "./tokens.css";

@custom-variant night (&:where([data-theme="polarnatt"], [data-theme="polarnatt"] *, [data-theme="nordlys"], [data-theme="nordlys"] *));

@theme inline {
  --font-text: var(--font-text);
  --font-display: var(--font-display);

  --color-canvas: var(--surface-canvas);
  --color-sheet: var(--surface-sheet);
  --color-sunken: var(--surface-sunken);
  --color-rail: var(--surface-rail);
  --color-on-rail: var(--text-on-rail);
  --color-hair: var(--line-hair);
  --color-control: var(--line-control);
  --color-ink-1: var(--text-1);
  --color-ink-2: var(--text-2);
  --color-ink-3: var(--text-3);
  --color-primary: var(--primary);
  --color-primary-hover: var(--primary-hover);
  --color-on-primary: var(--on-primary);
  --color-action: var(--action);
  --color-action-tint: var(--action-tint);
  --color-brand: var(--brand);
  --color-ok: var(--ok);
  --color-warn: var(--warn);
  --color-warn-text: var(--warn-text);
  --color-warn-tint: var(--warn-tint);
  --color-crit: var(--crit);
  --color-crit-text: var(--crit-text);
  --color-crit-tint: var(--crit-tint);
  --color-on-crit: var(--on-crit);

  --radius-chip: var(--radius-chip);
  --radius-control: var(--radius-control);
  --radius-object: var(--radius-object);
  --shadow-overlay: var(--shadow-overlay);

  --background-image-rail: var(--gradient-rail);
  --background-image-dusk: var(--gradient-fjord-dusk);
  --background-image-polar: var(--gradient-polar-night);
  --background-image-nordlys: var(--gradient-nordlys);
  --background-image-tang: var(--gradient-tang);
  --background-image-laks: var(--gradient-laks);
}
```

Spacing needs no mapping: Tailwind's 4px step already matches `space-1`…`space-8` (`p-1` 4, `p-2` 8, `p-3` 12, `p-4` 16, `p-6` 24, `p-8` 32, `p-12` 48, `p-18` 72).

## Tailwind v3 preset

```js
// tailwind.tromso.js — add to presets: [require('./tailwind.tromso')]
const v = (name) => `var(--${name})`;
module.exports = {
  theme: {
    extend: {
      fontFamily: { text: v('font-text'), display: v('font-display') },
      colors: {
        canvas: v('surface-canvas'), sheet: v('surface-sheet'), sunken: v('surface-sunken'),
        rail: v('surface-rail'), 'on-rail': v('text-on-rail'),
        hair: v('line-hair'), control: v('line-control'),
        ink: { 1: v('text-1'), 2: v('text-2'), 3: v('text-3') },
        primary: { DEFAULT: v('primary'), hover: v('primary-hover'), on: v('on-primary') },
        action: { DEFAULT: v('action'), tint: v('action-tint') },
        brand: v('brand'),
        ok: v('ok'),
        warn: { DEFAULT: v('warn'), text: v('warn-text'), tint: v('warn-tint') },
        crit: { DEFAULT: v('crit'), text: v('crit-text'), tint: v('crit-tint'), on: v('on-crit') },
        // palette scales, literal so opacity modifiers work: bg-navy-900/80
        slate: { 50: '#f7f8fa', 100: '#f2f4f6', 200: '#e6eaee', 300: '#cbd3db', 500: '#76848f', 600: '#5b6874', 700: '#3a4653', 800: '#243442', 900: '#16222e', 950: '#0f161d' },
        navy: { 300: '#8899b7', 700: '#22335a', 800: '#152151', 900: '#101a3e', 950: '#0a1124' },
        teal: { 400: '#7cb8be', 500: '#63a2a9', 600: '#5598a1', 800: '#2c5a60' },
      },
      borderRadius: { chip: v('radius-chip'), control: v('radius-control'), object: v('radius-object') },
      boxShadow: { overlay: v('shadow-overlay'), focus: v('ring-focus'), 'edge-crit': v('edge-crit'), 'edge-warn': v('edge-warn'), stripe: v('stripe-rail') },
      backgroundImage: { rail: v('gradient-rail'), dusk: v('gradient-fjord-dusk'), polar: v('gradient-polar-night'), nordlys: v('gradient-nordlys'), tang: v('gradient-tang'), laks: v('gradient-laks'), 'edge-fade': v('gradient-edge-fade') },
      height: { control: v('control-h'), coarse: v('control-h-coarse'), topbar: v('topbar-h') },
      width: { rail: v('rail-w'), 'rail-compact': v('rail-w-compact'), drawer: v('drawer-w') },
    },
  },
};
```

## The rules still hold

- Use role utilities (`bg-sheet text-ink-1 border-control`), not palette steps, in UI. Scales (`navy-900`, `teal-500`, …) are for illustration.
- Gradient utilities (`bg-rail`, `bg-dusk`, `bg-polar`, `bg-nordlys`, `bg-tang`, `bg-laks`) only on brand surfaces.
- `text-warn` is a shape colour; words in warning use `text-warn-text`.
- `bg-crit` only for critical. Never `bg-brand` on data, links or buttons.

```html
<a class="flex items-center gap-3 min-h-control px-3 rounded-control text-on-rail hover:bg-white/10 aria-[current=page]:bg-white/15 aria-[current=page]:font-bold">Meal board</a>
<button class="min-h-control px-4 rounded-control bg-primary hover:bg-primary-hover text-primary-on font-semibold">Record meal</button>
<span class="inline-flex items-center gap-1 h-6 px-2 rounded-chip bg-crit text-crit-on text-[13px] font-semibold">Critical</span>
```

## In this app

The console uses Tailwind v4 (`tailwindcss` and `@tailwindcss/cli`, pinned exactly in `package.json`) for its redesigned
pages, beside the `ui-*` parts of `components.css` (`static/css/ui.css`), and not as above in four ways:

- **Utilities only.** `frontend/tailwind.css` imports `tailwindcss/utilities.css` alone: no preflight (`base.css` and
  `ui.css` are the reset of every page) and no default theme (no palette, no sizes nobody chose). Its `@theme inline`
  maps the role tokens above, the type scale (`text-caption` 12 … `text-h1` 28), `--spacing: var(--space-1)` and the
  shell's breakpoints (`sm` 640, `lg` 1024, `xl` 1280 px). Two variants: `coarse` (`@media (pointer: coarse)`, for the
  48 px tank-side targets: `tw:coarse:min-h-12`, 56 px for the primary) and `night`.
- **A prefix.** Every class is `tw:`-prefixed (`tw:grid tw:gap-6 tw:xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]`), so a
  template's own class names (`hidden`, `table`, `collapse`) never meet a utility.
- **No cascade layer.** The build is unlayered and loaded last (`templates/app_base.html`): a layered utility would lose
  to every unlayered rule of the older sheets (`a` in `base.css`), whatever its specificity. Only Tailwind's
  `@layer properties` fallback (initial values of its own `--tw-*` variables) is layered.
- **Built and committed.** `npm run build` (and `npm run build:css` alone) writes `static/css/tw.css` from the source,
  reading the class names of `templates/**/*.html` and the apps' Python; `npm run check:css` fails when the committed
  file is stale (CI runs it before the build, and `npm test` too). No CDN, no Play CDN, nothing in the browser: the
  Content-Security-Policy stays `style-src 'self'`.

`core/tests_tailwind.py` holds it: the theme names only tokens of `tokens.css` (no colour literal), the source imports
the utilities alone, every app is read, the build styles only an element with a `tw:` class (so a page not redesigned is
unchanged), it is in no layer, it loads last, the tool is pinned and listed in `THIRD_PARTY.md`, and CI checks it.
