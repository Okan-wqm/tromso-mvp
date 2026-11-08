"""A live production department is on a site (F-212): a deleted site takes its (by then empty) departments with it
instead of leaving them without a site, and the database refuses a live department without one.

The check is added NOT VALID: a department a deleted site left without a site before stays as it is (nothing is
invented for it), and every insert or update from now on must satisfy it, so the row is put on a site the next time
it is saved (the department form asks for one). `manage.py check_stock` names such rows; once it names none, the
check can be validated (ALTER TABLE production_departments VALIDATE CONSTRAINT ...)."""
import django.db.models.deletion
from django.db import migrations, models

CHECK = 'chk_production_departments_live_on_a_site'


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0028_site_timezone_required'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productiondepartment',
            name='site',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='production_departments', to='farm.site', verbose_name='Site'),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name='productiondepartment',
                    constraint=models.CheckConstraint(condition=models.Q(('site__isnull', False), ('is_deleted', True), _connector='OR'), name=CHECK),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    f'ALTER TABLE production_departments ADD CONSTRAINT {CHECK} '
                    'CHECK (site_id IS NOT NULL OR is_deleted) NOT VALID',
                    f'ALTER TABLE production_departments DROP CONSTRAINT {CHECK}',
                ),
            ],
        ),
    ]
