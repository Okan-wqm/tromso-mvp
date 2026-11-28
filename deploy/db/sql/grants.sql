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
-- The rows' versions (core.versions) are written by the kept tables' triggers alone, whose functions run as the owner
-- (core migration 0021): the app role reads them and may not insert, change or delete one, so what a row was cannot be
-- rewritten from a page or a script.
REVOKE INSERT, UPDATE, DELETE ON core_row_versions FROM balik_app;
