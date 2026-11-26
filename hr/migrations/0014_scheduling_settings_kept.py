"""The scheduling settings' one row is changed, never deleted (the data-layering audit, M-1): a soft delete is refused by
a check, a DELETE by the database. Reading it (SchedulingSettings.get) no longer makes it again: a read stays a read."""
from django.db import migrations, models

from core.operations import KeepRows


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0013_forgotten_after_hours'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='schedulingsettings',
            constraint=models.CheckConstraint(condition=models.Q(('is_deleted', False)),
                                              name='chk_scheduling_settings_kept'),
        ),
        KeepRows('scheduling_settings', 'The scheduling settings'),
    ]
