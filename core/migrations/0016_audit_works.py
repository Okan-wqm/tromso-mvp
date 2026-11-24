"""The works an activity-log entry's record lay in when it was written (core.audit.stamp), for the change token.

The column is added with an empty array as its database default, which PostgreSQL keeps in the catalog (no rewrite, no
row touched, so the log's append-only trigger never fires), and the default stays: a row written by raw SQL (a data
migration's own entry, core/migrations/_log.py) gets an empty stamp, as an entry about no sealed record has. Entries
written before this migration have none either: the token reads the newest entries, written from now on."""
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_access_event'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='works',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=64), blank=True,
                                                            default=list, editable=False),
        ),
        migrations.RunSQL("ALTER TABLE audit_log ALTER COLUMN works SET DEFAULT '{}'",
                          "ALTER TABLE audit_log ALTER COLUMN works DROP DEFAULT"),
    ]
