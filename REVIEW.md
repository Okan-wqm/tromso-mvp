# Review notes: wip/fix-monitoring

The verified audit findings (scratchpad/audit-verify, against main b24de24) whose code is in `monitoring/`, `farm/water/`,
`sensors/` (bindings and devices excepted), the card templates and the Deffeyes code. Each finding: its root cause, the
fix, the tests that pin it, and what was left and why. Every behaviour was written as a test first and seen failing for
the right reason (the `Test:` commits), then fixed in its own commit.

## Package A: monitoring never shows danger or the unknown as OK

### F-090 a stocked unit with no limit stays "OK" (high)
- Root cause: `evaluate.Limits.assess` says `NO_LIMIT` when no row judges a value, and `monitoring.read.state_of` only
  looked at `PointWater.alerts` (critical and warning), so a value nobody judges fell through to OK. Limits are not seeded
  (WQ-24, by design), so a fresh farm showed every card green at any value.
- Fix: `PointWater.unjudged` (farm/water/read.py, the owner of judging) lists the values no row judges for the fish;
  the oxygen in mg/L and in % is one quantity (`parameters.SAME_QUANTITY`), judged when either has a row and named
  once when neither has. `state_of` has a new rung `unjudged`, word "No limit", below "No recent data" and above a note,
  in the strip and the announcer. `water.read.missing_limits()` lists, per species and water type kept today (deleted
  species included: nothing judges their fish), the parameters with no row; Reference data › Water limits shows it as
  "Fish with no limit". The state words are one list (`read.STATES`) the card, the strip, the announcer and the
  designer's "show as" read.
- Tests: `LadderTests.test_a_value_the_fish_have_no_limit_for_is_never_ok`,
  `test_the_oxygen_is_judged_when_one_of_its_two_units_has_a_limit`, `test_no_limit_ranks_below_no_recent_data_and_the_strip_names_it`,
  `test_every_state_has_one_word`; `CardsTests.test_a_stocked_unit_whose_fish_have_no_limit_is_not_ok_and_an_old_critical_value_stays_critical`;
  `farm LatestTests.test_the_values_the_fish_have_no_limit_for_and_the_oxygen_is_one_quantity_in_two_units`;
  `LimitTests.test_the_list_names_the_parameters_the_fish_kept_today_have_no_limit_for`; golden G-17 and
  `test_the_farm_has_every_state_a_card_can_be_in`.
- Decision taken (reviewer, please check): every limitable parameter counts, salinity and turbidity too; a farm that
  does not want to judge one sets a wide limit. The rung sits below "No recent data". If the owner wants a narrower set,
  that is a list in `parameters`, not a code change.

### F-244 a stale critical value drops the alarm; critical -> blind not announced (high)
- Root cause: `Context.judge` overwrote the status with `STALE` and forgot the judgement, so an eight-day-old critical
  nitrite left `alerts` and the card went OK while oxygen and temperature were fresh.
- Fix: `Reading.judged` keeps what the limits said whatever the age; `status` still says stale for the pages. `state_of`
  reads the judgement: an old critical or warning value keeps its rung and says "Critical, no recent data, 1 week old";
  `State.stale` marks it and the article carries `data-stale`. `Reading.old_alert` makes the value widgets and the water
  pages (`farm/_water_value.html`, `wq-was-critical`) show it as old and as what it was. The announcer
  (frontend/announce.ts) says a card whose data became old and a card that falls to "No recent data" from any state.
- Tests: `LadderTests.test_a_stale_critical_value_keeps_the_card_critical_and_says_it_is_old`, `..._warning_...`,
  `test_a_fresh_critical_value_is_not_marked_old_beside_a_stale_one`; farm `test_a_stale_value_keeps_what_its_limit_said_beside_its_age`,
  `PageTests.test_an_old_critical_value_is_shown_as_old_and_as_what_its_limit_said`; `FaceTests.test_an_old_critical_value_still_says_critical_and_old_and_an_old_fine_one_only_old`;
  `PageTests.test_a_card_with_an_old_critical_value_is_marked_old_for_the_announcer`; announce.test.ts "a card that loses
  sight of its water is said ..." and "an old critical card is said ...".

### F-025 required-source failure swallowed, not logged (high)
- Root cause: `cards()` wrapped the required reads in one `except Exception: raise Unavailable` with no log.
- Fix: `_required(name, loader)` logs the source's name and trace (`logger.exception`) at most once a minute per source
  (`_log_failure`, shared with the optional sources) and raises `Unavailable`. The grid's stale notice now says "Not
  updated: the server cannot be reached or cannot read the cards" (it said "No connection" for a server error too).
- Tests: `FragmentTests.test_a_source_the_state_needs_that_fails_is_logged_with_its_name_and_cause_once_a_minute`.

### F-088 bar all "critical" when the low bounds are open (medium)
- Root cause: `render.bar` walked a fixed band order, so an open lower bound made the whole bar critical.
- Fix: each stretch between bounds is what `evaluate.judge` (the one rule) says of its middle; no second rule.
- Tests: `BarTests` (four tests).

### F-134 sources fail to stderr only (medium, partly deploy)
- Fix here: an optional source that fails is said on the card's frame ("Could not be read: Sea-lice counts, Tasks"),
  where no template can hide it; failed live sensors make the card "No recent data" with "Live sensor values could not
  be read: samples only." (before only the detailed water widget said it). Both are logged with name and trace.
- Tests: `test_a_failed_source_is_said_on_the_frame_whatever_the_template_shows`, `test_live_sensors_that_could_not_be_read_are_never_ok`.
- Not fixed: a `LOGGING` configuration, error tracking and paging (Package H, F-043, with the dedicated server), and the
  alarm delivery (owner answer: push alarms with an outbox, being built in another branch). The log lines are ready for
  both.

