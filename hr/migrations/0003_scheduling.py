import core.fields
import core.models
import django.core.validators
import django.db.models.deletion
import hr.models.scheduling
import uuid
from django.conf import settings
from django.db import migrations, models


# A break is shorter than the shift. A shift that ends at or before its start ends the next day, so its length is the
# difference of the two times taken modulo a day; the database holds it because two columns and a function say it and
# a form is not the only writer. (An expression CHECK on time columns: PostgreSQL accepts it, the ORM cannot spell it.)
BREAK_SHORTER = """
ALTER TABLE shifts ADD CONSTRAINT chk_shifts_break_shorter CHECK (
    break_minutes < (((EXTRACT(EPOCH FROM (ends_at - starts_at))::integer / 60) + 1440) % 1440)
);
"""
DROP_BREAK_SHORTER = "ALTER TABLE shifts DROP CONSTRAINT IF EXISTS chk_shifts_break_shorter;"


def make_the_row(apps, schema_editor):
    """The one seed: the scheduling settings row with its defaults (no shift, holiday or leave type is seeded)."""
    apps.get_model('hr', 'SchedulingSettings').objects.get_or_create(singleton=True)


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0004_production_departments'),
        ('hr', '0002_people'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Holiday',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('day', models.DateField(verbose_name='Day')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('site', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='holidays', to='farm.site', verbose_name='Site')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'holiday',
                'verbose_name_plural': 'holidays',
                'db_table': 'holidays',
                'ordering': ['day', 'name'],
                'indexes': [models.Index(fields=['day'], name='holidays_day_e2066d_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('day', 'site'), name='uq_holidays_day_site_live', nulls_distinct=False, violation_error_message='This day is already a holiday for this site.')],
            },
        ),
        migrations.CreateModel(
            name='SchedulingSettings',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('singleton', models.BooleanField(default=True, editable=False)),
                ('standard_week_minutes', models.PositiveIntegerField(default=2400, validators=[django.core.validators.MaxValueValidator(10080)], verbose_name='Standard week (minutes)')),
                ('min_rest_minutes', models.PositiveIntegerField(default=660, validators=[django.core.validators.MaxValueValidator(1440)], verbose_name='Minimum rest between shifts (minutes)')),
                ('max_consecutive_days', models.PositiveSmallIntegerField(default=6, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(14)], verbose_name='Most working days in a row')),
                ('rest_rule', models.CharField(choices=[('warn', 'Warn'), ('block', 'Block')], default='warn', max_length=5, verbose_name='A short rest, a long week or too many days in a row')),
                ('working_weekdays', core.fields.ChoiceArrayField(base_field=models.PositiveSmallIntegerField(choices=[(0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')]), default=hr.models.scheduling.default_weekdays, verbose_name='Working weekdays')),
                ('punch_window_minutes', models.PositiveSmallIntegerField(default=120, validators=[django.core.validators.MaxValueValidator(720)], verbose_name='Punch window (minutes)')),
                ('absent_after_minutes', models.PositiveSmallIntegerField(default=30, validators=[django.core.validators.MaxValueValidator(240)], verbose_name='Absent after (minutes)')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'scheduling settings',
                'verbose_name_plural': 'scheduling settings',
                'db_table': 'scheduling_settings',
                'constraints': [models.UniqueConstraint(fields=('singleton',), name='uq_scheduling_settings_singleton'), models.CheckConstraint(condition=models.Q(('singleton', True)), name='chk_scheduling_settings_singleton'), models.CheckConstraint(condition=models.Q(('standard_week_minutes__lte', 10080)), name='chk_scheduling_week'), models.CheckConstraint(condition=models.Q(('min_rest_minutes__lte', 1440)), name='chk_scheduling_rest'), models.CheckConstraint(condition=models.Q(('max_consecutive_days__gte', 1), ('max_consecutive_days__lte', 14)), name='chk_scheduling_consecutive'), models.CheckConstraint(condition=models.Q(('rest_rule__in', ['warn', 'block'])), name='chk_scheduling_rule'), models.CheckConstraint(condition=models.Q(('working_weekdays__contained_by', [0, 1, 2, 3, 4, 5, 6]), ('working_weekdays__len__gt', 0)), name='chk_scheduling_weekdays'), models.CheckConstraint(condition=models.Q(('punch_window_minutes__lte', 720)), name='chk_scheduling_punch_window'), models.CheckConstraint(condition=models.Q(('absent_after_minutes__lte', 240)), name='chk_scheduling_absent_after')],
            },
        ),
        migrations.CreateModel(
            name='Shift',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('name', models.CharField(max_length=50, verbose_name='Name')),
                ('code', models.CharField(max_length=20, validators=[django.core.validators.RegexValidator('^[A-Z0-9_-]+$', 'Use capital letters, digits, hyphens and underscores only.')], verbose_name='Code')),
                ('starts_at', models.TimeField(verbose_name='Starts at')),
                ('ends_at', models.TimeField(verbose_name='Ends at')),
                ('break_minutes', models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(240)], verbose_name='Break (minutes)')),
                ('grace_minutes', models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(120)], verbose_name='Grace (minutes)')),
                ('tone', models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(8)], verbose_name='Tone')),
                ('status', models.CharField(choices=[('active', 'Active'), ('inactive', 'Inactive')], default='active', max_length=10, verbose_name='Status')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'shift',
                'verbose_name_plural': 'shifts',
                'db_table': 'shifts',
                'ordering': ['starts_at', 'code'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('code',), name='uq_shifts_code_live', violation_error_message='Another shift already uses this code.'), models.CheckConstraint(condition=models.Q(('code__regex', '^[A-Z0-9_-]+$')), name='chk_shifts_code', violation_error_message='Use capital letters, digits, hyphens and underscores only.'), models.CheckConstraint(condition=models.Q(('starts_at', models.F('ends_at')), _negated=True), name='chk_shifts_span', violation_error_message='A shift cannot start and end at the same time.'), models.CheckConstraint(condition=models.Q(('break_minutes__gte', 0), ('break_minutes__lte', 240)), name='chk_shifts_break', violation_error_message='The break is between 0 and 240 minutes.'), models.CheckConstraint(condition=models.Q(('grace_minutes__gte', 0), ('grace_minutes__lte', 120)), name='chk_shifts_grace', violation_error_message='The grace is between 0 and 120 minutes.'), models.CheckConstraint(condition=models.Q(('tone__gte', 1), ('tone__lte', 8)), name='chk_shifts_tone', violation_error_message='The tone is between 1 and 8.'), models.CheckConstraint(condition=models.Q(('status__in', ['active', 'inactive'])), name='chk_shifts_status')],
            },
            bases=(core.models.CodedMixin, models.Model),
        ),
        migrations.RunSQL(BREAK_SHORTER, reverse_sql=DROP_BREAK_SHORTER),
        migrations.RunPython(make_the_row, migrations.RunPython.noop),
    ]
