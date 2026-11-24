"""A board's wall screen and how far it is read from (frontend-redesign CONSENSUS §9): with both, a wall of fitted cards
never sets its type smaller than can be read from there (monitoring/cards/slots.py legible_unit). Every row the
database can hold is a constraint: a preset is its own diagonal, another screen has one in range, none has none; the
distance in range or empty. Existing boards say neither: their walls are as they were."""
import django.core.validators
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0007_ph_window_scales'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='monitorboard',
            name='distance_m',
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.5')), django.core.validators.MaxValueValidator(Decimal('20'))], verbose_name='Read from (m)'),
        ),
        migrations.AddField(
            model_name='monitorboard',
            name='screen',
            field=models.CharField(blank=True, choices=[('24', '24″ monitor, 1920 × 1080'), ('27', '27″ monitor, 2560 × 1440'), ('32', '32″ monitor, 3840 × 2160'), ('34', '34″ ultrawide monitor, 3440 × 1440'), ('49', '49″ ultrawide monitor, 5120 × 1440'), ('55', '55″ TV, 3840 × 2160'), ('65', '65″ TV, 3840 × 2160'), ('other', 'Another screen: type its diagonal')], default='', max_length=8, verbose_name='Screen'),
        ),
        migrations.AddField(
            model_name='monitorboard',
            name='screen_inches',
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True, validators=[django.core.validators.MinValueValidator(Decimal('10')), django.core.validators.MaxValueValidator(Decimal('150'))], verbose_name='Screen diagonal (inches)'),
        ),
        migrations.AddConstraint(
            model_name='monitorboard',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('screen', ''), ('screen_inches__isnull', True)), models.Q(('screen', 'other'), ('screen_inches__gte', Decimal('10')), ('screen_inches__lte', Decimal('150'))), models.Q(('screen', '24'), ('screen_inches', Decimal('24'))), models.Q(('screen', '27'), ('screen_inches', Decimal('27'))), models.Q(('screen', '32'), ('screen_inches', Decimal('32'))), models.Q(('screen', '34'), ('screen_inches', Decimal('34'))), models.Q(('screen', '49'), ('screen_inches', Decimal('49'))), models.Q(('screen', '55'), ('screen_inches', Decimal('55'))), models.Q(('screen', '65'), ('screen_inches', Decimal('65'))), _connector='OR'), name='chk_monitor_boards_screen', violation_error_message='Choose a screen, or another screen with its diagonal between 10 and 150 inches.'),
        ),
        migrations.AddConstraint(
            model_name='monitorboard',
            constraint=models.CheckConstraint(condition=models.Q(('distance_m__isnull', True), models.Q(('distance_m__gte', Decimal('0.5')), ('distance_m__lte', Decimal('20'))), _connector='OR'), name='chk_monitor_boards_distance', violation_error_message='Read from between 0.5 and 20 m, or leave it empty.'),
        ),
    ]
