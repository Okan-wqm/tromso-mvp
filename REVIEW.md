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

## Cross-review (audit-verify/REVIEW-CROSS-bugs.md) and the owner's later rules

Each finding was answered test first (`Test:` commits), then fixed, no history rewritten.

- **F1 company zone**: `COMPANY_TIME_ZONE` (environment, Europe/Oslo by default; later the owner settings) is a new site's
  zone and the one migration `farm/0030` fills; the server's `TIME_ZONE` stays UTC. The migration test runs on the
  production setting (no override). Fixtures that count on the UTC clock now say `timezone='UTC'`.
- **F2 headcount**: in `hr.rules.status` a clock-in beats leave; whoever clocked in is on Today (planned or not, on leave
  or not), never late on a day of leave.
- **F3/F5 dates**: `core.dates.read_day` is the one day parser: text in ASCII digits, `dd.mm.yyyy` or ISO, inside
  01.01.1900–31.12.2100 (`FIRST`, `LAST`); every list filter says a text it cannot read back and answers (16 pages ×
  extreme dates tested, no 500); `core.dates.install` gives every form date/moment field the shape message, the window and
  a required time; the date box never reinterprets a slash, a dash or a two-digit year. **After fix-monitoring lands, its
  water-history century clamp must use `read_day`'s window.**
- **F4 water status**: a point's status is the worst of its values; an old critical/warning keeps it ("Critical, no
  recent data", `Reading.judged`, `PointWater.old_alert`), never hidden by a fresh OK, never "No limit". fix-monitoring's
  F-244 (`judged`, `old_alert`) overlaps by design: at its landing keep one `judged` field and this status rule.
- **F6 one rule**: a hidden menu line means no access (comments, README, the role matrix's note rows); the walk covers
  every HR route on both mounts.
- **F7**: 403/404 asked by the dialog draw in the dialog's frame (`core.navigation.page_base`).
- **F8**: one label registry (`reports/labels.py`) names every content key the computation writes (an AST test), used by
  the report page, the print page and the differences; numbers in the language's way; notices follow `EVENTS`. The CSV
  export keeps the authority's field names.
- **F9**: only masses take the two-decimal rule; items counted in units show as recorded (`exact`).
- **F12**: the browser layout test lays out what the real templates print (`manage.py layout_pages`, `--check` in the
  suite); markup no longer written by hand. The notice, detail grid, designer and drawer cases are covered by the
  stylesheet rules and template scans only now.
- **Owner: dates shown** dd.mm.yyyy / dd.mm.yyyy HH:MM / dd.mm. in every language from one place,
  `config/formats/european.py`; expectations changed on purpose (golden titles, harvest notes, activity log).

## Still open after the cross-review

- `monitoring.tests.test_golden` fails between about 00:00 and 06:00 UTC on this branch **and on main 16fa1b3 alike**
  (a 30-hour-old sample falls two days back; checked at 01:49 UTC on both). Not caused here; the test should fix its now.
- Landing: `farm/0030_site_timezone_required` depends on 0026; re-point it at main's latest farm migration when
  health-reports has landed, and renumber to follow.

## The second cross-review's findings (R1-R12)

Each written as a test first and seen failing (the `Test:` commits), then fixed in its own commit with its docs.

- **R3/R4 headcount**: an open clock-in counts whatever the punch window (`hr.rules.status`): someone called in hours
  before their shift is present, not upcoming or absent, on leave or not; lateness comes only from the shift's own
  clock-ins. The board's first tile is **On site now** (every open clock-in, planned or not); "Here, not planned" keeps out
  who clocked out (`Board.unplanned_done`). Punches are read from two days back: a clock-in left open longer is not
  counted on site (said in `hr.read.board` and the README).
- **R8 report labels**: `contact`, `escape`, `health_event`, the weekdays and a plain list of units have their words. The
  test computes a report of every kind with every optional part filled, renders its print page and describes every path
  of its content, and fails on a raw key or "(unnamed figure)"; the static net also reads assigned keys. "Cause" is any
  cause (Årsak, Neden); only the mortality form says cause of death (`pgettext_lazy('mortality', 'Cause')`).
- **R1/R2 company zone**: `zone_of(None)` is the company's zone (`core.dates.company_zone`, `company_today`): the clocks,
  an unposted person on Today, HR times with no site, the activity log's days and times, a record's history, the
  messages, the feeding walk's default day, a unit's status time, the monitoring page's time. `core/tests_company_clock.py`
  reads the code: no `settings.TIME_ZONE`, no `localdate()`/`localtime(x)`/`make_aware(x)` without a zone. System check
  `farm.E001` refuses a company zone that is not one a site may have; migration 0030 refuses to write one.
- **R5/R6 one parser**: `core.dates.read_moment` reads the water chart's `?at=` and the replay's `start`/`end` (1900-2100;
  a 400, never an overflow); a replay step longer than any time is a 400 too. A test reads the code: no `strptime`,
  `parse_date`, `fromisoformat` … outside `core/dates.py`. The date filters tried are found by opening every menu page and
  the views it links to (typed date boxes and hidden dates of GET forms), checked to include the 16 the hand list had.
- **R7**: a stock count's unreadable day on a reload is said back and kept in the box, never replaced by today.
- **R10 (item 8)**: `PointWater.alerts` counts an old critical or warning as the point's status does: the monitoring card
  is critical/warning with "…, no recent data", the Production units dot says it in its title and for a screen reader.
  The overview's critical count keeps counting such a point (it holds a critical value). **At fix-monitoring's landing:
  its `_alerts`/`unjudged` replace `PointWater.alerts`; keep this rule (old judgements count) and the card test.**

## The third cross-review's follow-ups (N1-N6)

Each written as a test first and seen failing (the `Test:` commits), then fixed in its own commit with its docs.

- **N1 report values**: a notice's Found at is shown on the site's clock (dd.mm.yyyy HH:MM) on the detail and print pages,
  every date dd.mm.yyyy, a biomass basis and a loss's cause in words (`reports.labels.shown`, the `figure` and `coded`
  filters). The content and the **CSV keep the machine form: an instant as ISO with its UTC offset**, so the file says its
  zone (README). The test reads every value of every kind's detail and print pages.
