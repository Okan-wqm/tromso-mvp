"""The employment rule in the database, whatever writes: a person's live plans, held leave (pending or approved) and
punches lie between their first and last day. hr.services.check_employed and employment_conflicts say it first, with a
sentence; these triggers are the floor under them.

Constraint triggers, deferred to the commit: leaving the company sets the last day and then removes the later plans and
cancels the later pending leave in the same transaction (hr.services.align_placements), so the rule is read when that is
done. A punch is an instant and its day is on the site's clock, which the database does not know: the floor is the UTC
day with a day of slack either side; the exact day is the application's (hr.services.punch_day). Rows written before
this migration are not checked until they or the person change."""
from django.db import migrations

EMPLOYMENT = """
CREATE FUNCTION hr_employment_holds(person uuid) RETURNS void AS $$
DECLARE
    joined date;
    gone date;
BEGIN
    SELECT e.joined_on, e.left_on INTO joined, gone FROM employees e WHERE e.id = person;
    IF joined IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM shift_assignments s WHERE s.employee_id = person AND NOT s.is_deleted
               AND (s.day < joined OR (gone IS NOT NULL AND s.day > gone)))
       OR EXISTS (SELECT 1 FROM leave_requests l WHERE l.employee_id = person AND NOT l.is_deleted
                  AND l.status IN ('pending', 'approved')
                  AND (l.first_day < joined OR (gone IS NOT NULL AND l.last_day > gone)))
       OR EXISTS (SELECT 1 FROM attendance_records a WHERE a.employee_id = person AND NOT a.is_deleted
                  AND (a.clock_in < ((joined - 1)::timestamp AT TIME ZONE 'UTC')
                       OR (gone IS NOT NULL AND a.clock_in >= ((gone + 2)::timestamp AT TIME ZONE 'UTC')))) THEN
        RAISE EXCEPTION 'A plan, leave or punch of employee % lies outside their employment', person
            USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_employment_holds';
    END IF;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGERS = """
CREATE FUNCTION hr_employment_of_record() RETURNS trigger AS $$
BEGIN
    PERFORM hr_employment_holds(NEW.employee_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION hr_employment_of_person() RETURNS trigger AS $$
BEGIN
    PERFORM hr_employment_holds(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_shift_assignments_employment AFTER INSERT OR UPDATE ON shift_assignments
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hr_employment_of_record();
CREATE CONSTRAINT TRIGGER trg_leave_requests_employment AFTER INSERT OR UPDATE ON leave_requests
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hr_employment_of_record();
CREATE CONSTRAINT TRIGGER trg_attendance_records_employment AFTER INSERT OR UPDATE ON attendance_records
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hr_employment_of_record();
CREATE CONSTRAINT TRIGGER trg_employees_employment AFTER UPDATE OF joined_on, left_on ON employees
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hr_employment_of_person();
"""

DROP = """
DROP TRIGGER IF EXISTS trg_employees_employment ON employees;
DROP TRIGGER IF EXISTS trg_attendance_records_employment ON attendance_records;
DROP TRIGGER IF EXISTS trg_leave_requests_employment ON leave_requests;
DROP TRIGGER IF EXISTS trg_shift_assignments_employment ON shift_assignments;
DROP FUNCTION IF EXISTS hr_employment_of_person();
DROP FUNCTION IF EXISTS hr_employment_of_record();
DROP FUNCTION IF EXISTS hr_employment_holds(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [('hr', '0010_restore_preset_rights')]

    operations = [migrations.RunSQL(EMPLOYMENT + TRIGGERS, reverse_sql=DROP)]
