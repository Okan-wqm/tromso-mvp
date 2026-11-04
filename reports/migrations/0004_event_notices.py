"""A notice is about a health event (D-4): the disease notice's event, a welfare notice's optional one, and one notice per
event. That Mattilsynet was told of a health event is the filing of such a notice; the times the events kept are moved into
filed notices by the next migration, before farm migration 0024 drops the column."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0023_reports_fields'),
        ('reports', '0003_sea_lice_answers'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='health_event',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='notices', to='farm.healthevent', verbose_name='Health event'),
        ),
        migrations.AddConstraint(
            model_name='report',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('health_event__isnull', False), ('kind', 'disease')), models.Q(models.Q(('kind', 'disease'), _negated=True), models.Q(('kind', 'welfare'), ('health_event__isnull', True), _connector='OR')), _connector='OR'), name='chk_regulatory_reports_health_event', violation_error_message='A disease notice is about a health event; a welfare notice may be; no other report is.'),
        ),
        migrations.AddConstraint(
            model_name='report',
            constraint=models.UniqueConstraint(condition=models.Q(('corrects__isnull', True), ('health_event__isnull', False), ('is_deleted', False)), fields=('kind', 'health_event'), name='uq_regulatory_reports_event_notice', violation_error_message='This health event has a notice already: open it from the list.'),
        ),
    ]
