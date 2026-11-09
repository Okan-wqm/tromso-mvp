# Review notes: wip/owner-settings

The owner's platform settings, opening balances, the alarms app (F-091) and the alarm plan's defects (§2.3) and rules as
user data (§7c), then an independent cross review of round 2 (8b1f576) and its fixes. Every behaviour was written as a
test first and seen failing for the right reason (the `Test:` commits), then fixed in its own commit.

## Round 2: the alarm plan's defects (§2.3) and rules as data (§7c)

Design of round 1: the platform settings row (correction window, second approval), opening balances (F-197), the alarms
app (alarms, clearances, outbox, escalations, acknowledgements, append-only; recipient rules; `run_alarms`).

1. Units, not every point: `sources.water` reads `farm.water.read.unit_water` once (an inlet raises none; a depth point and
   the loop raise the unit's one alarm).
2. L/LL levels with on/off delays in data time and deadbands through `evaluate.judge` on the moved value; structural
   clear; a warning not notified under its critical.
3. Unreadable live sources: no clears in that pass, and a critical system alarm, restored when they answer.
4. Clear evidence must be newer than the last bad value.
5. Each loop step in its own transaction, failures logged and said; `run_alarms --loop` survives a failed pass.
6. `alarm_subject_state.open_alarm` unique, and a raise is one compare-and-set statement.
7. Set-based writes and routing read once per pass (`routing.Router`): the same queries for 2 and 6 alarming units.

§7c: `alarms.SeverityPolicy` (per severity) and `alarms.ParameterDeadband` (per parameter), seeded with the §7a defaults,
on Company › Alarms, logged, read once per pass.

## Merge of main 24d8326 (stock-mix landed)

- farm `0034_opening_balances` is now `0036_opening_balances` on `0035_stock_operation_size_mix_ack`; alarms `0004` no
  longer depends on a farm migration.
- `_commit` keeps both the size-mix and capacity timeline check and the opening balance; the opening balance form asks
  the size-mix acknowledgement as a stocking does (`record_opening_balance` goes through the size check).
- The data map and the catalogs were rebuilt (both sides kept).

## The cross review (8b1f576) and its fixes

The cross review checked the branch with its own probes, each asserting the safe behaviour. Every probe is now a test.

| # | Finding | Test commit | Fix commit |
|---|---|---|---|
| F1 blocker | A value stamped ahead of the clock (the read layer counts it up to the ingest contract's hour) delayed or suppressed its alarm while the card showed critical | 0065bdd | 00932e5 |
| F2 high | The deadband was applied to the deciding value only, so a level chattered | d24cd16 | bfc9b4a |
| F3 high | A step that failed every pass was silent, and one bad unit silenced the farm | 5f99527 | 0a87c05 |
| F4 high | The second-approval setting did nothing, but its help text said it did | 958c739 | de7471a |
| F5 high | Migration collision with main, merge conflicts | (merge) | 2a7ff18 |
| F6 medium | A missing severity rule disabled every water alarm | 0b6a315 | 9b28558 |
| F7 medium | Subjects keyed by point: a replaced middle point left an orphan and a duplicate | a13d216 | b944ea4 |
| F8 medium | A system alarm (no site) reached only company-wide rules | ade6945 | 5f7326b |
| F9 medium | Bounds were form-only and allowed unsafe values | 9f36877 | 51d47e0 |
| F10 medium | The staleness thresholds the alarms depend on were code constants; the numbers scan was narrow | 55f2db1 | 0a9eedd |
| F11 medium | The outbox is read whole each pass and would replay late | not fixed (worker phase) | |
| F12-F16 low | Structural clear names no change; carried events cleared as "returned"; 0004 not reversible; stale texts; a unit with no point has no alarm | 369ea4a | cec114c |
| Owner, 2026-11-09 | A device clock that differs from the platform's is an alarm | 35b138b | bb0a3ff |

### F1 (blocker): a fast device clock delayed or suppressed a critical alarm
- Root cause: the on-delay ran from the deciding value's own time; a value stamped ahead made `now - pending_since`
  negative, so even with critical on-delay 0 nothing was raised until the wall clock reached the stamp (up to 1 h).
- Fix: `sources.seen_at` = the value's time or the pass's, whichever is earlier, for the on-delay, the last bad value's
  time and the clear evidence's time. The values still decide the status as the read layer does (MAX_AHEAD contract).
- Tests: `ClockAheadTests` (4 min and 20 min fast raise critical at once; the warning's on-delay runs from the pass; the
  off-delay runs from the pass).

### F2: the deadband across every fresh value
- Fix: the read layer keeps the values that take part in a reading's status (`Reading.deciding`); `sources.judged_clear`
  judges each of them moved by the deadband through the same `evaluate.judge`. A level clears only when every one is clear.
- Tests: `DeadbandAcrossCandidatesTests`.

### F3: the alarm system supervises itself
- Fix: a supervision step, last in every pass, raises a critical system alarm per failed step (`system:step:<name>`) from
  the pass it fails in until it passes again (on-delay of the critical rule, 0 s: the first failed pass, the safest
  reading of "consecutive"). The water step reads all units at once and, when that fails, each unit in its own savepoint;
  each unit is evaluated on its own, so a unit that cannot be read or evaluated raises its own critical "could not be
  evaluated" alarm on its site, and the others go on. Writes stay set-based (the burst test's query count is unchanged).
- Tests: `FailedStepTests`.

### F4: second approval fails closed
- Decision: wire the hook, not hide the setting. Main's hook `second_person_must_approve` now asks
  `core.platform.second_approval_required('withdrawal')`. The approval flow does not exist yet, so ticked, every step past
  a medicine withdrawal is refused with "A second person must approve ... that approval cannot be given here yet". This
  keeps the owner's intent (nobody goes on alone) instead of a setting that silently does nothing; the help text says the
  approval is not built yet and such steps are refused.
- Tests: `SecondPersonSettingTests` (farm).

### F6: a missing severity rule
- Fix: `alarms.rules` gives each field of a missing severity the safest value (no on-delay; the longest off-delay, the
  shortest escalation, the most attempts of the rows there are, else their bounds); rules that cannot be read at all give
  the safest everything. The supervision step raises a critical configuration alarm until the row is back. A severity's
  rule cannot be deleted: model (`soft_delete`, `delete` refuse), a check (`is_deleted = false`) and a DELETE trigger
  (alarms 0006); the page offers Edit only.
- Tests: `MissingRuleTests`.

### F7: subjects keyed by unit
- Fix: `water:unit:<unit>:<slot>:<severity>`; a removed unit's subjects clear with "the unit was removed". alarms 0007
  re-keys every point-keyed subject; where two points of one unit had an alarm open at one level, the earliest stays open
  and the others are cleared with the cause "merged" (an append-only record of why); timers merged the safe way (earliest
  pending, latest bad value, no clear timer). Reversible.
- Tests: `UnitKeyTests`, `test_migration_subjects`.

### F8: routing of system alarms
- Fix: system alarms carry a site where one applies (a unit's evaluation, a unit without a point, a device's clock). A
  system alarm no rule reaches by site goes to every rule its severity reaches (company-wide rules first, since they match).
- Tests: `SystemRoutingTests`.

### F9: bounds in the model and the database
- Fix: per-severity bounds, checked by the model (`clean`) and the database (alarms 0008): critical on-delay at most 10 s
  (the owner's 10 s target, alarm plan §2.4, §7a Q3: "the 10 s rule wins over spike filtering"), critical escalation at
  most 30 min (six times the owner's 5 min), warning on-delay at most 15 min (EEMUA 191: an alarm asks for a timely
  response); a deadband at most its parameter's range (a database check). Unusual values inside the bounds (any critical
  on-delay, an escalation past 15 min for critical or 2 h for warning, a deadband over half the narrowest band of the live
  limits) are shown with a warning on the rules' pages, never refused.
- Tests: `RuleBoundsTests`.

### F10: staleness thresholds as rule data
- `fresh_hours` (per parameter) is now `farm.WaterFreshness` (Setup › Reference data › Water freshness, one seeded row per
  parameter, changed only, farm 0037), read through `farm/water/freshness.py`: once per request and per alarm pass, again
  after a row is saved; a lost row is made again from the seed (as the platform settings' row is).
- `CLOCK_SKEW` is the platform settings' clock tolerance (core 0010, 300 s, 0 to 3600).
- `FRESH_HEARTBEATS` is each channel's `fresh_heartbeats` (sensors 0010, 3, 1 to 20); `fresh_s` follows it.
- `MAX_AHEAD` stays a constant: it is the ingest contract's hour (`sensors_contract.future_skew_s` is at most 3600 s), a
  protocol limit both sides hold, not a policy; the scan's allowlist says so.
- The numbers scan reads every module an alarm's decision reads (alarms, evaluate, freshness, sensors' clock); a name is
  no pass by itself: each exception is named with its reason, and a reason for a name that is gone fails.
- Tests: `test_freshness`.

### F12-F16 (low)
- F12: a limit removed while its alarm is open clears it with "the water limit was removed"; the log entry names the row,
  who removed it and when. No fish is "no fish in the unit any more".
- F13: sensor events carried in by sensors 0008 clear with "event_closed" (alarms 0009 sets the append-only trigger aside
  for that one statement in its own transaction).
- F14: alarms 0004 refuses to go back once a system alarm exists, saying why (the alarms are append-only; restore a backup
  taken before it instead).
- F15: the level help and the access comment name the severity rules, not the Platform settings.
- F16: a unit with fish and no active point for its own water is a configuration warning on its site until it has one.
- Tests: `StructuralClearTests`, `TextTests`, `UnwatchedUnitTests`, `test_migration_reverse`.

### Owner, 2026-11-09: device clock alarm
- Measured per device from what the ingest already stores: `sensors_channel_state.last_value_ts` (the device's time of
  the newest good value, or the receive time when flagged 2 or 4) against `last_good_at` (when it was received). Ahead and
  behind. A time the ingest replaced (flag `clock_suspect`) is ahead by more than the contract's future skew; a message
  without a device time measures nothing; a value received longer ago than the channel's freshness measures nothing now.
- Judged by each severity's device clock limit and deadband (SeverityPolicy, alarms 0010): warning 60 s / 10 s (the
  ingest contract's default future skew, past which the ingest no longer trusts a device's time), critical 300 s / 30 s
  (the read layer's clock tolerance, past which a value ahead is no longer shown as fresh). The warning's limit is below
  the critical's (model). Raised and cleared per device, on its site, by the same settle (its warning not notified under
  its critical; a device removed or deactivated ends them).
- Shown on the device list (State) and on the unit's card as a data-quality note for the devices whose values the card
  shows ("Device clock is 4 min ahead (PROBE-1)").
- F1 still holds: a skewed device's values decide the status, their alarms are never delayed.
- Tests: `test_clock`.

## Migrations
- core 0009_platform_settings, 0010_clock_tolerance.
- farm 0036_opening_balances (on 0035_stock_operation_size_mix_ack), 0037_water_freshness.
- sensors 0008, 0009 (acknowledgements moved), 0010_channel_fresh_heartbeats.
- alarms 0001-0005 (round 2), 0006_severity_rules_kept, 0007_subjects_by_unit (data, reversible), 0008_severity_bounds,
  0009_clearance_causes (data), 0010_device_clock (seed).

## Weak points (known, not fixed here)
- F11: the outbox is read whole every pass, and a connected transport would send the whole backlog, including alarms
  cleared or acknowledged long ago. For the worker phase: filter to open, unacknowledged alarms (or expire older ones with
  a record), the failure-count cap in SQL, and a test that a cleared alarm's queued notification is not sent.
- A step failure is alarmed from the first failed pass (critical on-delay 0); a flaky step would raise and clear. The
  owner's on-delay for critical decides; no separate count of consecutive failures was added.
- If the supervision step itself fails, nothing alarms it but the log; the worker's dead man (later phase) covers a dead
  loop.
- A device clock "behind" includes the network's and the broker's delay; a gateway that buffers and sends late reads as
  behind. The card's note covers only devices whose values the card shows.
- The water freshness rows are held per process: a change reaches another process at its next request or pass.
- Not done from the plan (later phases): the worker process with NOTIFY wake-ups, shelving, flood grouping,
  `alarm_conditions` shared with the monitoring card, journal table, worker status. `check_sensors` still exists.
