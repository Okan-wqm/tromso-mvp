"""One table for the key of every new-record form and the record it created (F-232, core.models.EntryKey)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_audit_severity'),
    ]

    operations = [
        migrations.CreateModel(
            name='EntryKey',
            fields=[
                ('key', models.UUIDField(primary_key=True, serialize=False)),
                ('entity_type', models.CharField(max_length=100)),
                ('entity_id', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'entry_keys',
            },
        ),
    ]
