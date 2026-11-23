"""The outbox's queue and the words about a snooze (the review of the alarm worker, F1, F6, F9):
- `alarm_outbox`: the notifications still to be sent, one row each, so a round of the outbox reads what waits however
  long the history is; filled here with every notification that has no sent or covered attempt (the next round gives
  up what is past its attempts);
- a notification's `kind`: the alarm itself, or that someone snoozed it, or that its snooze ended with the alarm still
  open (with the snooze it is about); the alarm's own notification stays once per alarm, person, channel and level;
- the bounds of a critical alarm's retry time and flood window are tighter (5 minutes) than a warning's (an hour); the
  rows seeded (30 s and 120 s) are inside them.
Back: refused while a notification about a snooze exists (the history is append-only); the queue goes."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


FILL = """
INSERT INTO alarm_outbox (notification_id)
SELECT n.id FROM alarm_notifications n
WHERE NOT EXISTS (SELECT 1 FROM alarm_delivery_attempts a WHERE a.notification_id = n.id
                  AND a.outcome IN ('sent', 'grouped'))
"""


def refuse_with_snooze_words(apps, schema_editor):
    found = apps.get_model('alarms', 'Notification').objects.exclude(kind='alarm').count()
    if found:
        raise RuntimeError(f'alarms 0019 cannot be reversed: {found} notification(s) are about a snooze, which the '
                           f'alarms before it have no word for. Restore a backup taken before it instead.')


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0018_floods'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, refuse_with_snooze_words),
        migrations.CreateModel(
            name='OutboxEntry',
            fields=[
                ('notification', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='outbox_entry', serialize=False, to='alarms.notification', verbose_name='Notification')),
            ],
            options={
                'verbose_name': 'alarm outbox entry',
                'verbose_name_plural': 'alarm outbox entries',
                'db_table': 'alarm_outbox',
            },
        ),
        migrations.RemoveConstraint(
            model_name='notification',
            name='uq_alarm_notifications_once',
        ),
        migrations.RemoveConstraint(
            model_name='severitypolicy',
            name='chk_alarm_severity_policies_retry',
        ),
        migrations.RemoveConstraint(
            model_name='severitypolicy',
            name='chk_alarm_severity_policies_flood',
        ),
        migrations.AddField(
            model_name='notification',
            name='kind',
            field=models.CharField(choices=[('alarm', 'The alarm'), ('snoozed', 'The alarm was snoozed'), ('resumed', 'The snooze ended; the alarm is still open')], db_default='alarm', default='alarm', max_length=10, verbose_name='Kind'),
        ),
        migrations.AddField(
            model_name='notification',
            name='shelve',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='notifications', to='alarms.alarmshelve', verbose_name='Snooze'),
        ),
        migrations.AlterField(
            model_name='severitypolicy',
            name='flood_window_seconds',
            field=models.PositiveIntegerField(verbose_name='Flood window (seconds)'),
        ),
        migrations.AlterField(
            model_name='severitypolicy',
            name='retry_seconds',
            field=models.PositiveIntegerField(verbose_name='Retry after (seconds)'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.UniqueConstraint(condition=models.Q(('kind', 'alarm')), fields=('alarm', 'recipient', 'channel', 'level'), name='uq_alarm_notifications_once'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.UniqueConstraint(condition=models.Q(('shelve__isnull', False)), fields=('shelve', 'recipient', 'channel', 'kind'), name='uq_alarm_notifications_snooze_once'),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'alarm'), ('shelve__isnull', True)), models.Q(('kind__in', ['snoozed', 'resumed']), ('shelve__isnull', False)), _connector='OR'), name='chk_alarm_notifications_kind'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('pk__in', []), models.Q(('retry_seconds__gte', 1), ('retry_seconds__lte', 300), ('severity', 'critical')), models.Q(('retry_seconds__gte', 1), ('retry_seconds__lte', 3600), ('severity', 'warning')), _connector='OR'), name='chk_alarm_severity_policies_retry'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('flood_count__gte', 2), ('flood_count__lte', 1000)), name='chk_alarm_severity_policies_flood'),
        ),
        migrations.AddConstraint(
            model_name='severitypolicy',
            constraint=models.CheckConstraint(condition=models.Q(('pk__in', []), models.Q(('flood_window_seconds__gte', 10), ('flood_window_seconds__lte', 300), ('severity', 'critical')), models.Q(('flood_window_seconds__gte', 10), ('flood_window_seconds__lte', 3600), ('severity', 'warning')), _connector='OR'), name='chk_alarm_severity_policies_flood_window'),
        ),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
    ]
