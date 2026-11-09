"""A severity's alarm rule is never deleted (cross review F6): a soft delete is refused by a check, a DELETE by a trigger.
A row lost all the same (a restore) is survived by the evaluation (alarms/rules.py) and alarmed (sources.supervise)."""
from django.db import migrations, models

KEEP = """
CREATE FUNCTION alarm_severity_policies_kept() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'An alarm severity rule is changed, never deleted: the alarms of severity % need it.', OLD.severity
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_alarm_severity_policies_kept BEFORE DELETE ON alarm_severity_policies
    FOR EACH ROW EXECUTE FUNCTION alarm_severity_policies_kept();
"""
DROP = """
DROP TRIGGER IF EXISTS trg_alarm_severity_policies_kept ON alarm_severity_policies;
DROP FUNCTION IF EXISTS alarm_severity_policies_kept();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0005_one_open_alarm'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('is_deleted', False)),
                                              name='chk_alarm_severity_policies_kept'),
        ),
        migrations.RunSQL(KEEP, reverse_sql=DROP),
    ]
