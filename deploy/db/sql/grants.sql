-- The app role's rights on what exists, made again after every migration by the release step
-- (deploy/web/release.sh), as the owner role. The default privileges of roles.sql already give it what the owner
-- makes; this is the same set once more, so that a table made another way (by hand, by a restore) is not left out,
-- and whatever else was granted (TRUNCATE, REFERENCES, TRIGGER) is taken back. Idempotent.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO balik_app;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM balik_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO balik_app;
REVOKE UPDATE ON ALL SEQUENCES IN SCHEMA public FROM balik_app;
