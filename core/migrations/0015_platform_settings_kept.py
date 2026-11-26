"""The platform settings' one row is changed, never deleted (the data-layering audit, M-1): a soft delete is refused by a
check, a DELETE by the database. Reading it (PlatformSettings.get) no longer makes it again: a read stays a read."""
from django.db import migrations, models

from core.operations import KeepRows


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_rev'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='platformsettings',
            constraint=models.CheckConstraint(condition=models.Q(('is_deleted', False)),
                                              name='chk_platform_settings_kept'),
        ),
        KeepRows('platform_settings', 'The platform settings'),
    ]
