"""The index a sending round's flood check needs (alarms/floods.py `recent`): the attempts sent or covered within the
last flood window or critical follow-up time, found by their time. Without it every round that sends read the whole
history of delivery attempts end to end (a Seq Scan of 100,000 beside a history of that size, counted by
core.testing.reads; alarms/tests/test_review_fixes.py QueueTests), and the history only grows. Partial, on the sent and
covered ones only: the failed ones are never asked for by time.

A plain CREATE INDEX in the migration's transaction (review 1, M2): the upgrade stops every writer before it migrates
(docs/ops/upgrade.md), so nothing waits on the lock, and a run that fails leaves nothing behind (CONCURRENTLY would
leave an invalid index that stops the next release). Going back drops it."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alarms', '0023_alarm_place'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='deliveryattempt',
            index=models.Index(condition=models.Q(('outcome__in', ['sent', 'grouped'])), fields=['attempted_at'],
                               name='alarm_attempts_sent_at_idx'),
        ),
    ]
