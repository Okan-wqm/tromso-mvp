import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def administration_becomes_other(apps, schema_editor):
    """`administration` was an organisational department; those belong to the HR module, not here."""
    apps.get_model('farm', 'ProductionDepartment').objects.filter(type='administration').update(type='other')


class Migration(migrations.Migration):
    """The farm's departments are production departments: the company's own departments (management,
    HR) come with the HR module. Renames the model, its table and the system's link; the data stays."""

    dependencies = [
        ('farm', '0003_systems'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(old_name='Department', new_name='ProductionDepartment'),
        migrations.AlterModelTable(name='productiondepartment', table='production_departments'),
        migrations.RenameField(model_name='system', old_name='department', new_name='production_department'),
        migrations.AlterField(
            model_name='productiondepartment',
            name='site',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='production_departments', to='farm.site',
            ),
        ),
        migrations.RemoveConstraint(model_name='productiondepartment', name='uq_departments_code_live'),
        migrations.RemoveConstraint(model_name='productiondepartment', name='uq_departments_site_name_live'),
        migrations.RemoveConstraint(model_name='productiondepartment', name='chk_departments_capacity'),
        migrations.RenameIndex(
            model_name='productiondepartment', new_name='production__type_3603d7_idx',
            old_name='departments_type_a94984_idx',
        ),
        migrations.RenameIndex(
            model_name='productiondepartment', new_name='production__status_555f89_idx',
            old_name='departments_status_e50229_idx',
        ),
        migrations.RunPython(administration_becomes_other, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='productiondepartment',
            name='type',
            field=models.CharField(
                choices=[
                    ('production', 'Production'), ('maintenance', 'Maintenance'),
                    ('quality_control', 'Quality control'), ('feed', 'Feed'), ('hatchery', 'Hatchery'),
                    ('nursery', 'Nursery'), ('grow_out', 'Grow-out'), ('broodstock', 'Broodstock'),
                    ('quarantine', 'Quarantine'), ('processing', 'Processing'), ('laboratory', 'Laboratory'),
                    ('other', 'Other'),
                ],
                default='production', max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='productiondepartment',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_deleted', False)), fields=('code',),
                name='uq_production_departments_code_live',
                violation_error_message='Another production department already uses this code.',
            ),
        ),
        migrations.AddConstraint(
            model_name='productiondepartment',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_deleted', False)), fields=('site', 'name'),
                name='uq_production_departments_site_name_live',
                violation_error_message='This site already has a production department with this name.',
            ),
        ),
        migrations.AddConstraint(
            model_name='productiondepartment',
            constraint=models.CheckConstraint(
                condition=models.Q(('capacity__isnull', True), ('capacity__gte', 0), _connector='OR'),
                name='chk_production_departments_capacity',
            ),
        ),
    ]
