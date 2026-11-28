-- The app role's rights on what exists, made again after every migration by the release step
-- (deploy/web/release.sh), as the owner role. The default privileges of roles.sql already give it what the owner
-- makes; this is the same set once more, so that a table made another way (by hand, by a restore) is not left out,
-- and whatever else was granted (TRUNCATE, REFERENCES, TRIGGER) is taken back. Idempotent.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO balik_app;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM balik_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO balik_app;
REVOKE UPDATE ON ALL SEQUENCES IN SCHEMA public FROM balik_app;
-- The append-only tables (a trigger refuses every UPDATE and DELETE: the activity log, the alarms' history, the
-- withdrawal acknowledgements, the filed reports' snapshots) lose the rights too, so that the refusal is the
-- database's rights before it is the trigger's (security review S3). `alarms` keeps UPDATE: the alarm service locks
-- an alarm's row (SELECT ... FOR UPDATE), which needs it; its trigger still refuses every change.
REVOKE UPDATE, DELETE ON audit_log, alarm_clearances, alarm_notifications, alarm_delivery_attempts, alarm_escalations,
  alarm_acknowledgements, withdrawal_acknowledgements, regulatory_report_snapshots FROM balik_app;
REVOKE DELETE ON alarms FROM balik_app;
-- The open alarms' queue (alarms 0025) is written by its two triggers only, which run as their owner (SECURITY
-- DEFINER): the app may read it, never write it, so no code can drop a live alarm from it or keep a cleared one in it
-- (review 2, H2). `manage.py check --database default` compares it with the clearances (alarms.W001).
REVOKE INSERT, UPDATE, DELETE ON alarm_open FROM balik_app;
-- The same for the sensor events still to mirror (alarms 0026, review 3, M1): written by its triggers only, so no code
-- can drop an event no alarm mirrors yet; compared with the alarms by alarms.W002.
REVOKE INSERT, UPDATE, DELETE ON alarm_unmirrored_events FROM balik_app;
-- No temporary tables for the app (roles.sql; a farm made before it was granted TEMPORARY, taken back here): no code
-- makes one, and a trigger of its own on one could hand a SECURITY DEFINER trigger function a table of its choosing
-- (core.operations.DefinerTrigger, which also takes each such function's EXECUTE from PUBLIC).
DO $$ BEGIN
    EXECUTE 'REVOKE TEMPORARY ON DATABASE ' || quote_ident(current_database()) || ' FROM balik_app';
END $$;
