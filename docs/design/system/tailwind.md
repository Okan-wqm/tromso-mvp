# Tailwind

Suderra Platform works with Tailwind as a theme over the same CSS custom properties, so Day, Night and Fjord switch with `data-theme` and no class changes. Load `tokens.css` first; Tailwind only names the variables.

## Tailwind v4 (recommended)

```css
@import "tailwindcss";
@import "./tokens.css";

@custom-variant night (&:where([data-theme="dark"], [data-theme="dark"] *));
@custom-variant fjord (&:where([data-theme="fjord"], [data-theme="fjord"] *));

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
  --color-brand: var(--brand-teal);
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
  --background-image-aurora: var(--gradient-aurora);
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
        brand: v('brand-teal'),
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
      backgroundImage: { rail: v('gradient-rail'), dusk: v('gradient-fjord-dusk'), polar: v('gradient-polar-night'), aurora: v('gradient-aurora'), 'edge-fade': v('gradient-edge-fade') },
      height: { control: v('control-h'), coarse: v('control-h-coarse'), topbar: v('topbar-h') },
      width: { rail: v('rail-w'), 'rail-compact': v('rail-w-compact'), drawer: v('drawer-w') },
    },
  },
};
```

## The rules still hold

- Use role utilities (`bg-sheet text-ink-1 border-control`), not palette steps, in UI. Scales (`navy-900`, `teal-500`, …) are for illustration.
- Gradient utilities (`bg-rail`, `bg-dusk`, `bg-polar`, `bg-aurora`) only on brand surfaces.
- `text-warn` is a shape colour; words in warning use `text-warn-text`.
- `bg-crit` only for critical. Never `bg-brand` on data, links or buttons.

```html
<a class="flex items-center gap-3 min-h-control px-3 rounded-control text-on-rail hover:bg-white/10 aria-[current=page]:bg-white/15 aria-[current=page]:font-bold">Meal board</a>
<button class="min-h-control px-4 rounded-control bg-primary hover:bg-primary-hover text-primary-on font-semibold">Record meal</button>
<span class="inline-flex items-center gap-1 h-6 px-2 rounded-chip bg-crit text-crit-on text-[13px] font-semibold">Critical</span>
```
