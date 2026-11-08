# Review notes: wip/fix-integrity

Branch from main b24de24. Area: farm structure and stock ledger, core crud/softdelete/restore/audit mechanics, tasks,
experiments, messaging/knowledge, plus the query-parameter 500s. Every behaviour change has a `Test:` commit before
its fix commit (the test was run and seen failing for the reason named; the run output is not committed).

## Fixed

### F-212, F-020, F-191, F-114: a site deleted from under live units
- Root cause: `ProductionDepartment.site` was `SET_NULL` (ported from the source), so deleting a site whose units had
  no stock records left departments, and their live units, on no site. Those units still took fish and feed; a site's
  reports and the feed book reach fish only through the site, so the fish and feed fell out of both.
- Fix (model, database, write path):
  - `Site.delete_blockers`: a site with live units is not deleted (`N units still belong to it.`).
  - `ProductionDepartment.site` is `CASCADE`: a site's (empty) departments go with it, as its systems do; their
    equipment goes with them (HR postings `PROTECT` them, so a department with people blocks the site's delete).
  - Database check `chk_production_departments_live_on_a_site` (`site_id IS NOT NULL OR is_deleted`), added
    `NOT VALID` in farm 0029 (SeparateDatabaseAndState): existing rows a deleted site left without a site stay as they
    are, every new or changed row must have a site. No data is invented. `check_stock` names the legacy rows; when it
    names none, `VALIDATE CONSTRAINT` can be run (documented in the migration and README).
  - Legacy departments can be put on a site again (F-114): the department form opens its site again (required) for a
    department that has none (a first, generic "unfix an empty field" rule broke the sampling point's owner fields and
    was replaced); `ProductionDepartment.clean` allows that re-attach
    whatever the units' stock records (on no site they are in no report at all). **Decision for the reviewer/owner**:
    re-attaching a department whose units have history to a *different* site than the deleted one moves their past
    figures there; the preferred path is restoring the old site and choosing it.
  - One predicate for "takes fish": `farm.models.stock.TAKES_FISH` / `takes_fish()` (status and on a site), used by
    the stocking form's list and the page's buttons; the write path (`_check_static`) refuses an arrival into a unit
    without a site with its own message. A new unit, or a unit moved, goes only into a department on a site
    (`Tank._check_department`, same message as equipment).
  - `check_stock` reports fish in a unit without a site and every live department without a site.
- Tests: `farm.tests.test_site_structure` (all), updated: `test_delete_plan` (SET_NULL example now a department's
  systems), `test_systems`, `test_tanks`, `test_equipment`, `test_production_departments`, tasks/hr fixtures use
  `farm.tests.helpers.leave_without_site` to make a legacy row.
- F-191/F-020 (`inventory/read.py` filters `site__isnull=False`) is left as is: with the invariant there is no siteless
  feeding left to draw, and legacy rows are named by `check_stock`.

### F-166, F-112: maintenance with fish had no way out
- Root cause: the ported status machine has MAINTENANCE -> (PREPARING, INACTIVE), both needing an empty unit.
- Fix: MAINTENANCE -> ACTIVE added to `TRANSITIONS`; `status_blocker` already requires fish for ACTIVE, so the fish
  decide the way out. Arrivals into maintenance stay refused (by design). Docs: README, owner-questions list.
- Tests: `test_tanks.StockGuardTests.test_a_unit_in_maintenance_with_fish_goes_back_to_active`, updated
  `test_the_statuses_that_need_fish_and_those_that_need_none`.

### F-024: roster batch CLEAR crashed on a mixed selection
- Root cause: "nothing to clear" was decided per person, not per cell; an empty cell reached `_write_cell(row=None)`.
- Fix: `plan_shifts` keeps only the filled cells of a CLEAR batch before ruling and writing.
- Test: `hr.tests.test_roster...test_clearing_a_selection_with_empty_cells_clears_the_filled_ones_and_logs_only_them`.

### F-006, F-176, F-120 (+ reports year, HR page numbers): 500s on malformed query values
- Root cause: seven copies of a day parser, `parse_date` (raises on 2026-13-45), `str.isdigit()` + `int()` (² passes
  isdigit), unbounded numbers (bigint overflow) and unbounded dates (date arithmetic overflow at 9999-12-31).
- Fix: `core/query.py` (`day`, `number`, `year`), one rule: well formed and in range, else not given. Every copy
  replaced (core activity log, feeding, harvest, health, harvest plans, inventory, water history, HR roster, overview
  and attendance, messages before/after, reports duty year).
- Tests: `core.tests_query` (parser), `core.tests_query_pages` (walks every route without arguments plus the pages
  that read a message number, a year or a place, with three sets of malformed values; any exception or 5xx fails).
- Overlap: `reports/views.py` (duty_done year) is in the reports area (wip/fix-health-reports) - a one-line change.
  `sensors/views.py` deffeyes `int(step)`/`timedelta` can still overflow (huge `step`) - left to wip/fix-monitoring.

### F-110: a channel its last member left stayed live
- Fix: `messaging.services._remove` soft-deletes the channel when no live member remains (logged as a channel's
  delete; messages kept for a restore; the name is free again).
- Test: `messaging.tests.test_services...test_a_channel_its_last_member_leaves_is_deleted_and_frees_its_name`.

### F-029, F-067, F-003, F-065, F-079, F-190: restore and the delete plan's writes
- Root cause: restore brought back only the record (so a recurring task's planned tasks, deleted with it but still
  holding their days, were never made again: F-029); restore was unlocked and a DB-only clash was a 500 (F-003); the
  plan full-saved unlocked children (overwriting a concurrent edit: F-065/F-079/F-190).
- Fix: `softdelete.execute` stamps every record of one delete with one moment (`AuditedModel.mark_deleted`, which
  writes only the deletion's columns with `version = version + 1` in SQL; `detach` likewise). `restore` locks the
  record, refuses one already live, collects what the same delete took along (`taken_with`: records pointing at it,
  deleted at the same moment, recursively), checks the deleted targets outside that set, validates uniqueness and
  constraints, saves, then runs the models' own `clean()` with everything live; all inside one atomic block. A
  DB-only clash becomes the constraint's message (`core.models.violated_constraint`, now also used by the forms'
  `constraint_error`).
- Not fixed: F-036 (a SET_NULL detach is not re-linked on restore: the old pk is not kept anywhere; documented).
  Deletes made before this change carry per-record moments, so restoring one of those still brings back the record
  alone (documented).
- Tests: `farm.tests.test_restore` (four new), `test_equipment...restoring_it_brings_them_back`,
  `tasks.tests.test_series...test_restoring_a_deleted_recurring_task_brings_back_its_planned_tasks`; experiments
  `test_a_restored_draft_comes_back_with_its_design` (was pinning the old behaviour).
- Overlap: `monitoring/screens.py` note text (restoring a card template now brings its rules back) - wip/fix-monitoring.

### F-009, F-034: an edit's lock and a DB-only clash on an edit
- Root cause: `UpdateView`/`RowListView` locked with `.get(pk)` (DoesNotExist -> 500 when the record was deleted
  between the check and the save); `UpdateView` did not catch the IntegrityError `CreateView` catches.
- Fix: `ResourceView.locked_object` (404) used by update, row list and delete; the edit's save runs in a savepoint and
  a named constraint's refusal is put on the form (`constraint_error`, which no longer flips `_state.adding`; the
  create path sets it itself).
