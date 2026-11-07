# Paused (coordinator, 2026-11-07)

Committed and green in targeted runs: core_rev (step 3), background jobs (step 11 backend, worker, /healthz, Dockerfile,
compose `worker`). Committed as failing tests, implementation not yet committed: keyset paging (core/tests_paging.py),
the cold tier (sensors/tests/test_tiers.py).

No container of this worktree runs; test_perf and test_perf_world were dropped (recreate on resume, about 8 min).

## Exact next step
1. Uncommitted, in this worktree (work in progress, NOT verified): core/paging.py, core/archive.py, sensors/tiers.py,
   sensors/models/archive.py (+ export in sensors/models/__init__.py), sensors/migrations/0007_archived_chunk.py,
   COLD_ARCHIVE_DIR in config/settings.py, duckdb==1.5.6 in requirements.txt, THIRD_PARTY.md, perf/MEASURED.md.
   Tests run with image `balik-testrunner-perf` (balik-testrunner + duckdb 1.5.6; rebuild from
   ../img/Dockerfile if missing).
2. Last run (core.tests_paging + sensors.tests.test_tiers): 3 failures, 4 errors, all understood:
   - tests_paging PageTests.setUp updates audit_log.created_at: refused, audit_log is append-only. Fix the TEST: use
     another ordered model without that trigger (e.g. farm water samples or a model of the test's own), commit as
     "Test:".
   - test_tiers `archived()` test reads `.start/.end`: either give ArchivedChunk `start`/`end` properties or make the test
     read range_start/range_end (test decides: keep the model's field names, fix the test).
   - test_tiers refusal messages: drop says "differ"; the tests look for "differs". Align the message in tiers.drop
     ("... differs from the export ...").
   - GrowthTests fails by design until every Resource declares `growth` (47 tabs): do this only AFTER the fix branches
     land on main (touches every resources file).
   - one more error not yet read (re-run and read the full output).
3. Then: README section for the tiers (draft at the end of this file's sibling notes: /tmp is gone, rewrite from
   sensors/tiers.py's docstring), data_map, update_catalogs (ArchiveState labels and verbose names need NB/TR), commit
   the paging and tiers implementations separately.
4. Step 0 world harness: a helper's unverified draft is parked OUTSIDE the tree in
   ../hold-perf/park/{farm/world.py, farm/test_world.py, cmd/bench_world.py}. Review it fully before use (it was stopped
   mid-work), test first, build the world only into perf_* databases, never `balik`; then measure and fill
   perf/MEASURED.md with the step-0 figures (phase profile, EXPLAIN, budgets recorded as current).
5. Report to the coordinator after the NOW part; the LATER steps wait for the fix branches on main.
