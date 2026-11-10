"""What a note on a task was (TaskNote.kind): a note, or the completion note or the reason for cancelling that a
reopening took off the task and kept as a note by its writer (review R5: nothing a person wrote is lost by reopening;
the activity log holds only digests). Every note there is a note. Going back drops the column."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_entry_keys'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='tasknote',
            name='kind',
            field=models.CharField(choices=[('note', 'Note'), ('completion_note', 'Completion note'), ('cancel_reason', 'Reason for cancelling')], default='note', max_length=20, verbose_name='Kind'),
        ),
        migrations.AddConstraint(
            model_name='tasknote',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ['note', 'completion_note', 'cancel_reason'])), name='chk_task_notes_kind'),
        ),
    ]
