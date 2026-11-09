
import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def make_the_row(apps, schema_editor):
    """The one row, with the rules the farm had before the owner could set them: 31 days, no second approval, 15
    minutes."""
    apps.get_model('core', 'PlatformSettings').objects.get_or_create(singleton=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_entry_keys'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformSettings',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('singleton', models.BooleanField(default=True, editable=False)),
                ('correction_window_days', models.PositiveSmallIntegerField(default=31, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(3650)], verbose_name='Correction window (days)')),
                ('second_approval_withdrawal', models.BooleanField(default=False, verbose_name='A second person approves a withdrawal warning acknowledgement')),
                ('alarm_escalation_minutes', models.PositiveSmallIntegerField(default=15, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(1440)], verbose_name='Escalate an unacknowledged alarm after (minutes)')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'platform settings',
                'verbose_name_plural': 'platform settings',
                'db_table': 'platform_settings',
                'constraints': [models.UniqueConstraint(fields=('singleton',), name='uq_platform_settings_singleton'), models.CheckConstraint(condition=models.Q(('singleton', True)), name='chk_platform_settings_singleton'), models.CheckConstraint(condition=models.Q(('correction_window_days__gte', 1), ('correction_window_days__lte', 3650)), name='chk_platform_settings_window'), models.CheckConstraint(condition=models.Q(('alarm_escalation_minutes__gte', 1), ('alarm_escalation_minutes__lte', 1440)), name='chk_platform_settings_escalation')],
            },
        ),
        migrations.RunPython(make_the_row, migrations.RunPython.noop),
    ]
