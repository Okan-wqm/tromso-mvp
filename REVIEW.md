# Review notes: wip/fix-health-reports

Branch from main b24de24; main 6bf9a78 (organization chart) merged in 0868d4f. Area: farm/health (treatments,
withdrawal, lice), handling/withdrawal checks, harvest and harvest plans, feeding, reports/. Every behaviour is test
first: a `Test:` commit (seen failing for the right reason), then the fix commit with its README/docs lines. The
cross-review (REVIEW-CROSS.md, APPROVE WITH FIXES) is answered in its own section below.

## Owner hook (second person's approval)

`farm.handling.check.second_person_must_approve(user, kinds, record)` is THE one hook for the platform owner's setting
"a second person approves a withdrawal acknowledgement" (owner answer 2026-11-06, F-164): `user` is the person going on,
`kinds` the withdrawal warnings gone past (`WITHDRAWAL_WARNINGS`: `withdrawal` before a harvest, the guard's `harvested`
and `released`), `record` what is acknowledged (the assessment or the withdrawal change: warnings, messages,
fingerprint). It is consulted in one place, `check.require_acknowledged`, which every acknowledging path reaches: the
handling dialogs (harvest, transfer, grading, treatment), the experiment start, and the withdrawal guard (every write
that changes a withdrawal). It returns False now; True refuses the save ("A second person must approve ... cannot be
given here yet": fail closed until the approval flow exists). For wip/owner-settings: make the function read the setting
and build the approval flow. Test:
`SecondPersonHookTests.test_the_platform_owners_setting_is_asked_in_one_place_before_a_withdrawal_is_gone_past`.

## The withdrawal guard (F-195, F-188, F-196; cross-reviews 1 and 2)

ONE function, `farm.health.withdrawal.guarded(user, batch_ids, today, write, *, seen, ...)`, is the gate of every write
that can create, grow, shorten or end a withdrawal: `record_treatment`, `change_last_day`, `void_treatment`,
`record_feeding`, `void_feeding`, water `record` / `record_round` / `void`, stock `_commit` (every stock operation) and
`void`, the medicine's rows (`MedicineWithdrawalList.save`), and on their Setup pages a feed's type, a species' assumed
temperature and a sampling point's active flag, kind and owner (`Resource.edited`, a hook of `core.crud.UpdateView`).

- **Data-layer enforcement (cross-review 2, items 2 and 3).** `farm/withdrawal_gate.py` registers the inputs (Treatment,
  FeedingRecord, WaterMeasurement, MedicineWithdrawal, StockOperation, StockMovement: every write; Feed.feed_type,
  Species.withdrawal_temperature_c, SamplingPoint.is_active/kind/unit/system/equipment: changes of those fields). It
  refuses a change outside the guard through `pre_save`, `pre_delete`, `m2m_changed` (a treatment's units) and the
  QuerySet's `update`, `delete`, `bulk_create` and `bulk_update` (patched once, in the farm app's ready(); a model not in
  the registry passes through unchanged). The guard opens it for its write. Fixtures, commands and corrections that
  write behind it say why with `withdrawal_gate.opened(reason)`. The name-scan test is gone: the whole suite proves the
  gate, and `DataLayerTests` proves the registry and every kind of write.
- **One run (items 1 and 5).** The write runs once, in a savepoint. Its impact is worked out from the real after-state.
  If an acknowledgement is needed and not given, or `seen` is not exactly this impact's fingerprint, the savepoint is
  rolled back and `WithdrawalChanged` is raised with the change. Otherwise the write is kept as it was made, and the
  acknowledgements stored are those of the impact that was checked. Nothing runs twice, so a unit's status set by
  `_follow_status` stays (the reviewer's transfer probe, adopted as `OneRunTests`). `core.audit.marked` is gone. The
  guard writes its own critical log entry on the record, with the messages.
- **Earlier end (item 4).** `released` now covers any move of a held batch's withdrawal end to an earlier day (with the
  old and new end in the message), not only "free today". Owner decision as stated; note the cost below.
- **Explicit box (item 6).** No middleware. Every guarded service takes `withdrawal_ack=None`. Every `ServiceErrors`
  form carries an unrendered `withdrawal_ack` field and its save hands it to its own service. The void views, the water
  round, the row list (`RowList.question_field`) and the crud edit (`Resource.question_field`) pass the box of their own
  POST. A tick acknowledges that write only.
- **Locks (item 7).** `farm.stock.services.lock_fish`: read the batches present, lock them, lock the units, read again and
  lock any batch that arrived. Used by treatments, feedings, water samples, medicine rows and the Setup edits.
- **The acknowledged end (item 8).** A harvest already inside a withdrawal whose end moves later is asked again. In
  `check_withdrawal` an acknowledgement covers only the end it was given for ("Not acknowledged (acknowledged until X;
  now Y)").
- `check_withdrawal` labels per (harvest, batch, withdrawal) (cross-review 1, item 2).

Not guarded, on purpose:
- lice counts and a health event's void (no withdrawal input);
- the shared `voided` step (called inside each guarded void);
- sensor readings (the degree-days read the water samples only, `BatchWater`);
- data migrations (historical models) and raw SQL.

Known residual inputs not in the registry:
- a unit's `system` and the deletion of a unit or system, which change which samples count;
- a species' soft delete, which changes which withdrawal row applies.

Units with past fish are rarely deleted or moved, and `check_withdrawal` still catches what these do. Admin is
read-only, apart from its restore action, which goes through `save()` and is refused for gate fields.

**Cost (cross-review 2, item 8, measured by the reviewer):** a grower feeding takes 30 queries without the guard and 52
with it, because two full `Reader`s run. The `Reader` loads every treatment ever given in the units, with no date bound,
so the cost grows with the farm's age. The rule "every end moved earlier is asked" also means a temperature recorded
during a degree-day withdrawal whose projected end moves earlier asks for the box. For wip/perf and the owner:

- skip the guard for writes that cannot touch a withdrawal (a non-medicated feed, a sample without a temperature);
- bound the `Reader` to treatments overlapping the batches' presence;
- decide whether a projected (estimated) end moving earlier should ask.

Tests:
- `farm/tests/test_withdrawal_gate.py`: one run, refused stale acknowledgement, stored = shown, no ambient
  acknowledgement, earlier end, grown past the acknowledged end, data layer, the three Setup pages, the lock re-read;
- `farm/tests/test_withdrawal_guard.py`: each path's scenario, freed fish, labels, the spy that each known path calls
  the guard;
- `farm/tests/test_harvest_inside_withdrawal.py`;
- `farm/tests/test_migration_withdrawal_acknowledgements.py`: the reviewer's migration probe, with assertions;
- `reports/tests/test_scope_version.py`: item 9.

Migration farm 0027 (`0027_withdrawal_acknowledgements`): the new table and its append-only trigger, plus `batch` and
`withdrawal_source` on handling acknowledgements. Fully reversible; the reverse drops the acknowledgement rows. Reports
0014 adds `ReportSnapshot.scope_version` (default 1 for everything filed before).

## Findings fixed

| Finding | Root cause | Fix | Tests |
|---|---|---|---|
| F-195, F-188 (high) | A treatment's write path never looked for harvests already recorded inside the withdrawal it creates; `change_last_day` locked only the treatment. | The withdrawal guard (above); treatment paths lock batches, then units (`_lock_fish`). | `test_harvest_inside_withdrawal.py`, `test_withdrawal_guard.py` |
| F-124 | `check_withdrawal` folded the stock per unit. | One `stock_of` call. | `CheckWithdrawalTests.test_it_folds_the_stock_once` |
| F-086 (high) | The biomass report asked the person for the harvest condition though only round kilos exist. | The condition is derived (`compute.biomass.HARVEST_CONDITION` = round); `Report.harvest_condition` and its check dropped (reports 0013; filed reports keep their frozen snapshot). | `test_gaps789...test_the_harvest_condition_is_the_weights_never_an_answer`, `test_compute...test_losses_harvest_and_the_fallow_day` |
| F-101 (high) | Planned-slaughter deadline computed in four places; `fast_of` returned None once the plan was done. | One function `reports.compute.slaughter.deadline` through `compute.deadline_of`; `Report.deadline` (a `cached_property`: the list reads it once per row, cross-review 8), detail, due list, filing all use it; a filed report keeps `deadline_on`. The agreed day is clamped to each plan's own date (cross-review 7: a plan entered after its slaughter cannot make a week in time). | `reports/tests/test_deadline.py`, `test_probe_review.DeadlineProbe`, `test_cross_review.ReportListDeadlineTests` |
| F-083, F-239 | Medicine↔reason not checked; the lice report selects by reason only. | One rule `farm.health.lice.left_out_of_lice_report`: dialog warning (logged, not critical), report warning and fingerprint. | `test_lice_reason.py`, `test_lice.py::LiceMedicineForAnotherReasonTests` |
| F-085, F-227, F-238 | Plan fulfilment ignored week and facility. | One rule `reports.compute.slaughter.plans_of`; voided-harvest plans are open again in due and § 6. Due-list edge (cross-review 9) decided: a harvest of a plan dated before the site's reports-from date is owed nowhere in this system (the plan's week was the farm's to report before it used the system). | `test_slaughter_duty.py::PlannedAndDoneTests`, `test_plan_moved.py`, `test_cross_review.PlanBeforeReportsFromTests` |
| F-080 | One-column table gave an SFR only at its temperature. | Tables need two columns. | `test_one_column_table.py` |
| F-082 | Weekly site average from the filtered list. | `_site_weeks`: whole sites and ISO weeks, with its own date parser `_iso_day_or_none` (cross-review 5: wip/fix-integrity removes `_day`). | `test_lice_page_filter.py` |
| F-206 | Lice fingerprint missed earlier counts and plans. | Both in scope; plans bounded to `period.end + SLAUGHTER_DAYS` and their harvests' operations included (cross-review 4). | `CoverageRowsTests`, `test_probe_review.LiceFingerprintProbe`, `test_cross_review.LiceFingerprintTests` |
| F-077 | reopen / undo_duty_done unlocked. | Lock, refuse when gone, log after delete. | `test_take_away_once.py` |
| F-196 | Medicine rows edited at NORMAL severity; a shortening freed held fish unasked. | CRITICAL while a live treatment used the medicine (`RowList.severity`), and the rows go through the guard. | `test_withdrawal_rule_change.py`, `test_withdrawal_guard.py` |
| F-081 | Rate check per record. | The day's total. | `test_feeding...test_the_usual_rate_is_of_the_days_total_not_of_one_feeding` |

Translations: TR/NB, 0 missing (babel check); data map regenerated after the merge.

## Cross-review answers

1. Guard on every write path, enumerated: done (above).
2. `check_withdrawal` per pair: done.
3. Shortening that frees held fish: confirmed and critical, through the guard: done.
4. Lice fingerprint plans bounded, plus their harvests: done.
5. `_site_weeks` no longer uses `_day`: done.
6. farm 0027 keeps its number and is reversible: done.
7. Agreed-late clamp: done.
8. Deadline once per list row: done.
9. Due edge decided and tested: done.
10. Hook signature `(user, kinds, record)`: done.
11. Test hygiene: `aa148ad` ("Test: a plan is cancelled as its form cancels it") changed an existing assertion from a
    `queryset.update()` to a versioned save so that it could pass; it is not test-first, and the fingerprint still does
    not see `update()` writes that bypass versions (any write path in the app bumps the version). The lock tests check
    that batches and tanks are locked, not the order; the order is shared code (`_lock_fish`, `locked`).

Cross-review 2 (REVIEW-CROSS-2-health.md), the coordinator's decisions:

1, 5. One run in a savepoint; the impact is checked against exactly what was shown; nothing is written twice: done.
2, 3. Data-layer enforcement (`farm/withdrawal_gate.py`), the Setup edits through the guard, the name scan replaced: done.
4. Every earlier end of a held batch asks (the test that expected otherwise removed): done.
6. No middleware; `withdrawal_ack` is an explicit argument of each guarded service, handed over by its own form: done.
7. Units locked, the batches read again under the lock (`lock_fish`): done.
8. An acknowledgement covers its end: the guard asks again and the sweep says so: done.
9. Scope versions on the snapshot (`scope_version`; lice and slaughter 2): done.
Cost (30 -> 52 queries per feeding): recorded above for wip/perf.

## Not fixed, and why

- F-193, F-194: projection model changes; filed reports are frozen.
- F-189: the content-hash check already refuses a torn read.
- F-205: the detail page shows it; a sweep over all history is a performance decision.
- F-044, F-063, F-102, F-027, F-125, F-219: performance; measure first. The guard adds two withdrawal snapshots to each
  guarded write (a feeding, a stock operation): a measured cost item for wip/perf.
- F-173: belongs with the route x permission sweep (F-169).
- F-073: alarms work (package G). The guard's critical entries and `WithdrawalAcknowledgement` rows are what it will read;
  `check_withdrawal` is still a command nothing schedules.
- F-224, F-120: cosmetic.
- F-006 (reports year), F-232: package E (wip/fix-integrity).
- A filed biomass report with "gutted" stays as filed; its page shows the difference.
- Stored one-column feeding tables are not converted.
- The lice-reason warning shares the handling box, whose help text says "logged as critical".

## Merge notes

- wip/fix-integrity removes `_day` from `farm/health/views.py`: `_site_weeks` uses its own `_iso_day_or_none`.
- farm 0027 is this branch's; the other branches renumber after it.
- `config/settings.py` gains one middleware line (`farm.middleware.WithdrawalAcknowledgementMiddleware`).

## Checks run

At c99310e (main 16fa1b3 merged): `scripts/test.sh` (the full suite, parallel, its own throwaway database server): 2915 tests,
2909 OK, 3 skipped, 6 failures, all `monitoring.tests.test_golden` G-03 (the stale card). That test fails the same way on
main 16fa1b3 itself, run at the same hour (it depends on the time of day: a sample 30 hours old); it is monitoring's, not
this branch's. `makemigrations --check` no changes; `data_map --check` up to date; catalogs TR/NB 0 missing;
`compile_catalogs`; `tsc --noEmit` OK; `npm test` 40/40 (node_modules of F:/dev/balik-ciftligi).
