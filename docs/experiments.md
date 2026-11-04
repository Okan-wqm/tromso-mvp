# Experiments

Research › Experiments (`experiments/`, its own app; the README's section "Research › Experiments" says what each page does).
This document is the reference a researcher, a reviewer and the next developer read: what a day means, how the tanks are
dealt, what the database holds and what the code holds, what is derived and never stored, and what is checked live.

## What it is, and what it is not

An experiment is a **pre-registered design**: factors (the diet, and others with a unit), their levels, groups that each
take one level of every factor, replicates (a place in a group), and the tanks of each replicate with the days they are
booked. It is written once, **started**, and from then on the database itself refuses to change it. Everything about how it
went is **read from the farm's own records** (stock, feeding, health, water) over the days of the placements; nothing of
that is copied or stored in the experiment.

Not here (left to the statistics, the report and the lifecycle plans): the statistical tests, the end-of-trial report, the
record lock on a tank in a trial, closing an experiment, the permissions per experiment (a student edits only the
experiments they are in the team of), the sampling plan and the dataset.

## Days

All days are **dates on the site's clock** (the site's time zone, else the company's), both ends included.

| Day | What it is |
|---|---|
| day 0 | `starts_on`: the baseline. Each tank holds fish of the species and is weighed on this day: the window of its feed conversion starts at that measured point. A draft's day 0 is at most 31 days back (the farm's registration window, `settings.STOCK_BACKDATE_DAYS`); a started experiment is not held to it. |
| last day | `starts_on + duration_days`: the final weighing. The experiment has `duration_days + 1` days, day 0 to day N. |
| a placement | `from_on` to `until_on` (both included): the days a tank is booked to a replicate. The default is day 0 to the last day; a row may have days of its own inside them. |
| "now" | today on the site's clock. A placement whose first day has not come is not read; one whose last day has not come is read to today. |
| yesterday | the earliest last day a tank may be released with, and the earliest day before which a diet row may not be ended (the farm's rule: the days before yesterday keep what happened in them). |

Every figure of the Overview is bounded by the placement's days: the feed conversion runs **from the weighing of the first
day to the latest weighing**, or, once the last day has come (or the experiment is closed), **to the weighing of the last
day**; a bound that is not the day of a measured point gives no window and a dash that says why (nothing is interpolated). The survival
is the share of the fish present on the first day (in the tanks the replicate began with: the fish moved into a replacement are the same fish)
that were not lost since (mortality, culls, an adjustment down; in a replacement from its first day) to the last day or today. There is **no "since stocking" figure beside a trial figure**, and no figure of a group: a mean over
replicates is a statistic, which the statistics area comes with.

## Allocation

A group's tanks are given **by hand** (the method `manual`, with the reason in `allocation_note`) or **randomised** with the
method id **`sha256_v1`** and the seed in `allocation_seed`: the pool (tanks, or systems whose tanks go to one replicate
together) is sorted by `sha256("<seed>:<code>")` (hexadecimal, as text) and item *i* of the sorted pool is given the replicate *i* in
the order of the design (the group's position, then the replicate's number). It is not `random.shuffle`: only
`random.random()` is guaranteed stable between Python versions, and a deal must be reproducible years later from the
seed and the pool alone. The same pool and the same seed always give the same placements (fixed vectors in
`experiments/tests/test_places.py`, checked against `sha256sum`); the method id is stored so that a later method does not
change what an old experiment means.

## Life of an experiment

`draft → running → closed`, forward only (`models.TRANSITIONS`, and the trigger). Only **Start** is built here; closing is the
lifecycle plan's.

- **Draft**: the design, the places and the team are edited freely; the tanks are **reserved** (a draft holds its tanks as a running one does).
  A template is a draft design without a day 0, tanks or allocation; a copy starts from a design, never its tanks, allocation, seed or team.
- **Start** (`services.start`): needs no error of `design.problems` (hypothesis, primary endpoint, day 0, a lead, an allocation, a
  tank in every replicate on the site and inside the days, the diet's protocols active and of the species, no standing assignment of
  the tank's own and no protocol assigned to a batch in the tank that would beat the diet), asks for the warnings to be
  acknowledged (by their fingerprint: if they changed meanwhile, it asks again), writes the **unit-scope assignment rows through
  the farm's own assignment path** (`farm/feeding/assignments.py`: the row the dialog would write, logged as the dialog logs it) for every
  tank of a diet group over its placement's days, and sets the status, all in one transaction. The ration then follows the diet on every day.
- **Running**: the design is fixed. A tank may **leave** (`release_unit`) or be **replaced** (`replace_unit`), each with its
  reason; nothing else changes. The replicate keeps its number; the old placement only gets shorter; the diet's row follows.
- **Deviations** are read, never refused: a batch that came in, fish moved between replicates or out of the trial, a feed on
  no band of the diet, a ration that does not follow it (`read.deviations`).

## What the database holds

Constraints (migration 0001, tested one by one by ORM bypass in `experiments/tests/test_constraints.py`) and triggers (migration 0002,
tested by raw SQL in `test_triggers.py`):

| Held by | Rule |
|---|---|
| `excl_replicate_units_unit` (exclusion, `btree_gist`) | a tank is in one experiment at a time, drafts included: no two live placements of a tank overlap in days |
| `chk_experiment_placements_period` | a placement ends on or after the day it begins |
| `uq_experiments_code`, `chk_experiments_code` | the number `E-YYYY-NNN` is unique (numbers are never reused: `core/codes.next_code`) |
| `chk_experiments_status`, `chk_experiments_endpoint`, `chk_experiments_duration` | the status, the primary endpoint (`bfcr`, `efcr`, `survival`, `biomass_gain`) and 1 to 1095 days |
| `chk_experiments_template` | a template is a draft with no day 0 and no allocation |
| `chk_experiments_started` | a started experiment has its day 0, hypothesis, primary endpoint and allocation |
| `chk_experiments_allocation` | the method, seed and reason belong together: randomised has the seed, by hand has the reason, none has neither |
| `uq_experiment_factors_name_live`, `uq_experiment_factors_diet`, `chk_experiment_factors_*` | a factor's name is unique in the experiment; one diet factor; the diet has no unit |
| `uq_experiment_levels_*`, `chk_experiment_levels_by_kind` | a level's label (or protocol) is unique in its factor; a diet level names a protocol and no label, another level has a label and no protocol |
| `fk_experiment_levels_factor_kind` (composite) | a level has the kind of its factor |
| `uq_experiment_group_levels_group_factor` | one level of each factor for a group |
| `fk_experiment_group_levels_group` / `_factor` / `_level` (composite) | the group and the factor are of one experiment and the level is of that factor: a wrong row would put another trial's level in a group |
| `uq_experiment_groups_name_live`, `chk_experiment_groups_role`, `uq_experiment_replicates_number_live`, `chk_experiment_replicates_number` | group names and replicate numbers are unique, the group's role and the replicate number are in range |
| `uq_experiment_members_user`, `uq_experiment_members_lead`, `chk_experiment_members_role` | a person once in a team, one lead |
| `trg_experiments_frozen` | an experiment is only ever inserted as a draft, a draft with placements is never made a template; once started, every column but the status, the name, the notes and the bookkeeping is fixed; the status goes only forward; the row is never deleted |
| `trg_experiment_{factors,levels,groups,group_levels,replicates}_frozen` | no insert, update or delete of the design's parts unless the experiment is a draft |
| `trg_experiment_replicate_units_frozen` | a draft's placements are free; a running experiment may get a new placement and shorten one (`until_on`, never longer) and say why (`left_reason`); a closed one allows nothing; a started placement is never deleted; a template has none |
| PROTECT and the delete plan | a tank, a protocol, a site or a species that an experiment names is not deleted while it does; a draft is deleted with its design |

A change of the user columns alone (`created_by`, `updated_by`, `deleted_by`) always passes: removing a person from the system sets
them to NULL and must not be blocked by what they once created.

## What the code holds, and `check_experiments`

What PostgreSQL cannot say without copying columns across tables is held by the services and `design.problems` (a tank on the
site, a window inside the days, a level of every factor, a lead, the diet assigned at the start) and **checked from scratch** by
`manage.py check_experiments` (`experiments/integrity.py`), which the test suite runs after its scenarios. It finds, for every
started experiment: the errors of `design.HOLDS_AFTER_START` (a group without replicates or without a level of a factor, a tank off the
site or booked outside the days, an allocation missing), a tank deleted while it is in an experiment, a team without a lead and, while it runs,
a placement of a diet group **without its live feeding assignment** (the diet's protocol, from the placement's first day to its last).

## The chip beside a tank

`farm/placements.py` is a registry like the medicine withdrawal's (`farm/handling/withdrawal.py`): an app registers a provider in its `ready()`, and
Production units (the row and the drawer) and the meal board show what the providers say of each unit. The experiments' provider (`read.chips`) says
"E-2026-001 · Control · R2" for a tank booked to an experiment on its site's today, a draft included, for those who may read experiments. The
registry **fails open**: no provider, or one that raises or breaks its transaction (it runs in its own savepoint), gives no chip and changes nothing
else. `experiments/tests/test_placements.py` and `farm/tests/test_placements.py` test the registration, the day of each unit, the permission, the
query count and that a failing provider never breaks a farm page.

## Derived, never stored

`read.cells` (the one definition of "which tank, which days, which replicate"), `read.booked`, `read.placements`, `read.overview`,
`read.data`, `read.progress`, `read.error_df` (replicates less groups, the pooled degrees of freedom) and `read.deviations`. Every figure goes through the
farm's own reads (`feeding.read.windows_in`, `stock.read.stock_of`, `stock.read.Presence`, `ration.Policy`), and the queries do not
grow with the tanks (tests count them for 6 and 60). Cleaner fish, and any batch of another species, never count: the figures read only the
batches of the experiment's species, and a unit's feeding records are read for the fish the species is (the record's `target`: production fish or
cleaner fish beside them), so a cleaner fish's feed is never the trial's feed in the Data tab or in a deviation.

## Locking

Batches, then tanks (in primary-key order, `farm.stock.services.locked`), then the experiment **last**. Every write of a form compares the stored
`version` under `select_for_update`: a form older than the stored version is refused, and the person is told someone else changed it. A
form sent twice (a double click) creates one record (`entry_key`).

## Where the code differs from the plan

The plan (`plan/area1/PLAN.md`) and the code disagree in a few places, and the code wins:

- `Cell` carries the placement's own id (a tank is released or replaced by it); `Finding` carries what it is about, so that two findings of one rule stay two.
- `release_unit` and `replace_unit` take the experiment's `version` (a form built on an older one is refused).
- `assignments.save(user, made)` and `assignments.end(user, row, last_day)` take no `recorded` parameter: `assignments.recorded` is the one list of the fields the log shows.
- There is no `experiments/views.py`: the pages are `ResourceView`s in `resources.py`, as the other tabs are.
- `day_0_too_old` is asked of a draft only (the plan asked it of every experiment: a started one is not too old for the days that have passed).
- `deviations` are `foreign_batch`, `transfer`, `feed_off_band` and `ration_off_diet` (the plan's D1, D2, D4, D5). A transfer **between two replicates**, or between a tank of the experiment and one that is not in it, is a deviation; a move
  inside one replicate (a replacement's) is not: the plan's "between two placements" would have flagged every replacement. Only a protocol assigned to a
  **batch in the unit** beats the unit's (the farm's rule: batch in unit, then the unit, then the whole batch), so a protocol
  assigned to a batch alone is not a deviation.
- The placement badge (plan step 14) is built as the plan says, with one change: the provider is given the units and the person (`provider(units, user)`), not
  unit ids and a day, because each unit is read on its own site's day and only those who may read experiments see it.

## What to check live

Tests run in Docker against a test database; these need a real browser and server, a real clock and real data (nothing of this has been done):

1. **The owner's example end to end**: 6 systems, 3 diets × 2 replicates; the design, the randomisation (the seed written down), the places, the Start with its warnings, then a day of feeding on the meal board following each tank's diet.
2. **Two browsers racing a Start**, and a Start against a feeding write: one wins, the other is told.
3. **A student's and a technician's walk-through**: what each sees and may do on every tab (the matrix is data in Roles).
4. **Phone width and the Turkish and Norwegian labels** on the grids (the design and places grids wrap; the buttons on the Data tab; the dialogs).
5. **A 180-day, 60-tank trial**: `EXPLAIN` of the `placements` read and the overview walk; the Overview page time.
6. **Both merge orders** with the water sampling points (the Data tab's Water link, `farm/water/read.py`) and the withdrawal-scope branch (`farm/handling/check.py`, `farm/health/withdrawal.py`, farm migrations 0020 and 0021): then `check_stock` and `check_experiments`.
7. **A release and a replacement on the running trial** on a real tank: the diet row ends, the new tank's ration follows from its first day, and the Overview names the gap when there is no weighing at the move.
8. **The activity log** of a started experiment (the `Places`, `Reason it left`, `Status` and `Warnings acknowledged` rows) read in all three languages.
9. **The database viewer's Research section** shows the eight tables with their constraints and descriptions; the admin restores an experiment (not its parts).
