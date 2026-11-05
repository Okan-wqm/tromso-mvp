import core.models
import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


# A department is never nested under itself or anything below it. The form says so on the field; this trigger
# refuses it whatever writes (a script, another form, a restore). It walks up through deleted departments too, so a
# restore cannot close a loop either.
NO_CYCLE = """
CREATE FUNCTION office_departments_no_cycle() RETURNS trigger AS $$
DECLARE
    ancestor uuid := NEW.parent_id;
    steps integer := 0;
BEGIN
    WHILE ancestor IS NOT NULL LOOP
        IF ancestor = NEW.id THEN
            RAISE EXCEPTION 'office department % cannot be nested under itself or under one below it', NEW.id
                USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_office_departments_no_cycle';
        END IF;
        steps := steps + 1;
        IF steps > 1000 THEN
            RAISE EXCEPTION 'office departments are nested too deep' USING ERRCODE = 'check_violation';
        END IF;
        SELECT parent_id INTO ancestor FROM office_departments WHERE id = ancestor;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_office_departments_no_cycle
    BEFORE INSERT OR UPDATE OF parent_id ON office_departments
    FOR EACH ROW EXECUTE FUNCTION office_departments_no_cycle();
"""

DROP_NO_CYCLE = """
DROP TRIGGER IF EXISTS trg_office_departments_no_cycle ON office_departments;
DROP FUNCTION IF EXISTS office_departments_no_cycle();
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('farm', '0004_production_departments'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OfficeDepartment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
                ('code', models.CharField(max_length=20, validators=[django.core.validators.RegexValidator('^[A-Z0-9_-]+$', 'Use capital letters, digits, hyphens and underscores only.')], verbose_name='Code')),
                ('status', models.CharField(choices=[('active', 'Active'), ('inactive', 'Inactive')], default='active', max_length=10, verbose_name='Status')),
                ('description', models.TextField(blank=True, verbose_name='Description')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by')),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by')),
                ('manager', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Manager')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='hr.officedepartment', verbose_name='Parent department')),
                ('site', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='office_departments', to='farm.site', verbose_name='Site')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by')),
            ],
            options={
                'verbose_name': 'office department',
                'verbose_name_plural': 'office departments',
                'db_table': 'office_departments',
                'ordering': ['name'],
                'indexes': [models.Index(fields=['status'], name='office_depa_status_612da5_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('code',), name='uq_office_departments_code_live', violation_error_message='Another office department already uses this code.'), models.UniqueConstraint(condition=models.Q(('is_deleted', False)), fields=('parent', 'name'), name='uq_office_departments_parent_name_live', nulls_distinct=False, violation_error_message='This department already has a department with this name.'), models.CheckConstraint(condition=models.Q(('parent__isnull', True), models.Q(('parent', models.F('id')), _negated=True), _connector='OR'), name='chk_office_departments_parent_not_self', violation_error_message='A department cannot be its own parent.'), models.CheckConstraint(condition=models.Q(('code__regex', '^[A-Z0-9_-]+$')), name='chk_office_departments_code', violation_error_message='Use capital letters, digits, hyphens and underscores only.'), models.CheckConstraint(condition=models.Q(('status__in', ['active', 'inactive'])), name='chk_office_departments_status')],
            },
            bases=(core.models.CodedMixin, core.models.TreeMixin, models.Model),
        ),
        migrations.RunSQL(NO_CYCLE, reverse_sql=DROP_NO_CYCLE),
    ]