### F-045 / F-222 stale and gone wall notice CSS-only (low)
- Fix: announce.ts watches the grid's `data-poll-state` and says the page's own words (stale, gone, updated again) in
  the assertive region.
- Tests: announce.test.ts "the grid says aloud ..." (`pollNotice`), announce.browser.test.ts (a stub that answers 503).

## Package B

### F-089 Site.altitude unbounded (high)
- Root cause: no range on the model or the database; the calculator had its own 0..5000.
- Fix: `farm.models.site.ALTITUDE_LOW/HIGH` = -500 .. 5000 m (Dead Sea shore to the highest farms) as validators and
  `chk_sites_altitude_range`; the calculator's field takes the same range and its offer no longer re-checks it (one
  rule, the database's). Migration 0027 moves an out-of-range altitude into the site's notes with the day and empties it
  (the pattern of 0023), so the oxygen is worked out at sea-level pressure and says so.
- Tests: `SiteCreateTests.test_the_altitude_is_a_place_where_fish_are_kept`, `SiteAltitudeTests` (database, calculator
  below sea level), `AltitudeMigrationTests`.
- Owner decision to confirm: the low bound -500 m. `chemistry.pressure_atm` itself was not touched (wip/chemcore).

## Other findings in the area

| Finding | Fix | Tests |
|---|---|---|
| F-176 / F-019 water history 500 on a bad date, unbounded and judged before paging | `_day` returns the default for a day that is no day; a span over 366 days starts later and says so (the feeding page's own message); samples paged in the database and only the page judged (alerts-only still judges the span, as the alert is worked out on read); `services.earliest` once per point (was `setdefault`, evaluated per row) | `PageTests.test_a_date_that_is_no_date_is_the_default_never_a_server_error`, `test_the_history_spans_at_most_a_year_and_judges_only_the_page_it_shows` |
| F-149 "undefined removed." | the designer finds a removed widget in the layout before the change | designer.browser.test.ts "a removed widget is said by its name ..." |
| F-122 / F-151 preview errors silent, network errors thrown | a refused or failed preview is said in the pane (`role="alert"`), never thrown | designer.browser.test.ts "a preview the server refuses ..." |
| F-127 Playwright tests skip silently | `frontend/test/browsers.ts`: one skip rule, never skipped under `CI=1` | browsers.test.ts |
| F-152 water_void duplicates stock_void | water_void extends stock_void and fills its `entry` block | existing void tests |
| F-074 migration imports live app code (farm/water/points.py) | 0019 has its own frozen copy of the template | `FrozenTemplateTests` |
| F-160 Turkish `.lower()` | `core/text.lower` lowers by the language; the water limit text and the bar's sentence use it | `core/test_text.py` |
| F-136 / F-138 / F-142 README tables | code layout rows for hr, monitoring, sensors, sensors-ingest, core/checks, ranges, text; the database viewer's app list; the Monitoring boards page | docs |

## Not fixed, and why

- F-026 (the wall re-folds all stock and feeding history each refresh, medium): a performance design change (bounding
  the feeding walk or caching the rendered card, README "Measured at 100 units"); needs a measurement on the live farm
  first. No wrong figure today.
- F-119 / F-116 (monitoring imports other apps' views; package cycles in farm, low): layering smells with no defect;
  moving the permission names out of the views touches every module and other branches.
- F-183 (change token depends on the audit log, partly): bounded to a minute by the token's minute bucket; sensors have
  their own epoch. By design.
- F-184 (btree_gist ownership split, sensors migration) and F-187 (retention of water_measurements, partly deploy):
  migration ordering and capacity planning for the dedicated server (Package H).
- F-224 (void dialogs do not say "cannot be undone", partly): copy polish over several modules (health, lice, stock);
  water's dialog says how to correct, as the others do.
- F-160 in other areas: `tasks/services.py`, `inventory/`, `farm/models/tank.py`, `farm/feeding/services.py`,
  `farm/health/withdrawal.py` and the templates' `|lower` (stock_void, inventory void, unit drawer) still lower with
  Python's rule; they belong to other branches and can use `core.text.lower` (a template filter would close the
  templates).
- F-240, F-140: documentation wording, no defect.

## Notes for the reviewer
- New migration `farm/0027_site_altitude_range` may need renumbering when other branches add farm migrations.
- `water.read` judges with `Reading.judged`; `status` keeps its old meaning, so every other page is unchanged.
- The golden cards were re-recorded (GOLDEN_WRITE=1): the states of every old card are unchanged; G-17 is new ("No
  limit"), limits for pH and CO₂ were added to the golden farm so its cards stay judged, and the recording now holds the
  texts the templates added since it was first made.
- The designer's `data-label-preview-failed` landed in the Package A commit with the state words (same template).

## Verification (main b24de24 has not moved, so there was nothing to merge)
- Full Docker suite (fresh `test_fixmon`, no --parallel): 2772 tests, 1 failure, 3 skipped: the frontend contract test
  caught the grid's new `data-live-text` (the `data-live-*` names are poll.ts's live forms). Renamed to
  `data-updated-text`; `core.test_frontend_contract` and the announcer tests rerun green.
- `makemigrations --check`: no changes; `data_map --check` after regenerating: clean; `compile_catalogs`: tr and nb
  built, no untranslated message; `npx tsc --noEmit`: clean; `npm test`: 46 pass, 0 skipped (Chrome present).
- `--keepdb` runs are not trustworthy here after migration tests (TransactionTestCase) on a kept database: built-in card
  templates went missing and monitoring tests failed; a fresh database passes. Use a fresh test database for this
  branch.
