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
- Fix: `farm.models.site.ALTITUDE_LOW/HIGH` = 0 .. 5000 m (owner decision 2026-11-06: no site lies below sea level; a
  minus sign is a slip, and 10 m change the pressure by about 0.1 %) as validators and
  `chk_sites_altitude_range`; the calculator's field takes the same range and its offer no longer re-checks it (one
  rule, the database's). Migration 0028 (renumbered: 0027 is another branch's) moves an out-of-range altitude into the site's notes with the day it runs, empties it, logs each change in the activity log, and goes back from that log
  (the pattern of 0023), so the oxygen is worked out at sea-level pressure and says so.
- Tests: `SiteCreateTests.test_the_altitude_is_a_place_where_fish_are_kept`, `SiteAltitudeTests` (database, calculator
  at sea level, the calculator field's range), `AltitudeMigrationTests`.
- The low bound is the owner's (0 m, 2026-11-06); migration 0028 moves negative altitudes into the notes too.
  `chemistry.pressure_atm` itself was not touched (wip/chemcore).

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
- Migration `farm/0028_site_altitude_range` depends on main's 0026; with another branch's 0027 landed first, a merge migration joins the two leaves (coordinator).
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

## Cross review 2026-11-07 (APPROVE WITH FIXES): what was done
- 1 (high) mixed species: `Limits.uncovered` names the species no row judges a value for; `Reading.uncovered` carries
  them and `PointWater.unjudged` is every value with any; a cage with salmon judged and lumpfish without a row is
  "No limit". Tests: `WaterLimitsOfEveryFishTests` (farm, sea cage), `CleanerFishTests.test_a_cage_with_salmon_and_lumpfish_...`.
- 2 oxygen: owner rule, dissolved oxygen is one quantity. `Context.judge` works an oxygen value out in the other unit
  (`_in_other_unit`: its own observation's other value, else `_oxygen` with its own or the point's fresh temperature,
  the salinity and the site's pressure: the existing solubility, no second formula) and judges it by that unit's row;
  what cannot be worked out stays uncovered ("No limit"). The pair excuse in `unjudged` is gone. Tests:
  `NoLimitTests.test_oxygen_in_two_observations_is_judged_each_by_its_own_unit` (the reviewer's 8.5 mg/L + 35 %),
  `test_a_probes_saturation_is_judged_against_the_mg_l_limit_through_the_solubility` (35 % at 9 °C: critical).
  The golden cards now say the worked-out % with its judgement ("Oxygen saturation: Critical" beside the mg/L);
  no card changed state.
- 3 history dates: `_day` holds a day to the last century up to today (`OLDEST_DAYS`); tested with 9999-12-31 and
  0001-01-01.
- 4 golden ages: the Normaliser marks ages under an hour as `<recent>`; re-recorded; `NormaliserTests`.
- 5/6 migration: renumbered 0028 (depends on main's 0026 and core 0007); the note says the day it runs; one
  activity-log row per changed site ("system", altitude and notes before and after); going back restores from those
  rows. Tests: `AltitudeMigrationTests` (two).
- 7 `PointWater.alerts` removed (no caller). The announcer reads the order of the states from the page
  (`data-states`, from `read.STATES`) and says an old critical card falling to "No recent data"; tested in
  `AnnouncerTests` and announce.test.ts.
- Owner rule (2026-11-07) oxygen entry: the record form offers the point's latest fresh temperature and salinity
  (with origin and age), stores them with the oxygen, needs them where there is none, does not store an untouched offer
  without oxygen; a worked-out oxygen says "Worked out from T, S and P" on the water page and the card. The water round
  follows the same rule (`OxygenInputs`, shared, not copied; an oxygen column brings the temperature and salinity
  columns; one read for every row). Note: an offer typed back unchanged without oxygen cannot be told from an untouched
  one and is not stored. Tests: `PageTests.test_an_oxygen_entry_...` (two),
  `test_the_worked_out_oxygen_says_what_it_was_worked_out_from`, `test_a_worked_out_oxygen_says_on_the_card_...`.
- Owner rule A9 (2026-11-07) in the one resolver: the newest of the unit's own fresh values wins whatever the origin,
  the sensor channels too (`read.newest`; the primary before the backup only at one measurement time, owner follow-up);
  the system (its sensor or a loop sample) stands in only when the unit has nothing fresh; stale is shown, never used.
  It supersedes the owner's 2026-11-04 rule that the chart never takes the loop's temperature; four old tests were
  changed to A9 in `Test:` commits. Tests: `NewestOwnValueTests` (five).

## Verification after the cross review, A9 and the oxygen entry (main 912c55d merged, e6f3e25)
- Fresh `test_fixmon`, no --parallel: monitoring, farm water / sources / points / calculator / deffeyes / cleaner fish /
  sites / both migrations / feeding / health, sensors, core: 1230 tests, 8 errors, all `core.test_database`: its
  fixtures used altitude -5.50 and -7.00, which the owner's 0 .. 5000 m now refuses; they take a negative longitude
  instead (44556fa) and the module reruns green (58 tests).
- `makemigrations --check`: no changes; `data_map --check`: up to date; `compile_catalogs`: tr and nb, nothing
  missing; tsc clean; the node tests 48 pass, 0 skipped. The main repo's `node_modules/typescript/bin` is empty after
  the move to F:, so `npm test` cannot find `tsc`; the same steps were run through `node_modules/typescript/lib/tsc.js`.
- Open: the farm migration 0028 needs a merge migration with another branch's 0027 at landing.

## Follow-ups (2026-11-07/08): A9 always the newest, the round's oxygen inputs
- `read.newest`: among a point's own fresh sensor channels the newest reading wins; the primary before the backup only
  at one measurement time (latest values and a value at a moment). Test: `OrderTests.test_the_newest_fresh_channel_wins_and_the_primary_only_at_the_same_time`.
- The water round uses the sample form's rule (`forms.water.OxygenInputs`, shared mixin): an oxygen column brings the
  temperature and salinity columns, each row offered its point's latest fresh values (one read of every row's water),
  stored with the oxygen, needed where there is none, an untouched offer alone is no sample. Test:
  `PageTests.test_a_round_with_oxygen_offers_and_stores_temperature_and_salinity_as_the_sample_form_does`.
- Full suite, fresh `test_fixmon`, no --parallel, on 440a13f (main 912c55d merged; main has not moved since):
  2868 tests OK (3 skipped). `makemigrations --check` no changes; `compile_catalogs` built, nothing missing; the data map
  was regenerated afterwards (a6dbf4f: the round's hidden offer fields) and is up to date; `npm test` from
  F:/dev/balik-ciftligi's node_modules: 48 pass, 0 skipped.

## Second cross review (2026-11-08, CHANGES REQUIRED): what was done

Test first throughout: each fix has its `Test:` commit before it.

- **1 (high) oxygen entry provenance**: what an oxygen is worked out with is stored as `oxygen_basis_*` (value, source,
  channel, time; migration 0029, checks), found by the server at the sample's own point and time (`read.oxygen_basis`),
  never as a measurement; the forms leave T and S empty (P3, P4, P5 tests; P6: a typed value alone is stored).
- **2 (high, owner decision 2026-11-08)**: the worst fresh value decides the status (`read.worst_fresh`), the shown
  value stays A9's choice and the reading says which value decided it.
- **A9.1 (owner decision 2026-11-08)**: a unit's own points are those measuring its own water (`read.OWN_WATER_KINDS`:
  middle, depth, outlets, drain); an inlet (supply stream) never counts for the unit's value or status.
- **3 (medium) stale never calculates**: salinity fresh at the value's time (7 days), conversion only with a temperature
  fresh at the value's own time (`read.fresh_at`, P8), stale sensor TAN says so.
- **4 (medium) one resolver**: `read.choose` is A9 for `latest`, `Series.latest` and the ration's temperature; a probe on
  the loop point stands in (P1); one tie-breaker; a value standing in is judged for the unit's fish only; each place's
  readings are judged on their own copy.
- **5 (medium)**: a % judged against an mg/L limit says the value it was judged as, its inputs and the limit
  (`Reading.through`).
- **7 (low)**: migration 0028 going back skips a site corrected since. **8 (low)**: future-stamped values beyond 5 min are
  never fresh (P7, `evaluate.CLOCK_SKEW`); the round no longer carries hidden offers; one assumed-salinity read per round.
  **10**: golden cards on a pinned clock, recorded again (only the new notes changed).
- **Not done here**: the migration chain (6) is re-pointed at landing; the Deffeyes replay and the trail
  (`sensors/read.deffeyes_frames`, `sensors/trail.py`) were moved to `read.choose` per frame in the follow-ups.

## Owner follow-ups (2026-11-08)

- **A11** (the one explicit exception to A9.3): the ration takes the newest temperature however old; a stale one is shown
  with "Based on the temperature from dd.mm.yyyy HH:MM (N days old)" (`feeding.temperature.Temperature.warning`, the meal
  board); `TEMPERATURE_USABLE_DAYS` is gone; the samples before the read range are found by `Series(carry=True)`.
- **Withdrawal degree-days**: per day the lowest daily mean of the unit's own-water points (never the inlet), else the
  loop (`water/degree_days.Temperatures.of`, `water_sources(every_point=True)`). **To reconcile at the merge with
  wip/fix-health-reports**: its withdrawal guard's coverage test registers what the withdrawal readers read; this
  branch makes `Temperatures` read the unit's other own-water points too.
- A "Judged as" note only where a conversion was made; a system without a loop point stands in for the ration through
  its own sensors, as on the water page (`Series(systems=...)`, `read.SYSTEM_KEY`).
