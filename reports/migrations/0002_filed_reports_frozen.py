"""A filed report is the farm's record of what it told an authority: the database itself refuses to change or delete
it, its frozen content, or the rows of its answers (docs/regulatory-reports.md, 5.3). The checks the forms and the
services make give the readable messages; these make the rule hold whatever writes. The user columns stay writable,
so a user removed from the system (people are deactivated, but Django may still set them to NULL) does not block."""
from django.db import migrations

FROZEN = """
CREATE FUNCTION regulatory_report_frozen() RETURNS trigger AS $$
BEGIN
    IF OLD.submitted_at IS NULL THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'regulatory report % was filed: it is never deleted', OLD.id;
    END IF;
    IF (to_jsonb(NEW) - 'created_by_id' - 'updated_by_id' - 'deleted_by_id')
       IS DISTINCT FROM (to_jsonb(OLD) - 'created_by_id' - 'updated_by_id' - 'deleted_by_id') THEN
        RAISE EXCEPTION 'regulatory report % was filed: it cannot change', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_regulatory_reports_frozen
    BEFORE UPDATE OR DELETE ON regulatory_reports
    FOR EACH ROW EXECUTE FUNCTION regulatory_report_frozen();

CREATE FUNCTION regulatory_report_snapshot_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'regulatory_report_snapshots is append-only: what was filed cannot be changed or deleted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_regulatory_report_snapshots_append_only
    BEFORE UPDATE OR DELETE ON regulatory_report_snapshots
    FOR EACH ROW EXECUTE FUNCTION regulatory_report_snapshot_append_only();

CREATE FUNCTION regulatory_report_row_frozen() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(NEW) - 'created_by_id') IS NOT DISTINCT FROM (to_jsonb(OLD) - 'created_by_id') THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'INSERT' AND EXISTS (
        SELECT 1 FROM regulatory_reports WHERE id = OLD.report_id AND submitted_at IS NOT NULL) THEN
        RAISE EXCEPTION 'the answers of a filed regulatory report cannot change';
    END IF;
    IF TG_OP <> 'DELETE' AND EXISTS (
        SELECT 1 FROM regulatory_reports WHERE id = NEW.report_id AND submitted_at IS NOT NULL) THEN
        RAISE EXCEPTION 'the answers of a filed regulatory report cannot change';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
""" + ''.join(f"""
CREATE TRIGGER trg_{table}_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION regulatory_report_row_frozen();
""" for table in ('regulatory_report_resistance_suspicions', 'regulatory_report_sensitivity_tests',
                  'regulatory_report_unit_answers'))

DROP = ''.join(f"""
DROP TRIGGER IF EXISTS trg_{table}_frozen ON {table};
""" for table in ('regulatory_report_resistance_suspicions', 'regulatory_report_sensitivity_tests',
                  'regulatory_report_unit_answers')) + """
DROP FUNCTION IF EXISTS regulatory_report_row_frozen();
DROP TRIGGER IF EXISTS trg_regulatory_report_snapshots_append_only ON regulatory_report_snapshots;
DROP FUNCTION IF EXISTS regulatory_report_snapshot_append_only();
DROP TRIGGER IF EXISTS trg_regulatory_reports_frozen ON regulatory_reports;
DROP FUNCTION IF EXISTS regulatory_report_frozen();
"""


class Migration(migrations.Migration):
    dependencies = [('reports', '0001_regulatory_reports')]

    operations = [migrations.RunSQL(FROZEN, reverse_sql=DROP)]
