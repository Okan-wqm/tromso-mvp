Suderra Platform is the design system of the Suderra fish-farm platform: a fish farm's whole day in one calm, legible console that a newcomer reads at a glance and an operator trusts with wet hands at the tank side. Its colour comes from the Norwegian coast — fjord water, the polar night, the northern lights, kelp and salmon — as five themes that share one grammar: a dark rail, a pale or deep canvas, slate greys, and a single brand accent on the rail. Colour runs in two channels that never mix: the area hues say where you are (navigation, page heads, module icons), the status colours say what is wrong (and only that).

This release covers the **shell** (rail sidebar and top bar) and three **Production** screens: Meal board, Production units and Water chemistry. Login and the other panels are out of scope for now.

## Principles

- **One job per colour.** `crit` means critical only. `action` blue marks what you can follow or select. `primary` ink is structure and the single commit button per view. `brand` is the theme's accent and never touches data.
- **Two colour channels that never mix** (owner, 2026-11-21: "colourful, clear, organised"; replaces "grey by default").
  - **Area hues say where you are**: farm, water, feed, stock (`area-*`), and a neutral area for people, administration,
    knowledge and reports. They colour only the rail's icons, a page head's area chip and a module icon: never a value,
    a row, a chip or a chart.
  - **Status colours say what is wrong**: ok, note, warn, critical, and stale as a second axis drawn with a hatch. A
    normal value is still `text-1` on `surface-sheet`; only a warning, a critical or an old value earns a tint, a hatch
    or an edge, and OK stays quiet (a green disc, never a green card). Note and stale have no hue at all (a note is told
    by its square and its word, stale by its hatch and its age), so no area hue can be read as one of them; every area
    hue stands at least 30° from the ok, warn and critical hues (`core/tests_contrast.py`).
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

Use the files in **Logos**: `suderra-mark-disc.png` (the fish on a white disc) is the mark in the rail head, 40px, beside the wordmark set in type: **SU** in `text-on-rail` and **DERRA** in `brand`, `font-display` 600, letter-spacing .08em — the logo's own two-tone split. `suderra-logo.png` (mark above the navy and teal wordmark) goes on white grounds only. The mark's red belongs to the logo alone; in the UI red means critical.

## Colour

Five themes, chosen per person with a cookie (never from the OS). Each is one place on the Norwegian coast; all share the same role tokens, so a template written once looks right in every theme.

| Theme | `data-theme` | Kind | The picture | Accent (`brand`) |
|---|---|---|---|---|
| **Fjord** | `fjord` (default) | day | Deep navy water (the logo navy) under a pale cold sky | logo teal `#63a2a9` |
| **Polarnatt** | `polarnatt` | night | The polar night: blue-black, light kept for text and figures | muted teal `#7cb8be` |
| **Nordlys** | `nordlys` | night, wall screens | Indigo-black sky, a faint green glow at the foot of the rail | aurora green `#7de0c3` |
| **Tang** | `tang` | day | Kelp forest: deep kelp rail, green-grey canvas | sea grass `#a9c9b4` |
| **Laks** | `laks` | day, warm | Warm snow canvas, a smokehouse-charcoal rail | salmon `#f0a08a` |

The accent lives only on the rail (DERRA in the wordmark, the 3px stripe, the active-item bar). Status colours are one set for day themes and one for night themes, so a critical chip reads the same everywhere; in Laks the salmon accent and the critical red never share a surface, and in Nordlys the aurora accent and the OK mark never do.

Use role tokens only; never write a hex in component CSS. The tokens have one source, `tokens.json`: `scripts/tokens.mjs`
builds this folder's `tokens.css` and the app's `static/css/tokens.css` from it (`npm run build:tokens`; `npm run
check:tokens`, CI and `npm test` fail when either file is not what it builds).

