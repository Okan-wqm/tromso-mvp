# Paused (coordinator, wave for the fixes)

Done and committed: steps 1 (route walk, non-interference, registry tests), 2 (core.sealing, AccessEvent), 3 (schema,
migration 0003), 4 (whole-system booking, neutral booked message).

Next step: step 5 (experiments' own seal). The half edit is saved, not committed, as
`scratchpad/expacc-tools/paused/step5-wip.diff` (apply with `git apply`); the per-app seal modules and later-step
scripts are in `scratchpad/expacc-tools/paused/hold` and `scratchpad/expacc-tools/apply_step5.py`, `apply_step6.py`.
After applying, these existing tests still expect a reader outside the team to see a (now sealed by default) experiment
and must be brought to the new rule (team, share or `audience='open'`): test_pages Create/Language (log row count),
DeleteTests, EditTests history, ListTests, PermissionTests, ReadTests, test_copy CopyPageTests; the database viewer test
needs descriptions for experiment_shares / experiment_replicate_systems / experiment_cells / core_access_events
(config/database.py). DeletePlanTests turns green with step 6 (farm seals). Then steps 6-9, 11-12; step 10 after
wip/fix-security is on main (merge main first, rebuild catalogs, regenerate the data map).

Known integration debts: farm/tests/test_water_points `test_there_is_one_implementation_of_the_units_water` must list
farm/sealing.py; catalogs (AccessKind, booking texts) and the data map need regenerating; full suite takes ~2.6 h on the
shared machine.
