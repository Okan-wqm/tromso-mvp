"""The index a sending round's flood check needs (alarms/floods.py `recent`): the attempts sent or covered within the
last flood window or critical follow-up time, found by their time. Without it every round that sends read the whole
history of delivery attempts end to end (a Seq Scan of 100,000 rows beside a history of that size, counted by
core.testing.plans; alarms/tests/test_review_fixes.py QueueTests), and the history only grows. Partial, on the sent and
covered ones only: the failed ones are never asked for by time.

Built CONCURRENTLY, so a farm's running alarm worker keeps writing its attempts while the index is made on a long
history (a plain CREATE INDEX would hold their writes for as long as it takes): this migration is therefore not
atomic, and its one statement is its own step. Going back drops the index the same way."""
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('alarms', '0023_alarm_place'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='deliveryattempt',
            index=models.Index(condition=models.Q(('outcome__in', ['sent', 'grouped'])), fields=['attempted_at'],
                               name='alarm_attempts_sent_at_idx'),
        ),
    ]
