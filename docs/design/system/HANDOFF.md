# Suderra Platform design system: hand-off for the implementer

This folder is the design system for the Suderra app. Apply it to the Django templates and `static/css` as described below. `README.md` is the brand book (rules); this file says how to get there from today's code.

## What is in this folder

| File | What it is |
|---|---|
| `README.md` | The rules: principles, colour roles, gradients, type, space, shell, tables, icons, motion, do/don't. Read it first. |
| `tokens.json` | The source of truth: every colour in the five themes (Fjord, Polarnatt, Nordlys, Tang, Laks), type style, spacing, radius, shadow, gradient, size, z-index, each with a usage note. |
| `tokens.css` | The same tokens as CSS custom properties: `:root, [data-theme="fjord"]` (the default), then one block per other theme (`polarnatt`, `nordlys`, `tang`, `laks`), then the theme-independent ones. |
| `components.css` | The `ui-*` component classes (rail, top bar, page head, buttons, chips, tabs, toolbar, segmented toggle, table, value face, gauge, meal pips). Reads only tokens. |
| `components/*.md` | Guidelines per component: when to use, what the template provides, states. |
| `previews/*.html` | Open in a browser: the target look for the sidebar, top bar, buttons, chips and three Production screens (Meal board, Production units, Water chemistry). A theme switch sits bottom right. |
| `tailwind.md` | Tailwind v4 `@theme` and v3 preset over the same variables, and how the app uses it ("In this app": utilities only, `tw:` prefix, built into `static/css/tw.css`). |
| `assets/logos/` | `suderra-mark-disc.png` (rail mark), `suderra-mark.png`, `suderra-logo.png`. |
| `../claude-design-brief.md` | The full product brief: screens, data, states, responsive rules, acceptance tests. |

## Scope of this release

The shell (rail sidebar + top bar) and three Production pages: Meal board (`templates/farm/meal_board.html`), Production units (`templates/farm/production_units.html`) and Water chemistry (the water templates). Login and the other pages keep working on the new tokens but get no redesign yet.

## Steps

1. **Tokens.** Copy `tokens.css` to `static/css/tokens.css` and load it first in `templates/app_base.html` (and `auth_base.html`). Copy `components.css` to `static/css/ui.css`, loaded after `base.css`.
2. **Fonts.** Replace the Google Fonts link with Atkinson Hyperlegible Next (400–700) and Bricolage Grotesque (opsz, 600): `https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400..700&family=Bricolage+Grotesque:opsz,wght@12..96,600&display=swap`, or self-host both as woff2 (the brief prefers self-hosting). Remove the `@import` line at the top of `ui.css` once the link is in the templates.
3. **Map the old variables** in `base.css`, `app.css`, `components.css` and the module sheets, then delete the old `:root` block:

   | Old | New |
   |---|---|
   | `--mist` | `--surface-canvas` |
   | `--white` | `--surface-sheet` |
   | `--rail-bg` | `--surface-rail` (the rail is now dark: its text becomes `--text-on-rail`) |
   | `--speck` | `--text-1` |
   | `--olive`, `--olive-deep` | `--primary` for the commit button; `--text-1` for text |
   | `--muted` | `--text-3` (help, sub-lines) or `--text-2` (column heads) |
   | `--sage` as a control border | `--line-control` |
   | `--sage` as a divider, `--line` | `--line-hair` |
   | `--stripe` on the primary button | `--primary` / `--primary-hover`, label `--on-primary` |
   | `--stripe` on links, the active tab, selection, the pressed language | `--action`, fill `--action-tint` |
   | `--stripe` as the rail's top edge | `--stripe-rail` (box-shadow) |
   | `--stripe-dark` | `--action` (links) |
   | `--error` | `--crit` (fills, edges) / `--crit-text` (text) |
   | `#F7E6E6` | `--crit-tint` |
   | `#FBF0D9` / `#7A5410` | `--warn-tint` / `--warn-text` |
   | `#C58A16` | `--warn` |
   | `--hover` | `--surface-sunken` |
   | `--active-bg` | `--action-tint` |
   | `--font` | `--font-text` (headings h1/h2: `--font-display`) |
   | `--font-mono` | drop it; the brief bans monospace |

   No colour literal may remain in any stylesheet; `grep -nE "#[0-9A-Fa-f]{3,8}\b|rgba?\(" static/css/*.css` should return only `tokens.css`.
4. **Theme.** Fjord is the default. Set `data-theme` on `<html>` from a cookie (`fjord`, `polarnatt`, `nordlys`, `tang`, `laks`), never from `prefers-color-scheme`. Add the choice to the user menu next to the language; Nordlys is meant for the monitoring wall.
5. **Rail.** Rebuild the rail in `app_base.html` / `_workspace_brand.html` to match `previews/Sidebar.html`: `ui-rail` with the logo disc (`static/img/suderra-mark-disc.png`, 40px, empty `alt`) and the type wordmark `SU<span>DERRA</span>`, the Company / Production switch, groups in daily order, `aria-current="page"` on the active link, badges as `ui-rail-badge` (`data-status="critical"` only for a critical count). Keep today's collapse behaviour, with 72px as the collapsed width.
6. **Top bar and page head** as in `previews/TopBar.html`: breadcrumb, the EN / TR / NB switch moved out of the user menu, the user menu, then `h1`, one row of status chips and the single primary action.
7. **The three pages** as in their previews: real `<table>` in `ui-table-wrap` (`tabindex="0"`, `aria-label`), sticky first column and sticky actions, units in heads, `ui-value` for every value with origin and age, `ui-why` for missing figures, status as `ui-chip` with glyph and word.

## Rules that are easy to miss

- Red (`--crit`) means critical only. Never brand, link or button.
- The brand accent (`--brand`, different per theme) only on the rail: DERRA, the stripe, the active-item bar. Never on data.
- A normal value stays `--text-1`; only warning, critical or stale values get colour.
- `--warn` is for shapes; words in warning use `--warn-text`.
- Gradients only on brand surfaces (rail, monitoring wall); never on data, chips or buttons.
- Sentence case, no `text-transform`, no all-caps (Turkish İ/ı).
- Every text pair is at least 4.5:1 in all five themes (see `README.md`). Keep it that way when adding colours.

## Done when

- The sidebar and the three pages match their previews in all five themes at 1440, 1024 and 390 px.
- The acceptance list in `../claude-design-brief.md` section 7 passes for those pages.
- The existing test suite (`python manage.py test`, `npm test`) still passes.
