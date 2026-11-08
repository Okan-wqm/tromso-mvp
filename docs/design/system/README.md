Suderra Platform is the design system of the Suderra fish-farm platform: a fish farm's whole day in one calm, legible console that a newcomer reads at a glance and an operator trusts with wet hands at the tank side. Its palette is northern and cold — a deep navy rail like the fjord at night, snow-white canvas, slate greys — with one brand accent taken from the logo, and colour otherwise kept for what is abnormal.

This release covers the **shell** (rail sidebar and top bar) and three **Production** screens: Meal board, Production units and Water chemistry. Login and the other panels are out of scope for now.

## Principles

- **One job per colour.** `crit` means critical only. `action` blue marks what you can follow or select. `primary` ink is structure and the single commit button per view. `brand-teal` is the brand accent and never touches data.
- **Grey by default, colour only for the abnormal.** A normal value is `text-1` on `surface-sheet`. Only a warning, critical or stale value earns a tint.
- **Status is shape, word and fill weight; colour comes third.** Every status chip carries a glyph and a word, so it survives greyscale, colour blindness and glare.
- **Five numbers never wrap, clip or hide:** unit, decision figure, status, next action, age.
- **Every value says where it came from and how old it is** ("Sensor, 40 s ago", "Manual, 2 d ago"). "no data" is a word, never a dash or 0.
- **Say why when something is absent.** Use a `ui-why` line: "12.3 °C is outside this table (8.0–12.0 °C), so no ration is worked out."
- **Tank side first.** 48px targets on coarse pointers, 56px for the primary; the next meal recorded in three taps.

## Content

- Sentence case everywhere. No all-caps, no `text-transform` (Turkish İ and ı break), no monospace.
- One name per action from label to confirmation: "Record meal" → "Meal recorded".
- Units live in the column head ("Biomass (kg)"), with a non-breaking space before a unit in cells ("1,045 kg"). One precision per column.
- Write in three real languages (EN, TR, NB) and design for +50 % label length: heads wrap, buttons size by padding, tabs scroll.
- Numbers: 1,234.5 (EN), 1.234,5 (TR), 1 234,5 (NB). Dates: "3 Nov 2026, 19:21", 24-hour, Monday first.
- Authority terms stay Norwegian with a gloss ("Lokalitetsnummer").

## Logo

Use the files in **Logos**: `suderra-mark-disc.png` (the fish on a white disc) is the mark in the rail head, 40px, beside the wordmark set in type: **SU** in `slate-50` and **DERRA** in `brand-teal`, `font-display` 600, letter-spacing .08em — the logo's own two-tone split. `suderra-logo.png` (mark above the navy and teal wordmark) goes on white grounds only. The mark's red belongs to the logo alone; in the UI red means critical.

## Colour

Three themes. Use role tokens only; never write a hex in component CSS.

- **Day** (`light`, default): the logo theme — navy rail (`#13203a`), snow canvas, slate greys, logo teal accent.
- **Night** (`dark`, set by cookie, never by the OS): the same roles on deep navy.
- **Fjord** (`fjord`): navy-graphite rail (`#1b232c`), whiter canvas, cooler slate, and ice blue (`#8ccbdc`) as the single brand accent. Status colours are Day's.

| Use | Token |
|---|---|
| Page ground | `surface-canvas` |
| The one sheet per page, tables, dialogs | `surface-sheet`, framed with `line-hair` |
| Table heads, row hover, wells | `surface-sunken` |
| Rail | `surface-rail` with `gradient-rail` / `gradient-rail-night` / `gradient-rail-fjord`, text `text-on-rail` |
| Text | `text-1` primary, `text-2` heads and why-lines, `text-3` help, origin and age |
| Control borders | `line-control` (3:1 on every surface, sunken included) |
| Commit button | `primary` / `primary-hover`, label `on-primary` |
| Links, selection, active tab, pressed toggles | `action`, fill `action-tint` |
| Status | `ok`; `warn`, `warn-text`, `warn-tint`; `crit`, `crit-text`, `crit-tint`, `on-crit` |
| Brand | `brand-teal` on `surface-rail` only: DERRA, the 3px `stripe-rail`, the active-item bar (ice in Fjord) |
| Charts | `chart-s1`…`chart-s5`, `chart-iso`, `zone-safe`, `zone-toxic` |
| Roster shift chips | `tone-1`…`tone-8` (Fjord, Birch, Sand, Heather, Clay, Glacier, Stone, Lingon) with `text-1` |

Computed contrast, Day / Night / Fjord: `text-1` on sheet 17.2 / 13.8 / 17.3; `text-3` on sunken 4.7 / 4.9 / 5.3; `text-on-rail` on rail 12.2 / 10.5 / 11.5; `brand-teal` on rail 5.6 / 8.5 / 8.8; `action` on sheet 7.2 / 7.9 / 6.7; `warn-text` on `warn-tint` 6.0 / 8.2 / 6.0; `on-crit` on `crit` 6.5 / 6.7 / 6.5; `line-control` on sunken 3.2 / 3.2 / 3.6. `warn` is a shape colour (3.6:1 Day): never set words in it, use `warn-text`.