| Use | Token |
|---|---|
| Page ground | `surface-canvas` |
| The one sheet per page, tables, dialogs | `surface-sheet`, framed with `line-hair` |
| Table heads, row hover, wells | `surface-sunken` |
| Rail | `surface-rail` with `gradient-rail` (per theme), text `text-on-rail` |
| Text | `text-1` primary, `text-2` heads and why-lines, `text-3` help, origin and age |
| Control borders | `line-control` (3:1 on every surface, sunken included) |
| Commit button | `primary` / `primary-hover`, label `on-primary` |
| Links, selection, active tab, pressed toggles | `action`, fill `action-tint` |
| Status | `ok`, `ok-text`, `ok-tint`; `note`, `note-text`, `note-tint`; `warn`, `warn-text`, `warn-tint`; `crit`, `crit-text`, `crit-tint`, `on-crit` |
| Stale (old or assumed data, a second axis over any status) | `stale` (the hatch's lines), `stale-text`, `stale-tint`: no hue, drawn as `ui-stale` and as the hatched strip on a monitoring card |
| Area (where you are: rail icons, page-head chip, module icons only) | `area-farm`, `area-water`, `area-feed`, `area-stock`, `area-neutral`, each with `-tint` (its chip on the sheet) and `-rail` (its icon on the rail) |
| Brand | `brand` on `surface-rail` only: DERRA, the 3px `stripe-rail`, the active-item bar |
| Charts | `chart-s1`…`chart-s5`, `chart-iso`, `zone-safe`, `zone-toxic` |
| Roster shift chips | `tone-1`…`tone-8` (Fjord, Birch, Sand, Heather, Clay, Glacier, Stone, Lingon) with `text-1` |

Contrast is measured, not claimed: `core/tests_contrast.py` checks 48 pairs in each of the five themes, every text pair
at 4.5:1 and every shape at 3:1 (text-1/2/3 on sheet, canvas and sunken; action; on-primary; the rail; each status's
words on its tint and on the sheet; each area's icon on its tint, on the sheet and on the rail). The lowest text pairs
are `text-3` on sunken (4.83 in Tang) and the night themes' area icons on their tints (4.50 to 4.58). Computed contrast
in every theme (Fjord · Polarnatt · Nordlys · Tang · Laks): `text-1` on sheet 17.2 · 13.8 · 15.2 · 16.9 · 17.5;
`text-3` on sunken 5.1 · 4.9 · 5.4 · 4.8 · 5.4; `text-on-rail` on rail 12.2 · 10.5 · 12.4 · 11.9 · 12.0; `brand` on
rail 5.6 · 8.5 · 12.6 · 8.8 · 7.8; `action` on sheet 7.2 · 7.9 · 8.7 · 7.3 · 7.2; `warn-text` on `warn-tint` 6.0 · 8.2
· 8.2 · 6.0 · 6.0; `on-crit` on `crit` 6.5 · 6.7 · 6.7 · 6.5 · 6.5; `line-control` on sunken 3.4 · 3.2 · 3.6 · 3.4 ·
3.6. `warn` is a shape colour (3.6:1 on a day sheet): never set words in it, use `warn-text`.

The `slate`, `navy`, `teal`, `fjord`, `kelp`, `amber`, `ember`, `aurora`, `kelpdeep` and `salmon` scales (50–950) are the palette behind the roles, for illustration and Tailwind utilities. UI code reaches for roles first.

**Focus.** A double ring, `ring-focus`: 2px `focus-inner` inside, 2px `focus-outer` outside. On the rail, `ring-focus-rail` (white).

## Gradients

Gradients belong to **brand surfaces** only — the rail, the monitoring wall, release art — and never to data, chips, buttons or charts. Each is quiet: two or three close stops in one family, and the brightest stop is never under text.

- `gradient-rail`: per theme, the rail deepening toward its foot; in Nordlys the foot carries a faint aurora green. `text-on-rail` stays above 10:1 at every stop.
- `gradient-fjord-dusk`, `gradient-polar-night`, `gradient-nordlys`, `gradient-tang`, `gradient-laks`: one picture per theme for the wall header and release art. Nordlys and Polarnatt are also the monitoring-wall background behind its cards.
- `gradient-snow`: an optional sheen on the top of a day page head, never under figures.
- `gradient-edge-fade`: the scroll cue at a table's or tab row's continuing edge.
- `gradient-skeleton`: loading rows.

## Type

- `font-text` (Atkinson Hyperlegible Next, 400–700) for everything read or entered: its 0/O and 1/l differ, so HA-K01 never reads HA-KO1. Tabular figures on everywhere.
- `font-display` (Bricolage Grotesque 600) only for `h1`, `h2`, the `wordmark` and empty-state titles, 22px and up; never for a measured value.
- Scale: `caption` 12 (chart ticks), `head` / `small` 13 (column heads, sub-lines), `body` 15 (16 coarse), `label` 15/600, `figure` 18/600 (the one figure per row people act on), `h2` 22, `h1` and `readout` 28 (the Next meal figure). Line height 1.45, headings 1.2, prose 68ch.
- The scale is a CSS variable per step, `--fs-<name>` (`--fs-caption` … `--fs-h1`, built from `tokens.json`'s type
  styles): a stylesheet writes `font-size: var(--fs-small)`, never a number (the gate below).

## Space, radius, depth

- 4px base: `space-1`…`space-8` = 4, 8, 12, 16, 24, 32, 48, 72.
- Radius by role: `radius-chip` 4, `radius-control` 6, `radius-object` 10 (sheet, dialog, drawer, tile, card, window), `radius-pill` for badges.
- Elevation: flat by default; `shadow-raised` (elevation 1) for a card that is a link or a tile; `shadow-overlay`
  (elevation 2) for menu, drawer, dialog and movable window. Row status uses `edge-crit` / `edge-warn` (a 4px inset
  left edge).

## Shell

- Rail `rail-w` 240px from a 1280px viewport; `rail-w-compact` 72px (icons, label on focus) from 1024 to 1279px; below that a 56px bottom bar (Meals, Water, Units, Storage, More).
- The rail carries `stripe-rail` (3px brand accent on top), the logo disc and wordmark, a Company / Production panel switch, then groups in daily order: Overview, Operations, Feeding, Harvest, Health, Reports, Communication, Team, and Setup collapsed last.
- The active item is a light fill with a 4px `brand` bar — never red. A rail badge is a 20px pill; red (`crit`) only for a critical count.
- Top bar `topbar-h` 56px on `surface-canvas`: breadcrumb, the EN / TR / NB switch, user menu.
- Page head: the area chip (the page's menu icon in its area hue), `h1`, one line of status chips, the single primary
  action at right.
- The rail's icons take their line's area hue (`area-*-rail`); the label stays `text-on-rail`.

## Width

The shell never caps the width: the content area reaches the window's right edge at every width, from a 390 px phone to
the farm's 5120 × 1440 wall monitor. A page says how its content uses the room with `data-measure` on `<main>` (the
block `measure` of `app_base.html`); it never sets a page width of its own.

| Measure | Pages | At any width |
|---|---|---|
| `fluid` (the default) | lists, tables, dashboards, read pages, the calculator, monitoring | everything fills the width: tables to the edge, cards in more columns, a read page's sections side by side |
| `wall` | monitoring `?wall=1` | no chrome, the whole screen; the cards per screen follow the wall's slot rule |
| `form` | `crud/form.html` and every form built on it | the fields flow into columns of at least 17 rem, as many as they fill (an unused column folds away, so they spread over the width), none wider than 32 rem (a text area 75 ch); from 1280 px the form's sections (its tab list) stand beside it as a sticky outline |
| `prose` | long text (a document's text) | each block keeps a reading measure (70 ch) and the blocks flow into as many columns as fit, with the page's `ui-aside` (its outline) beside them from 1280 px |

Neither `form` nor `prose` leaves a dead band: what a wider window adds becomes columns, never empty space.
`frontend/test/layout.browser.test.ts` holds a fluid page's content to the window's right edge less the gutter at 390,
1024, 1280, 1440, 1920, 2560, 3440 and 5120 px.

## Components

One rule set per pattern, in `static/css/ds.css`, read by every page; it reads only tokens. Each pattern's name is the
design system's `ui-*` class; the older class names of the same pattern are listed beside it in the same rule, so a
template not yet migrated looks the same without an edit, and the gate below counts them down.

| Pattern | Class | Variants and states | Older names drawn by it |
|---|---|---|---|
| Button | `ui-btn` | secondary (outlined) by default; `data-variant` `primary` (one per view), `danger`, `link`; `data-size="coarse"`; `aria-pressed`; disabled; 40 px, 48 on a coarse pointer | `button` (primary), `button-ghost` (secondary), `button-danger`, `filter-button`; `icon-button` is the square icon button |
| Field | `.field` (label, control, `.help`, `.errorlist`), and `ui-control` for a control outside a form | 40 px controls, a 1.5 px `line-control` edge, the action ring on focus, a `crit` edge on error | every input, select and text area in `.field`, a `ui-toolbar`, `.search` and the old filter wrappers |
| Filter bar | `ui-toolbar` | one wrapping row, a labelled control's label above it, the last button at the right | `toolbar`, `filter-bar`, `monitor-filters`, `feeding-filters`, `water-filters` |
| Table | `ui-table` in `ui-table-wrap` | sunken head, rows with hover, `.num` right-aligned on one line; the frame scrolls and shades the side that goes on | `data-table` in `table-wrap` |
| Tabs | `ui-tabs` of `ui-tab` | a button tab (`aria-selected`) and a link tab (`aria-current="page"`) look alike: the action underline; `ui-count` beside a name; `tab-error` | `tabs`/`tab`, `view-tabs`/`view-tab`, `view-count` (every template migrated) |
| Badge | `ui-chip` with `data-status` (ok, note, warning, critical, hold, neutral) or `data-state` (nodata, stale) | glyph and word, a ladder of fill weight | `badge` with `badge-<status>` (each mapped to a tone) |
| Card | `ui-card` (`ui-sheet` for a frame without padding) | flat; raised one step when it is a link | `card`, `tile`, `calc-card` |
| Page head | `ui-head` | area chip, `h1`, status line, actions | (one, in `app_base.html`) |

The field markup is one template for every form (`templates/django/forms/field.html`, drawing
`registration/_field.html`, which `crud/form.html` includes too): the label bound to the control, the server's own
`min`, `max` and `step` on it (the browser's check mirrors the server's rule; nothing is written again in TypeScript),
the help line and the errors tied to it by `aria-describedby`, and `aria-invalid` in error
(`core.tests_templates.FieldMarkupTests`).

## The gate

`npm run check:ds` (`scripts/check-ds.mjs`; CI and `npm test` run it) fails on a one-off style:

- a colour (hex, `rgb()`, `hsl()`, a named colour) anywhere but `tokens.css`;
- a raw font size or radius in `ds.css`, the component layer;
- more raw font sizes or radii (px or rem, not a token) in an older sheet than the ratchet allows for it;
- more uses of an older class name (`button`, `data-table`, `badge`, `tabs`, `view-tab`, `toolbar`, `card`, …) in the
  templates than the ratchet allows, or more arbitrary Tailwind sizes (`tw:text-[13px]`);
- a count that went down while the ratchet was not lowered with it.

The ratchet is `ds-ratchet.json` in this folder: today's counts, which may only go down (`node scripts/check-ds.mjs
--write` after a migration). `frontend/test/check-ds.test.ts` plants each kind of fault in a throwaway tree and proves
the gate catches it.

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
- Do not put eyebrows over every block or arrows on buttons.
- Do make the production overview a dashboard (the owner's decision, over the earlier "no KPI tile row"): its figures are metric cards on one sheet, several to a row (five from 768 px, two on a phone), each the figure large with its label, one sub-line and its source and time, the whole card the link. A card is grey; only an abnormal figure gets the 4px `edge-crit` / `edge-warn`, its glyph and the status word in its label. No figure as a label | figure | link bar across the page.
- Do not let a table scroll silently or cut its actions.