- Tests: `farm.tests.test_sites.SiteEditTests.test_a_site_deleted_while_it_was_saved_is_not_found`,
  `...test_a_clash_only_the_database_catches_is_told_on_the_edit_form`.

### F-232: double submit duplicated records without an entry_key column
- Root cause: the generic create path guarded only models that declared `entry_key` (tasks, leave, attendance).
- Fix: one register for every kind of record, `core.models.EntryKey` (`entry_keys`, key = PK, so two sendings at once
  serialise on the insert). Every `TabbedForm` new-record form carries the key; `CreateView` writes it in the
  creating transaction (`note_sent`) and `sent_before` reads it. The per-model columns of tasks (Task, TaskSeries)
  and HR (AttendanceRecord, LeaveRequest) are copied into the register by their migrations and dropped (no duplicate
  mechanism). Write paths of their own (stock, feeding, health, inventory, water, experiment copy) keep their keys.
- Tests: `core.tests_entry_key` (every tab's create form has the key; a health event sent twice is created once),
  updated `tasks.tests.test_pages`, `hr.tests.test_attendance/test_leave` (column lists).
- Not done: the frontend submit lock (UX only; the server guard is the real one); no browser test infrastructure runs
  here (Playwright tests skip, F-127).
- Migrations: see F10 below (on main's leaves after the merge of c6ae1f7).

## Checks run (final, after merging main 6bf9a78)
- Full Docker suite (image balik-testrunner, test_fixint fresh, no --parallel) at ff923c5: 2784 tests, 1 failure, the
  stale data map only; regenerated in b1e14b7, then core.test_datamap + core.test_catalogs: 36 OK, data_map --check up
  to date. (The run before, at a232036, found 5 tests pinning the old rules; fixed in ff923c5.)
- `makemigrations --check`: no changes. `data_map --check`: up to date. `compile_catalogs`: built tr, nb.
- `npx tsc -p tsconfig.json --noEmit`: OK. `npm test`: 40 pass.

## Not fixed in this branch (and why)
- F-104 (experiment-written feeding assignments editable from the farm): needs a farm-side guard that knows about
  experiments without farm importing experiments (a holder registry); designed, not built for time. Detection stays
  with `check_experiments`.
- F-094, F-102, F-022, F-123, F-125, F-219, F-217, F-019, F-027 (whole-history folds, uncached due lists): performance
  that grows with history; a read-model/cache is an architecture decision (F-240), not a patch.
- F-036 (SET_NULL not re-linked on restore): the old link is not stored anywhere; would need a pk in the audit row.
- F-201, F-202, F-215, F-002, F-064 (tasks materialise on GET, unlocked withdraw): not reached.
- F-113, F-115, F-228 (System.site fixed only in form; site/department status not enforced on operations): owner
  semantics for "closed site"/"inactive department" are not decided; F-228 partly covered (a unit takes fish only on
  a site).
- F-008, F-015, F-105, F-106, F-108, F-209, F-214 (knowledge), F-207, F-208, F-168 (experiments), F-210, F-211, F-213,
  F-093, F-199, F-200, F-087, F-192, F-193, F-032, F-181, F-050, F-061, F-066, F-068, F-071, F-072, F-237 (audit
  values), F-221 (modal drops the submitter: frontend, experiments Randomise/Add factor): not reached in this round.
- Sensors deffeyes `?step=` with a huge value still overflows `timedelta` (sensors belongs to wip/fix-monitoring).

## Overlap with other branches
- wip/bugs-nov5 (design walk): no shared change found; `reports/views.py` (duty year) and the reports' text are
  theirs/health-reports' area - one-line change here.
- wip/fix-monitoring: `monitoring/screens.py` note text only.
- wip/fix-security / wip/owner-settings: hr migration 0009 and hr model fields (entry_key dropped); core migration 0008.

## Cross review round (audit-verify/REVIEW-CROSS-integrity.md), main 16fa1b3 merged

Each item: `Test:` commit first (seen failing), then the fix commit.

- **F1 (HIGH)** "On a site" = live unit, live department, live site. One predicate `farm.models.tank.ON_A_SITE` /
  `on_a_site` used by `TAKES_FISH`/`takes_fish`, `_check_static` (stock write path), `Tank._check_department` (unit
  create/move) and the tank form's department list. Farm 0030: three constraint triggers (`trg_units_on_a_live_site`,
  `trg_departments_on_a_live_site`, `trg_sites_without_live_departments`) hold it in the database as far as a row's
  write can be checked; `CreateView` now shows a trigger refusal on the form (as `UpdateView` did after main's change).
  `Tank.save` locks the site, then the department (the order a site delete takes them). `check_stock` names live units
  in deleted departments and live departments on deleted sites. Legacy siteless departments stay the NOT VALID
  check's matter (the triggers let them be, so their fish can still be moved out). Tests:
  `farm.tests.test_site_structure.LiveSiteTests`. Tests that deleted a site/department over live children were changed
  to delete the children first (core.test_database, farm test_tanks, test_systems, sensors test_portable).
- **F2** `softdelete.execute` locks the records the plan takes along or detaches and re-checks each under the lock: it
  must still hang by its link on something the delete takes and be live; one moved meanwhile stays (with what hangs
  under it), one deleted on its own keeps its own moment. Tests: `farm.tests.test_delete_plan.StalePlanTests`.
- **F4 (owner rule)** Re-siting a legacy department: no stock history -> any live site; with history -> only the
  site they were recorded on (`ProductionDepartment.former_site`, read from the source delete's log row, matched by
  label, restored first); unknown -> refused with the reason. Tests: `ResitingTests`. Translations TR/NB added.
- **F5** The channel and its last membership are deleted at one moment (`mark_deleted`), so a restore brings both.
  Test: `messaging...test_a_channel_its_last_member_left_comes_back_with_that_member`.
- **F7** One key mechanism: the seven remaining per-model `entry_key` columns (StockOperation, FeedingRecord,
  Treatment, LiceCount, InventoryOperation, WaterMeasurement, Experiment) are copied into `EntryKey` and dropped
  (farm 0031, inventory 0002, experiments 0003); their services use `EntryKey.record_of/note`. The feeding-assignment
  and Move dialogs look the key up first and note it. The generic create path now reads the key from the posted data
  *before* validating (a second sending of a record with a unique code was told "code taken"). Tests:
  `core.tests_entry_key.WritePathKeyTests`, `SentBeforeValidationTests`, the dialog tests in test_protocols /
  sensors test_bindings (each posts twice and checks one record and the same landing).
- **F9 (partly)** The DB viewer's page number goes through `query.number`. Test in `core.tests_query_pages`.

### Waiting / not done in this round
- **F8** (done after main c6ae1f7 was merged): every day, moment and period is `core.dates.read_day` / `read_moment` /
  `read_period` (main's side taken in the merge for every caller); `core.query` keeps `number` and `year`, the year on
  `core.dates`' calendar; `core.tests_query_pages` has a dd.mm.yyyy row. Tests: `core.tests_query`.
- **F10** (done at the merge of main c6ae1f7): each app's migrations sit on main's latest, one leaf per app: core
  0008_entry_keys (after 0007), farm 0029-0031 (after 0028_site_timezone_required), hr 0009, tasks 0002, inventory
  0002, experiments 0003.
- **F7c** (LOW): fixed after the round: `EntryKey.note` refuses a key that stands for a record of another kind with a
  form error (new-record form, assignment dialog, write paths). Tests: `core.tests_entry_key.KeyOfAnotherRecordTests`.
- **F6** weak spots (timestamp equality as "same delete", whole-restore refusal not naming the record): documented,
  not changed.
- `monitoring.tests.test_golden` fails 6 subtests on main too (clock-dependent "Stale · <day-1>" around 01:00 UTC);
  not this branch's.

## Merge review (audit-verify/REVIEW-CROSS-merge-integrity.md): LAND WITH FOLLOW-UPS, followed up

- **Finding 1 (MEDIUM) lock-order deadlock** between a department delete (department, then its units) and a unit save
  (unit, then site and department). One lock order now, written once in `core/softdelete.py` (LOCK ORDER): the fish
  first (batches, then units: stock operations, the withdrawal guard's `lock_fish`), then the place going up (production
  departments, then sites: `Tank._lock_place`, which now locks the department before the site). A delete locks what it
  takes along the deepest first and the record last (`softdelete.lock_along`, called by the delete view before it
  locks the record; `execute` again); a restore collects unlocked and locks the deepest first, then saves parents first.
  Health's guard locks the fish first, which is the start of the same order. Backstop:
  `core.middleware.CrossedWritesMiddleware` turns a deadlock (40P01) or serialization failure (40001) on a POST into
  "Someone else saved at the same moment: nothing was saved. Send it again." on the page it was sent from. Tests:
  `farm.tests.test_lock_order.LockOrderTests` (two real transactions on two connections; it deadlocked before the fix)
  and `CrossedWritesTests`.
- **Finding 2 (LOW) experiment copy sent twice at once**: `experiments.services.copy` locks the source before it looks
  the key up, as every keyed write path does. Test: `experiments.tests.test_amend.CopyRaceTests` (two threads; the
  second failed on the key before the fix).
- **Finding 3 (INFO) migration reverse**: the reverse of the entry-key migrations (farm 0031, tasks 0002, hr 0009,
  inventory 0002, experiments 0003) is a no-op for the data: rolling back re-adds the 11 `entry_key` columns empty and
  does not copy the keys back from `entry_keys`. The only effect is that a form opened before the rollback and sent
  after it is not recognised as sent before; no record is touched.
