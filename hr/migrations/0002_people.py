import core.ranges
import django.contrib.postgres.constraints
import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0004_production_departments'),
        ('hr', '0001_office_departments'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # The exclusion constraints compare an equal id and an overlapping range in one index. The extension is shared with the
        # farm's own exclusion constraints, so going back never drops it (it would fail while they exist, and it is not ours).
        migrations.RunSQL('CREATE EXTENSION IF NOT EXISTS btree_gist', reverse_sql=migrations.RunSQL.noop),
        migrations.CreateModel(
            name='Employee',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('employee_number', models.CharField(max_length=20, validators=[django.core.validators.RegexValidator('^[A-Za-z0-9_./-]+$', 'Use letters, digits, dots, hyphens, slashes and underscores only.')], verbose_name='Employee number')),
                ('first_name', models.CharField(blank=True, max_length=100, verbose_name='First name')),
                ('last_name', models.CharField(blank=True, max_length=100, verbose_name='Last name')),
                ('employment_type', models.CharField(choices=[('staff', 'Staff'), ('student', 'Student'), ('researcher', 'Researcher'), ('technician', 'Technician'), ('advisor', 'Advisor'), ('contractor', 'Contractor'), ('volunteer', 'Volunteer')], default='staff', max_length=20, verbose_name='Employment type')),
                ('joined_on', models.DateField(verbose_name='Joined on')),
                ('left_on', models.DateField(blank=True, null=True, verbose_name='Left on')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='employee', to=settings.AUTH_USER_MODEL, verbose_name='Account')),
            ],
            options={
                'verbose_name': 'employee',
                'verbose_name_plural': 'employees',
                'db_table': 'employees',
                'ordering': ['last_name', 'first_name', 'employee_number'],
                'permissions': [('all_employee', 'Can see every employee')],
            },
        ),
        migrations.CreateModel(
            name='Posting',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('title', models.CharField(blank=True, max_length=100, verbose_name='Title')),
                ('valid_from', models.DateField(verbose_name='From')),
                ('valid_until', models.DateField(blank=True, null=True, verbose_name='Until')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='postings', to='hr.employee', verbose_name='Employee')),
                ('office_department', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='postings', to='hr.officedepartment', verbose_name='Office department')),
                ('production_department', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='postings', to='farm.productiondepartment', verbose_name='Production department')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'placement',
                'verbose_name_plural': 'placements',
                'db_table': 'postings',
                'ordering': ['employee', '-valid_from'],
            },
        ),
        migrations.AddConstraint(
            model_name='employee',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('employee_number',), name='uq_employees_number_live', violation_error_message='Another employee already has this number.'),
        ),
        migrations.AddConstraint(
            model_name='employee',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('user',), name='uq_employees_user_live', violation_error_message='This account already belongs to another employee.'),
        ),
        migrations.AddConstraint(
            model_name='employee',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('first_name', ''), ('last_name', ''), ('user__isnull', False)), models.Q(('user__isnull', True), models.Q(('last_name', ''), _negated=True)), _connector='OR'), name='chk_employees_identity', violation_error_message='A person with an account is named by it; one without needs a last name.'),
        ),
        migrations.AddConstraint(
            model_name='employee',
            constraint=models.CheckConstraint(condition=models.Q(('left_on__isnull', True), ('left_on__gte', models.F('joined_on')), _connector='OR'), name='chk_employees_period', violation_error_message='A person cannot leave before they joined.'),
        ),
        migrations.AddConstraint(
            model_name='employee',
            constraint=models.CheckConstraint(condition=models.Q(('employment_type__in', ['staff', 'student', 'researcher', 'technician', 'advisor', 'contractor', 'volunteer'])), name='chk_employees_type'),
        ),
        migrations.AddConstraint(
            model_name='employee',
            constraint=models.CheckConstraint(condition=models.Q(('employee_number__regex', '^[A-Za-z0-9_./-]+$')), name='chk_employees_number', violation_error_message='Use letters, digits, dots, hyphens, slashes and underscores only.'),
        ),
        migrations.AddIndex(
            model_name='posting',
            index=models.Index(fields=['valid_from'], name='postings_valid_f_39f649_idx'),
        ),
        migrations.AddConstraint(
            model_name='posting',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('office_department__isnull', True), ('production_department__isnull', False)), models.Q(('office_department__isnull', False), ('production_department__isnull', True)), _connector='OR'), name='chk_postings_one_department', violation_error_message='Choose one department: a production department or an office department.'),
        ),
        migrations.AddConstraint(
            model_name='posting',
            constraint=models.CheckConstraint(condition=models.Q(('valid_until__isnull', True), ('valid_until__gte', models.F('valid_from')), _connector='OR'), name='chk_postings_period', violation_error_message='A placement cannot end before it starts.'),
        ),
        migrations.AddConstraint(
            model_name='posting',
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(condition=models.Q(('is_deleted', False)), expressions=[(models.F('employee'), '='), (core.ranges.DateRange(models.F('valid_from'), models.F('valid_until'), models.Value('[]')), '&&')], name='excl_postings_employee_period', violation_error_message='This person is already placed in a department on some of these days.'),
        ),
    ]
