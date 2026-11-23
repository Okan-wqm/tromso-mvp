"""The read log of confidential records (core.AccessEvent), append-only like the activity log (core migration 0003)."""
import django.utils.timezone
from django.db import migrations, models

APPEND_ONLY = """
CREATE FUNCTION core_access_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'core_access_events is append-only: rows cannot be changed or deleted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_core_access_events_append_only
    BEFORE UPDATE OR DELETE ON core_access_events
    FOR EACH ROW EXECUTE FUNCTION core_access_events_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS trg_core_access_events_append_only ON core_access_events;
DROP FUNCTION IF EXISTS core_access_events_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [('core', '0013_unknown_withdrawal_ceiling')]

    operations = [
        migrations.CreateModel(
            name='AccessEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='When')),
                ('user_id', models.IntegerField(blank=True, null=True, verbose_name='Person id')),
                ('user_name', models.CharField(max_length=150, verbose_name='Person')),
                ('kind', models.CharField(choices=[('view', 'Viewed'), ('export', 'Exported'), ('denied', 'Refused'),
                                                   ('oversee', 'Oversaw'), ('support', 'Support read')],
                                          max_length=8, verbose_name='Kind')),
                ('entity_type', models.CharField(max_length=64, verbose_name='Record type')),
                ('entity_id', models.CharField(max_length=64, verbose_name='Record')),
                ('part', models.CharField(blank=True, max_length=8, verbose_name='Part')),
                ('route', models.CharField(blank=True, max_length=120, verbose_name='Page')),
            ],
            options={
                'verbose_name': 'read of a confidential record',
                'verbose_name_plural': 'reads of confidential records',
                'db_table': 'core_access_events',
                'ordering': ['-at', '-id'],
                'indexes': [models.Index(fields=['entity_type', 'entity_id', 'at'], name='idx_access_events_entity'),
                            models.Index(fields=['user_name', 'at'], name='idx_access_events_user')],
                'constraints': [models.CheckConstraint(
                    condition=models.Q(kind__in=['view', 'export', 'denied', 'oversee', 'support']),
                    name='chk_access_events_kind')],
            },
        ),
        migrations.RunSQL(APPEND_ONLY, reverse_sql=DROP),
    ]
