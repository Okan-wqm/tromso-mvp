"""The activity log's order made total: newest first, then by id for entries of the same moment, so a list of it never
depends on how its statement was planned (core.models.AuditLog.Meta)."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_audit_works'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='auditlog',
            options={'ordering': ['-created_at', '-id'],
                     'permissions': [('browse_database', 'Can browse the database')]},
        ),
    ]
