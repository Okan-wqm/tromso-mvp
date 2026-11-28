-- The farm database's roles (docs/ops/database-roles.md). Run once, by the database image's first start
-- (deploy/db/init/100-balik-roles.sh), as the superuser, in the farm's database; and by deploy/scripts/restore.sh on
-- the server a backup is restored to. Each password is the first line of its Docker secret: nothing is typed here.
--
--   balik_owner     owns the database, its schema and every table: the release step migrates as it. Not a superuser,
--                   may not create roles or databases.
--   balik_app       the web server and its jobs: reads and writes rows (SELECT, INSERT, UPDATE, DELETE) and nothing
--                   else: no CREATE, ALTER, DROP or TRUNCATE, no REFERENCES or TRIGGER (deploy/scripts/check-roles.sh).
--   sensors_ingest  the MQTT ingest: what migrations sensors/0001, 0002 and 0006 grant it (reads its contract, writes
--                   the readings and its runtime tables), nothing more. Made here so that it can sign in; the
--                   migration finds it and only grants.
--   balik_backup    pg_dump and pg_basebackup (deploy/backup): reads every row (pg_read_all_data) and streams the WAL
--                   (REPLICATION); writes nothing.
\set ON_ERROR_STOP on
-- A failed statement is written to the server's log with its text, and these hold passwords: this session logs none.
SET log_min_error_statement = panic;
SET log_statement = 'none';
\set owner_password `head -n 1 /run/secrets/db_owner_password`
\set app_password `head -n 1 /run/secrets/db_app_password`
\set ingest_password `head -n 1 /run/secrets/db_ingest_password`
\set backup_password `head -n 1 /run/secrets/db_backup_password`
SELECT current_database() AS dbname \gset

CREATE ROLE balik_owner LOGIN PASSWORD :'owner_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE balik_app LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE sensors_ingest LOGIN PASSWORD :'ingest_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE balik_backup LOGIN REPLICATION PASSWORD :'backup_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT pg_read_all_data TO balik_backup;

-- The extensions the migrations ask for (core/0001 timescaledb, hr/0002 btree_gist): TimescaleDB may be created by a
-- superuser only, so both are made here; the migrations' CREATE EXTENSION IF NOT EXISTS then finds them.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS btree_gist;
-- No usage reports to Timescale (also a server setting in deploy/compose.yml).
ALTER DATABASE :"dbname" SET timescaledb.telemetry_level = off;

-- The database and its schema belong to the owner role: every table the migrations make is its.
ALTER DATABASE :"dbname" OWNER TO balik_owner;
ALTER SCHEMA public OWNER TO balik_owner;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"dbname" TO balik_app;
GRANT CONNECT ON DATABASE :"dbname" TO sensors_ingest, balik_backup;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO balik_app, sensors_ingest;

-- What the owner makes from now on is the app's to read and write, never to change the shape of.
ALTER DEFAULT PRIVILEGES FOR ROLE balik_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO balik_app;
ALTER DEFAULT PRIVILEGES FOR ROLE balik_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO balik_app;
-- A function the owner makes is not everyone's to call: a SECURITY DEFINER trigger function would otherwise be one any
-- role could hang on a trigger of its own temporary table (core.operations.DefinerTrigger). Firing a trigger needs no
-- EXECUTE.
ALTER DEFAULT PRIVILEGES FOR ROLE balik_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
