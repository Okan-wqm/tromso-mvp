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

## The withdrawal guard (F-195, F-188, F-196; cross-review 1, 2, 3)

ONE function, `farm.health.withdrawal.guarded(user, batch_ids, today, write, ...)`, is the gate of every write that can
create, grow, shorten or end a withdrawal: `record_treatment`, `change_last_day`, `void_treatment`, `record_feeding`,
`void_feeding`, water `record` / `record_round` / `void`, stock `_commit` (every stock operation) and `void`, and
`MedicineWithdrawalList.save` (the medicine's rows). It works out the withdrawals of the fish the write touches (their
batches, locked first: batches, then units, the order a harvest locks them) before and after the write, inside the
write's transaction, and asks when the write

- brings a recorded harvest inside a withdrawal it was not inside before (`harvested`), or
- frees fish held by a withdrawal today (`released`; cross-review 3: shortening a running course, a medicine's row, a
  void, a temperature correction that frees held fish is confirmed and logged critical, not only relabelled).

The write is tried in a savepoint; with nothing to ask it stands as it is (one write). With warnings it is rolled back and
refused (`WithdrawalChanged`, a ValidationError on `withdrawal_ack` carrying the change) unless the person went on past
exactly these warnings (the box `withdrawal_ack`, its value the fingerprint; `farm.middleware.WithdrawalAcknowledgementMiddleware`
hands it to the guard from the POST; tests use `withdrawal.acknowledging`). Going on makes the write again inside
`core.audit.marked(CRITICAL, ...)` (its own log entries critical, with "Withdrawal warnings acknowledged") and stores one
`WithdrawalAcknowledgement` per warning (the write, the batch, the withdrawal `source`, the harvest; append-only by a DB
trigger). A harvest the write itself records is left to its own handling check (not asked twice). Every dialog shows the
question with its box (`templates/farm/_withdrawal_change.html`, through `ServiceErrors.withdrawal_change`; the medicine
rows page through `RowListView`). `check_withdrawal` labels an acknowledgement only for the (harvest, batch, withdrawal)
it names: `HandlingAcknowledgement` withdrawal rows now keep `batch` and `withdrawal_source`; older rows name none and
count as not acknowledged (cross-review 2).

Not guarded, on purpose (stated in `WritePathTests.EXEMPT` or here): lice counts and a health event's void (no
withdrawal input); the shared `voided` step (called inside each guarded void); sensor readings (the sensors
app; the degree-days read the water samples only, `farm.water.degree_days.BatchWater`); the Django
admin and data migrations (superuser tools). A water point of equipment holds no fish.

Tests: `farm/tests/test_withdrawal_guard.py` (14: each path's scenario, freed fish, labels, the enumeration of the write
functions of the four service modules plus the medicine rows, and a spy that each path calls the guard),
`farm/tests/test_harvest_inside_withdrawal.py` (rewritten to the guard), `farm/tests/test_probe_review.py` (the
reviewer's probes 1 and 2, adopted).

Migration farm 0027 (`0027_withdrawal_acknowledgements`, keeps number 0027; replaces this branch's earlier 0027, which
never landed): the new table and its append-only trigger, `batch` and `withdrawal_source` on handling acknowledgements.
Fully reversible (cross-review 6).

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

See the final report: full Docker suite on a fresh test DB, `makemigrations --check`, `data_map --check`,
`compile_catalogs`, `tsc --noEmit`, `npm test`.
