# Review notes: wip/fix-health-reports

Branch from main b24de24 (main has not moved since; nothing to merge). Area: farm/health (treatments, withdrawal,
lice), handling/withdrawal checks, harvest and harvest plans, feeding, reports/. Every behaviour is test first: a
`Test:` commit (seen failing for the right reason), then the fix commit with its README/docs lines.

## Owner hook (second person's approval)

`farm.handling.check.second_person_must_approve(kinds)` is THE one hook for the platform owner's setting "a second
person approves a withdrawal acknowledgement" (owner answer 2026-11-06, F-164). It is consulted in one place,
`check.require_acknowledged`, i.e. every dialog that goes on past warnings (harvest, transfer, grading, treatment,
last day, experiment start), and only when the warnings gone past include a withdrawal kind (`WITHDRAWAL_WARNINGS`:
`withdrawal`, `harvested`). It returns False now. When it returns True the save is refused with "A second person
must approve ... cannot be given here yet" (fail closed until the approval flow exists). wip/owner-settings: make the
function read the setting and build the approval flow; nothing else needs to change. Test:
`SecondPersonHookTests.test_the_platform_owners_setting_is_asked_in_one_place_before_a_withdrawal_is_gone_past`.

## Findings fixed

| Finding | Root cause | Fix | Tests |
|---|---|---|---|
| F-195, F-188 (high) | A treatment's write path checked only fish on the first day and the fast; nothing looked for harvests already recorded inside the withdrawal it creates; `change_last_day` locked only the treatment. | `farm.health.withdrawal.course_harvests` (treatment saved or not) and `harvests_inside` (sweep) share one rule `_inside` (= `Withdrawal.holds_on` on the harvest's day). `services.handling` / `last_day_handling` add each such harvest as a warning (`HarvestInside`) to the treatment dialog's box; going on stores a `HandlingAcknowledgement` of the new kind `harvested` naming the harvest (new FK `harvest`, DB shape check: harvested rows name harvest + treatment, no other row names a harvest; migration farm 0027, existing rows stay valid) and logs CRITICAL. A longer course asks only about harvests it newly brings inside; shorter asks nothing. Both paths lock batches then units (`_lock_fish`, the order a stock operation locks). `check_withdrawal` lists every harvest inside a withdrawal, however it came to, and whether it was acknowledged (at harvest, with the treatment, or not). | `farm/tests/test_harvest_inside_withdrawal.py` (16 tests: BackdatedTreatmentTests, LongerCourseTests, SecondPersonHookTests, AcknowledgementShapeTests, CheckWithdrawalTests) |
| F-124 | `check_withdrawal` folded the stock per unit. | One `stock_of` call. | `CheckWithdrawalTests.test_it_folds_the_stock_once` |
| F-086 (high) | The biomass report asked the person for the harvest condition though only round kilos exist. | The condition is derived (`compute.biomass.HARVEST_CONDITION` = round); `Report.harvest_condition` and its check dropped (reports 0013; filed reports keep what they filed in the frozen snapshot, dropping a column fires no row trigger). | `test_gaps789.ConditionAndFeedFieldsTests.test_the_harvest_condition_is_the_weights_never_an_answer`, `test_compute...test_losses_harvest_and_the_fallow_day` |
| F-101 (high) | Planned-slaughter deadline computed in four places; `fast_of` returned None once the plan was done. | One function `reports.compute.slaughter.deadline` (rule Thursday, the fast each plan asked for, done or not via `fast_of(done_too=True)`, the late-agreed day) through `compute.deadline_of`; `Report.deadline` (list), detail, due list, filing all use it; a filed report keeps `deadline_on`. | `reports/tests/test_deadline.py` (readers agree; unchanged after the harvest; agreed late; filing and after a rule change) |
| F-083, F-239 | Medicine↔reason not checked; the lice report selects by reason only. | One rule `farm.health.lice.left_out_of_lice_report`. Treatment dialog: warning `LeftOutOfLiceReport`, goes on past the box (logged "Warnings acknowledged", NORMAL: not a fish/food warning, not stored as a handling acknowledgement). Lice report: a warning per such treatment of the week, and the treatments enter its fingerprint scope. | `farm/tests/test_lice_reason.py`, `reports/tests/test_lice.py::LiceMedicineForAnotherReasonTests` |
| F-085, F-227, F-238 | `_fulfil` links a plan regardless of week/facility; `unplanned_of` excluded only plans of the same facility and week; due list created a duty for the harvest's own week too. | One rule `reports.compute.slaughter.plans_of`: a harvest recorded from a plan is the plan's (owed and counted once there). `unplanned_of` and due use it; both reports warn where it went; the harvest dialog notes it beforehand (never refuses). Same class found and fixed: due and the lice § 6 exception filtered out plans whose harvest had been voided (they are open again by the model's own rule `HandlingPlanItem.done`). | `reports/tests/test_slaughter_duty.py::PlannedAndDoneTests` (4), `farm/tests/test_plan_moved.py`, `test_lice.py::CoverageRowsTests` |
| F-080 | A one-column table gave an SFR only at exactly its temperature (no extrapolation, Q1). | The table form needs at least two columns; the lookup's last-line comment corrected. Stored one-column tables still read only their temperature (not migrated: no value can be invented). | `farm/tests/test_one_column_table.py`; page tests moved to two columns |
| F-082 | The weekly site average was computed from the filtered count list. | `_site_weeks`: whole sites (a unit filter selects its site) and whole ISO weeks (dates select the weeks they touch). | `farm/tests/test_lice_page_filter.py` |
| F-206 | Lice report fingerprint missed earlier counts and harvest plans. | Both added to `scope`. | `CoverageRowsTests.test_an_earlier_count_and_a_plan_are_in_the_fingerprint` |
| F-077 | reopen / undo_duty_done unlocked, audit before delete. | `_take_away`: lock, refuse when gone, log after delete; views show the refusal instead of a 500. | `reports/tests/test_take_away_once.py` |
| F-196 | Medicine withdrawal rows edited at NORMAL severity although they move running courses. | `RowList.severity(obj)` hook; Medicines list answers CRITICAL while a live treatment used the medicine. Live computation (HLT-02) kept on purpose; check_withdrawal catches harvests it brings inside. | `farm/tests/test_withdrawal_rule_change.py` |
| F-081 | The 10 %-a-day acknowledgement checked one record. | The day's total of the target in the unit (under the unit lock); message says the day's kilos. | `test_feeding.RecordTests.test_the_usual_rate_is_of_the_days_total_not_of_one_feeding` |

Translations: TR/NB filled for every new message (0 missing, checked with babel); data map regenerated.

## Not fixed, and why

- F-193 (feed of a batch gone by day's end not credited), F-194 (past projection drifts): projection model changes,
  estimate error ~one day's growth; needs its own design. Filed reports are frozen, so filings are unaffected.
- F-189 (submit READ COMMITTED): the content-hash check already refuses a torn read that differs from the preview.
- F-205 (no_longer_match skips old periods for master data): detail page `differences()` shows it; a list sweep over
  all history is a performance decision.
- F-044, F-063, F-102, F-027, F-125, F-219 (performance, recomputation per request): measure first (README's cache
  decision); no correctness change.
- F-173 (report reads without area perms): plausibly by design (the filer needs the figures); belongs with the
  route x permission sweep (F-169, security agent).
- F-073 (critical severity read by no alarm): the alarms are the owner's new alarm/outbox work (package G), not here.
- F-224 (void dialog copy), F-120 (`_day` duplicated): cosmetic; left to avoid touching every view in this batch.
- F-006 `reports/views.py` year 500: listed in package E (wip/fix-integrity); not touched here to avoid a conflict.
- F-232 (HealthEvent double submit): package E (wip/fix-integrity).
- A filed biomass report with "gutted" stays as filed (frozen); its page shows the difference to the recomputation.
  Whether to tell Fiskeridirektoratet is the farm's decision.
- Stored one-column feeding tables are not converted; the form refuses new ones.
- The lice-reason warning shares the handling panel and its box, whose help text says "logged as critical"; for
  that warning alone the entry is not critical. Copy polish for a later batch.

## Checks run

Targeted modules while working; final: full Docker suite (balik-testrunner, test_fixhr, no --parallel): 2786 tests OK
(3 skipped), at 65dd20b;
`makemigrations --check` (no changes), `data_map --check` (up to date), `compile_catalogs`, `tsc --noEmit` (ok),
`npm test` (40/40).
