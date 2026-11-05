import core.models
import core.ranges
import django.contrib.postgres.constraints
import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


# Nobody decides their own leave: the service refuses it, and this trigger holds it whatever writes (a script, a restore). A
# request that needs no approval is granted with no decider, so `decided_by` stays empty for it.
NO_SELF_DECISION = """
CREATE FUNCTION leave_requests_no_self_decision() RETURNS trigger AS $$
BEGIN
    IF NEW.decided_by_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM employees WHERE employees.id = NEW.employee_id AND employees.user_id = NEW.decided_by_id
    ) THEN
        RAISE EXCEPTION 'nobody decides their own leave request'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_leave_requests_no_self_decision';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_leave_requests_no_self_decision
    BEFORE INSERT OR UPDATE OF decided_by_id, employee_id ON leave_requests
    FOR EACH ROW EXECUTE FUNCTION leave_requests_no_self_decision();
"""

DROP_NO_SELF_DECISION = """
DROP TRIGGER IF EXISTS trg_leave_requests_no_self_decision ON leave_requests;
DROP FUNCTION IF EXISTS leave_requests_no_self_decision();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0004_roster'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LeaveType',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
                ('code', models.CharField(max_length=20, validators=[django.core.validators.RegexValidator('^[A-Z0-9_-]+$', 'Use capital letters, digits, hyphens and underscores only.')], verbose_name='Code')),
                ('annual_days', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Days a year')),
                ('needs_approval', models.BooleanField(default=True, verbose_name='Needs approval')),
                ('status', models.CharField(choices=[('active', 'Active'), ('inactive', 'Inactive')], default='active', max_length=10, verbose_name='Status')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'leave type',
                'verbose_name_plural': 'leave types',
                'db_table': 'leave_types',
                'ordering': ['name'],
            },
            bases=(core.models.CodedMixin, models.Model),
        ),
        migrations.CreateModel(
            name='LeaveRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('first_day', models.DateField(verbose_name='First day')),
                ('last_day', models.DateField(verbose_name='Last day')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled')], default='pending', max_length=10, verbose_name='Status')),
                ('reason', models.CharField(blank=True, max_length=500, verbose_name='Reason')),
                ('decision_note', models.CharField(blank=True, max_length=500, verbose_name='Decision note')),
                ('decided_at', models.DateTimeField(blank=True, null=True, verbose_name='Decided at')),
                ('entry_key', models.UUIDField(blank=True, editable=False, null=True, unique=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('decided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Decided by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='leave_requests', to='hr.employee', verbose_name='Employee')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
                ('leave_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requests', to='hr.leavetype', verbose_name='Leave type')),
            ],
            options={
                'verbose_name': 'leave request',
                'verbose_name_plural': 'leave requests',
                'db_table': 'leave_requests',
                'ordering': ['-first_day', 'employee'],
            },
        ),
        migrations.AddConstraint(
            model_name='leavetype',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('code',), name='uq_leave_types_code_live', violation_error_message='Another leave type already uses this code.'),
        ),
        migrations.AddConstraint(
            model_name='leavetype',
            constraint=models.CheckConstraint(condition=models.Q(('code__regex', '^[A-Z0-9_-]+$')), name='chk_leave_types_code', violation_error_message='Use capital letters, digits, hyphens and underscores only.'),
        ),
        migrations.AddConstraint(
            model_name='leavetype',
            constraint=models.CheckConstraint(condition=models.Q(('annual_days__isnull', True), ('annual_days__gte', 0), _connector='OR'), name='chk_leave_types_days', violation_error_message='The days a year cannot be negative.'),
        ),
        migrations.AddConstraint(
            model_name='leavetype',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ['active', 'inactive'])), name='chk_leave_types_status'),
        ),
        migrations.AddIndex(
            model_name='leaverequest',
            index=models.Index(fields=['first_day'], name='leave_reque_first_d_9b3361_idx'),
        ),
        migrations.AddIndex(
            model_name='leaverequest',
            index=models.Index(fields=['status'], name='leave_reque_status_401183_idx'),
        ),
        migrations.AddConstraint(
            model_name='leaverequest',
            constraint=models.CheckConstraint(condition=models.Q(('last_day__gte', models.F('first_day'))), name='chk_leave_requests_days', violation_error_message='The last day cannot be before the first.'),
        ),
        migrations.AddConstraint(
            model_name='leaverequest',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ['pending', 'approved', 'rejected', 'cancelled'])), name='chk_leave_requests_status'),
        ),
        migrations.AddConstraint(
            model_name='leaverequest',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ['pending', 'cancelled']), ('decided_at__isnull', False), _connector='OR'), name='chk_leave_requests_decided', violation_error_message='An approved or rejected request has the time it was decided.'),
        ),
        migrations.AddConstraint(
            model_name='leaverequest',
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(condition=models.Q(('is_deleted', False), ('status__in', ['pending', 'approved'])), expressions=[(models.F('employee'), '='), (core.ranges.DateRange(models.F('first_day'), models.F('last_day'), models.Value('[]')), '&&')], name='excl_leave_requests_employee_days', violation_error_message='This person already has a leave request for some of these days.'),
        ),
        migrations.RunSQL(NO_SELF_DECISION, reverse_sql=DROP_NO_SELF_DECISION),
    ]