- **N2 template times**: every time a page shows goes through `|site_clock:site` (alarms on their binding's clock, a
  Mattilsynet notification on its event's site, bindings, tasks, live values, feeding and lice records, a filing on Oslo's
  clock as typed) or `|company_clock` (the activity log, history, messages, the library, user sign-ins, stock and
  inventory recording times, which may span sites). In the tests `|date` and `|time` refuse an aware moment without one
  (`core/clock_guard.py`, `settings.CLOCK_GUARD`): the whole suite is the guard, so a page no test renders is not checked.
  No middleware, no `TIME_ZONE` change (the reviewer's DST and raw-SQL evidence).
- **N3 UTC days**: the clock guard also refuses `date.today()`, `datetime.now()` without a zone, `now().date()`,
  `Trunc*` without `tzinfo` and a `__date` lookup on a moment (it sees the reviewer's bypass probe). The attendance list
  reads a stretch's day on the company's zone (the department move at 00:30 is the new department's); the form and the
  service read the person's site through `hr.read.local_day`. `hr/forms/attendance.py:72` (`naive_in.date()`) is the
  typed wall date, right as it is.
- **N4 periods**: `Period.from_key` reads through `core.dates.read_period` (ASCII digits, a real week or month,
  1900-2100). The one-parser guard also sees a parser reached through `getattr` with its name built from text and a date
  built from `int(...)`/`map(int, ...)`; a parser's name held in a variable is not seen (said in the test).
- **N5 muster**: On site now is every open clock-in on the farm whoever looks (`hr.read.muster`), a number only, by site
  when several; the tile says "Everyone clocked in, all teams". An open clock-in is read whatever its age; one open more
  than 12 hours stays on site, flagged "Open since …: check" on its row and counted on the tile.
- **N6**: migration 0030 holds its own frozen list of zones. `core.dates.on_clock` is the one DST check (the water chart
  and the sensors). Found on the way: the old check compared a time with itself in its own zone, so a skipped spring time
  was refused as "happens twice"; it now reads through UTC and says "does not exist". Still not under it: the moments
  typed on a site's clock elsewhere (a water sample, an attendance stretch, a report's Found at and filing time) are made
  aware with `make_aware`, which takes a skipped or repeated time silently as its first reading. Whether those should
  refuse (an attendance punch at 02:30 on the autumn night is real) is a decision, not done here.

## Still open after the third cross-review

- Template times without a clock: closed by N2 above, with explicit filters and a test guard (no middleware).
- **R9** user-facing translated messages that still show ISO dates (experiments, a feeding form error): deferred.
- **R11** a 403/400/500 in a dialog (two wordings, no 400 template, the 500 document in the dialog): deferred.
- **R12** `monitoring.tests.test_golden` G-03 fails between about 00:00 and 06:00 UTC, here and on main; the
  monitoring branch fixes it.
