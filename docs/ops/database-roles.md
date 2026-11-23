# Database roles

Made by `deploy/db/sql/roles.sql` at the database's first start (as the superuser), kept by
`deploy/db/sql/grants.sql` after every migration (the release step), proved by `deploy/scripts/check-roles.sh` (on a
farm's server after install and after every upgrade; on every run of the go-live stack workflow).

| Role | Signs in from | May | May not |
|---|---|---|---|
| `postgres` | nothing that runs; the `restore` service, a person's maintenance | everything (superuser) | (not used by any service in normal running) |
| `balik_owner` | the `release` step | own the database, the schema and every table: migrate | create roles or databases; it is no superuser |
| `balik_app` | `web`, `jobs` (and the alarm worker) | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on the tables, use the sequences | `TRUNCATE`, `CREATE` (tables, indexes, schemas), `ALTER`, `DROP`, `REFERENCES`, `TRIGGER`, disable a trigger, grant |
| `sensors_ingest` | `ingest` | what migrations `sensors/0001`, `0002`, `0006` grant: read its contract (`sensors_ingest_config`, `sensors_contract`, `sensors_quality_flag`), insert readings, read and write its runtime tables | read any other table, delete or update readings, any DDL |
| `balik_backup` | `backup` | read every row (`pg_read_all_data`), stream the WAL (`REPLICATION`) | write anything, any DDL |

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
  `dc run --rm --no-deps web python manage.py <command>`.
- `manage.py sensors_ingest_role` is a development tool on a farm's server: the ingest's role signs in with the
  password `roles.sql` gave it.
- Hardening left for later: the append-only tables (the activity log, the alarms' history) are guarded by triggers;
  their `UPDATE` and `DELETE` could also be taken from the app role once every write path is confirmed to need none.