The `slate`, `navy`, `teal`, `fjord`, `kelp`, `amber` and `ember` scales (50–950) are the palette behind the roles, for illustration and Tailwind utilities. UI code reaches for roles first.

**Focus.** A double ring, `ring-focus`: 2px `focus-inner` inside, 2px `focus-outer` outside. On the rail, `ring-focus-rail` (white).

## Gradients

Gradients belong to **brand surfaces** only — the rail, the monitoring wall, release art — and never to data, chips, buttons or charts. Each is quiet: two or three close stops in one family.

- `gradient-rail` / `gradient-rail-night` / `gradient-rail-fjord`: the rail deepening toward its foot; `text-on-rail` stays above 10:1 at every stop.
- `gradient-fjord-dusk`: dark water rising to a pale sky, the brand picture for release art and the wall header.
- `gradient-polar-night`: the Night monitoring wall behind its cards.
- `gradient-aurora`: navy to fjord blue to logo teal, for marketing and release splashes only.
- `gradient-snow`: an optional sheen on the top of a Day page head, never under figures.
- `gradient-edge-fade`: the scroll cue at a table's or tab row's continuing edge.
- `gradient-skeleton`: loading rows.

## Type

- `font-text` (Atkinson Hyperlegible Next, 400–700) for everything read or entered: its 0/O and 1/l differ, so HA-K01 never reads HA-KO1. Tabular figures on everywhere.
- `font-display` (Bricolage Grotesque 600) only for `h1`, `h2`, the `wordmark` and empty-state titles, 22px and up; never for a measured value.
- Scale: `caption` 12 (chart ticks), `head` / `small` 13 (column heads, sub-lines), `body` 15 (16 coarse), `label` 15/600, `figure` 18/600 (the one figure per row people act on), `h2` 22, `h1` and `readout` 28 (the Next meal figure). Line height 1.45, headings 1.2, prose 68ch.

## Space, radius, depth

- 4px base: `space-1`…`space-8` = 4, 8, 12, 16, 24, 32, 48, 72.
- Radius by role: `radius-chip` 4, `radius-control` 6, `radius-object` 10 (sheet, dialog, drawer, tile, card, window), `radius-pill` for badges.
- Flat by default; one shadow, `shadow-overlay`, for menu, drawer, dialog and movable window. Row status uses `edge-crit` / `edge-warn` (a 4px inset left edge).

## Shell

- Rail `rail-w` 240px from a 1280px viewport; `rail-w-compact` 72px (icons, label on focus) from 1024 to 1279px; below that a 56px bottom bar (Meals, Water, Units, Storage, More).
- The rail carries `stripe-rail` (3px brand accent on top), the logo disc and wordmark, a Company / Production panel switch, then groups in daily order: Overview, Operations, Feeding, Harvest, Health, Reports, Communication, Team, and Setup collapsed last.
- The active item is a light fill with a 4px `brand-teal` bar — never red. A rail badge is a 20px pill; red (`crit`) only for a critical count.
- Top bar `topbar-h` 56px on `surface-canvas`: breadcrumb, the EN / TR / NB switch, user menu.
- Page head: `h1`, one line of status chips, the single primary action at right.

## Tables

Every table is a real `<table>` in a `ui-table-wrap` that scrolls inside itself with `tabindex=0` and a label. First column and the row actions are sticky, so Edit and Record never scroll out of sight. Heads `head` in `text-2` on `surface-sunken`; figures right-aligned; rows 40px (one line), 52px (two), 56px coarse. Critical rows get `edge-crit`; empty or unmeasured rows fold into one group ("Not measured (8)"). Below 640px, tables over four columns become cards.

## Iconography

Lucide-style outline SVGs from the codebase (`templates/icons/`, 24px grid), inlined so they take `currentColor`: 20px at stroke 1.75 in the rail, 16px at stroke 2 inline and in chips. Status glyphs: check-circle (OK), triangle (warning), octagon (critical), hourglass (hold), clock (stale). A status glyph never appears without a word. No emoji.

## Motion

Only four things move: drawer, dialog and movable window open in 180ms; recording a meal fills the next pip in 200ms; the Deffeyes water dot glides 200ms; a monitoring card that changes state crossfades. Colour transitions on hover are 150ms. `prefers-reduced-motion` turns all of it off.

## Do and do not

- Do make the next meal the largest figure on the board (`readout`).
- Do keep a safety sentence visible: "Nobody is alerted: critical values are shown here, not sent."
- Do not use red for brand, link or button; do not put the brand accent on data; do not colour a normal value.
- Do not put a KPI tile row on an overview, eyebrows over every block, or arrows on buttons.
- Do not let a table scroll silently or cut its actions.
