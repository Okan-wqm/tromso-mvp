# Database roles

Made by `deploy/db/sql/roles.sql` at the database's first start (as the superuser), kept by
`deploy/db/sql/grants.sql` after every migration (the release step), proved by `deploy/scripts/check-roles.sh` (on a
farm's server after install and after every upgrade; on every run of the go-live stack workflow).

| Role | Signs in from | May | May not |
|---|---|---|---|
| `postgres` | nothing that runs; the `restore` service, a person's maintenance | everything (superuser) | (not used by any service in normal running) |
| `balik_owner` | the `release` step | own the database, the schema and every table: migrate | create roles or databases; it is no superuser |
| `balik_app` | `web`, `jobs` (and the alarm worker) | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on the tables (but `UPDATE`/`DELETE` on the append-only ones, below), use the sequences | `TRUNCATE`, `CREATE` (tables, indexes, schemas), `ALTER`, `DROP`, `REFERENCES`, `TRIGGER`, disable a trigger, grant |
| `sensors_ingest` | `ingest` | what migrations `sensors/0001`, `0002`, `0006` grant: read its contract (`sensors_ingest_config`, `sensors_contract`, `sensors_quality_flag`), insert readings, read and write its runtime tables | read any other table, delete or update readings, any DDL |
| `balik_backup` | `backup` | read every row (`pg_read_all_data`), stream the WAL (`REPLICATION`) | write anything, any DDL. It can read the roles' password verifiers (`pg_authid`): a physical backup copies the whole server, them included, so whoever holds this role or the backups holds them too; the repository is encrypted and append-only for the farm |

What follows from it:

- A flaw in a page cannot drop, empty or reshape a table: the role the web server signs in as has no such right.
  The activity log's append-only trigger cannot be set aside by the app either (only the owner may).
- **Commands that need the owner** run in the release service's container (it signs in as `balik_owner`):
  ```
  dc run --rm --no-deps release python manage.py private_log_values --dry-run
  dc run --rm --no-deps release python manage.py erase_stranger_address <address> ...
  ```
  (`erase_stranger_address` sets the log's trigger aside inside its transaction, which needs the table's owner;
  `docs/erasure.md`.) Every other product command (README, Management commands) runs as the app role:
  `dc run --rm manage python manage.py <command>`.
- `manage.py sensors_ingest_role` is a development tool on a farm's server: the ingest's role signs in with the
  password `roles.sql` gave it.
- **The append-only tables** (the activity log, the alarms' history, the withdrawal acknowledgements, the filed reports'
  snapshots) are refused `UPDATE` and `DELETE` by the app role's rights as well as by their triggers (grants.sql). One
  exception: `alarms` keeps `UPDATE`, because the alarm service locks an alarm's row (`SELECT ... FOR UPDATE`, which
  needs it); its trigger still refuses every change. `check-roles.sh` tries them.
- **The alarms' queues** (`alarm_open`, the open alarms; `alarm_unmirrored_events`, the sensor events still to mirror)
  are written only by their triggers, whose functions run as the owner (SECURITY DEFINER,
  `core.operations.DefinerTrigger`); the app role may read them, never write them (grants.sql). So that
  no other role can call such a function with a table of its choosing, the operation that makes one takes its EXECUTE
  from PUBLIC (firing a trigger needs none), the app role may not make temporary tables (no `TEMPORARY`: roles.sql,
  grants.sql), and the function refuses to run for any table but its own, with the temporary schema last in its search
  path, so a table it names is always the public one. Every other function keeps PUBLIC's EXECUTE: the app calls them,
  itself (`core_rev_flush`) or through its own triggers (`core_rev_note`), with its own rights. `check-roles.sh` proves
  that neither runtime role may call a SECURITY DEFINER function or make a temporary table, and that the app writes a
  tracked table with its deferred triggers run, and that a sensor event the app writes is queued to be mirrored.
  Raw SQL that writes alarms, clearances or sensor events by an explicit id (a repair, a hand-made restore) runs with
  the alarm worker stopped: a row written while the one it names is still uncommitted in another transaction (the
  foreign keys are checked only at the commit) is not seen by that one's trigger, so a cleared alarm stays in the open
  alarms' queue (alarms 0025), and a mirrored event in the queue to mirror (0026). `manage.py check --database default`
  names such a row, with its repair (alarms.W001, W002).
