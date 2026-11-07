# Review notes: wip/bugs-nov5

The defects seen walking the live app (claude-design brief, section 17, items 1-25). Each: its root cause, the fix (one
rule, at the layer that owns it), the tests that pin it, and what was decided or left. Every behaviour was written as a test
first and seen failing for the right reason (the `Test:` commits), then fixed in its own commit, with its README or
docs/i18n.md part.

## Layout: tables, overflow, buttons (A, B, C, N, E/17/18, 19, 25)

- **A wide tables cut their columns, pages scroll sideways.** Root causes, five classes: the table frame scrolled but gave
  no sign of it (no cue, scrollbars hidden or far below); bare `1fr` grid tracks (`.form-grid` on a phone, `.detail`'s
  implicit `auto` track) grow to their widest content; `.view-tabs` and filter selects (a long option) never wrapped;
  a long word (a content hash) never broke; a `.sr-only` label inside a scroller (the role matrix's `.matrix-wrap` had no
  `position: relative`) lay at its static place far right. Fix: `.table-wrap` is the one frame (the matrix and the
  calculator tables use it too, `.table-wrap-bare` in a card) with shades on the side the table goes on (pure CSS,
  local/scroll backgrounds), a thin visible scrollbar; every fr track `minmax(0, …)`; `.content` breaks long words;
  view tabs, filters and a notice's list wrap; `.sr-only` pinned left. Tests: `core/tests_templates.py`
  (every table in `.table-wrap`, no bare fr track), `frontend/test/layout.browser.test.ts` (no page scrolls sideways at
  390/1024/1440, the cue on the right side only while more lies there, and none on a table that fits).
- **B batch table one word a line**: a table wider than its frame gives each column its min-content. Fix: a cell of words
  (`:has(> .row-sub)`, not `.num`) keeps 10 rem; on a phone the first column's `.nowrap` lines wrap.
- **C row actions ran together**: no spacing rule for text actions. Fix: `td.row-actions > * + *` margin.
- **N buttons**: `.button` is full width (auth pages) and the approve dialog used it in `.form-actions`; the record form's
  Save showed on a row-list tab. Fix: one rule for `.form-actions` (others first, the one filled button last, as wide as its
  words), the record form's buttons hidden while none of its own panels shows; `leave_detail` reordered. Test: the
  template scan for button order and the browser test.
- **E/17/18 value glued to its origin, origin wrapping word by word**: `.wq-source` had no CSS at all; on the card the
  origin line took the figure's font size (`.metrics dd` outranked `.row-sub`). Fix: one part
  `farm/_water_source.html` (origin and age as two inline blocks, so the line breaks only between them) used by the water
  page, the Deffeyes window and the cards; `.metrics dd.row-sub` at line size; a card's water cells at least 8.5 rem.
- **19 Norwegian Monitoring 1448 px**: the same classes (long Norwegian words in fixed-min metrics cells); the browser
  test has a Norwegian card and was seen failing on the old style sheets.
- **25 Sensors › Channels on a phone**: the filter select class of A.

## Figures and words (D, 20, I, J, K, 23)

- **D 251.804 kg beside 1,420 kg**: `amount()` showed up to three decimals, which read as a thousands group. Fix: under a
  kilogram to the gram, from a kilogram at most two decimals, trailing zeros dropped, every language. The cards' golden
  record was edited for the new figures (1.06 kg, 0.11 kg), a deliberate change, not a re-record.
- **20 Live values 13 / 45.400**: `floatformat:"-3"`. Fix: `sensors` filter `measured`, the quantity's own decimals (a
  water parameter's), also for alarm thresholds and peaks.
- **I raw keys in a filed report's differences**: Fix: `reports/labels.py` names a content path as the page names the
  figure, the unit by its number.
- **J sea-lice page showed notice fields**: `_figures.html` fell back to the notice fields for any kind without its own
  table. Fix: notice fields only for notices; any other kind lists the print page's rows (one partial `_rows.html`).
- **K overview 0 critical vs water page 1**: the overview read the units' middle points only. Fix: the tile is the water
  page's own count ("Sampling points with a critical water value").
- **23 HA-K02 side outlet Critical on 5 Nov, No limit on 6 Nov**: found by reading the dev database: the CO₂ 15.6 sample
  (3 Nov 08:15) passed CO₂'s 72 fresh hours on 6 Nov; the row's other values (alkalinity …) have no limit row for salmon,
  and `PointWater.status` ranked "No limit" before "Stale". Fix: a point whose judged values aged is Stale; a value without
  a limit carries why (no fish in the unit / no limit set for the fish; the species is not named, a water reader need not
  read the stock), shown under the point's status. The earlier test expecting "No limit" there was changed on purpose.
  **Overlap to check at landing: wip/fix-monitoring (F-244) also changes how a stale critical value is judged
  (`Reading.judged`, `old_alert`); the two must be reconciled in `PointWater.status`.**

## People (F, G, H, 24)

- **F leave "Off" on the schedule, "On leave" in the overview**: two readings. Fix: `hr.read.Cell.state`, read by both.
- **G Today tiles did not add up**: only some states had tiles. Fix: `Board.tiles` partitions the planned people
  (upcoming, here with the late said in it, not in yet, absent, on leave, done); "Here, not planned" apart; someone on
  leave with nothing planned is not listed.
- **H "Nobody else" to the admin**: Fix: no Crew block for someone with no employee record; an unplaced worker is told
  why; the block follows the list or its empty state (`crud/list.html` block `below`).
- **24 Team overview open by URL to a worker**: `show_when` was a menu courtesy only. Decision (one rule, owner's
  request): `core.middleware.MenuAccessMiddleware` refuses a page whose menu line is left out for the person; a
  production-only worker is now refused Company › HR pages too (they use Production › Team). Test walks every line for
  every starting role, a lead, an office person and the admin.

## Dates, time zones, error pages (L, 22, M, 21)

- **L mixed date styles**: English had no TIME_FORMAT/short formats of its own (Django's `9:04 p.m.`, `10/26/2026`).
  Fix: one style per language, templates only through named formats (scanned by a test), Python text too.
- **22 date inputs (owner rule)**: typed and shown `dd.mm.yyyy` and `dd.mm.yyyy HH:MM` in every language, ISO read too;
  every form date field defaults to the shared `DayInput`/`MomentInput` (core apps), filters use `{% day_input %}` and
  one `core.dates.read_day` (nine ISO parsers removed); `frontend/date-input.ts` (no library, no picker) tidies what is
  typed. Test walks every form class of the project. Not done: a calendar picker.
- **M site without a time zone ran on UTC**: Fix: the zone is required (DB check, form asks, default the company's
  `settings.TIME_ZONE`); migration `farm/0030_site_timezone_required` fills empty zones with the company's. **0027-0029 are
  other branches'; this one still depends on 0026, so the landing links it after them.** With TIME_ZONE = UTC the migration
  writes UTC: check each site's zone after it (the seeded Bergen/Tromsø sites).
- **21 bare 403**: `templates/403.html`, `404.html` in the shell, `500.html` standalone.

## Weak points

- Screenshots "after" were taken by injecting this branch's CSS into the dev server's pages (main's HTML, read-only):
  A-C and E show; D, O and every template change need the live check after landing.
- The table frame's cue is a shade (no sticky actions column); on a phone the actions are reached by scrolling the frame.
- Page dates (not typed) keep each language's display format (`26 Oct 2026`, `26. oktober 2026`); the owner rule was
  applied to entry boxes. Say if the display should be dd.mm.yyyy too.
- The test runs on this machine took 1.5-2 h each under the other branches' load.
