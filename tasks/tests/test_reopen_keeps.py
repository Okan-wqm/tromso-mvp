"""Reopening a task loses nothing a person wrote (review R5). Reopening clears the completion note and the reason for
cancelling on the task (the task is open again), and the activity log holds only their digests, so the words would
exist nowhere. They are kept on the task as notes by the person who wrote them, marked as what they were; only the
erasure procedure removes a person's words (docs/erasure.md, task_notes)."""
from django.urls import reverse

from core.audit import private
from core.models import AuditLog

from ..models import TaskNote
from . import TasksTestCase

FOUND = '14 dead fish removed, two with wounds'
WHY = 'Net torn by the wellboat, diver called'


class ReopenKeepsTheWordsTests(TasksTestCase):
    def act(self, user, name, task, data=None):
        self.client.force_login(user)
        return self.client.post(reverse(f'tasks:task_{name}', args=[task.pk]), data or {})

    def notes(self, task):
        return [(note.kind, note.author, note.body) for note in TaskNote.objects.filter(task=task).order_by('id')]

    def test_the_reason_for_cancelling_and_the_completion_note_stay_on_the_task_as_notes(self):
        task = self.make_task(assignees=[self.ali])
        self.act(self.boss, 'cancel', task, {'reason': WHY})
        self.act(self.boss, 'reopen', task)
        self.act(self.ali, 'complete', task, {'note': FOUND})
        self.act(self.boss, 'reopen', task)
        task.refresh_from_db()
        self.assertEqual((task.status, task.completion_note, task.cancel_reason), ('open', '', ''))
        self.assertEqual(self.notes(task), [('cancel_reason', self.boss, WHY), ('completion_note', self.ali, FOUND)])
        # who reads the task reads them, each said as what it was
        drawer = self.client.get(reverse('tasks:task_list'), {'task': str(task.pk), 'view': 'open'}).content.decode()
        for words in (WHY, FOUND, 'Reason for cancelling, kept when the task was reopened',
                      'Completion note, kept when the task was reopened'):
            self.assertIn(words, drawer)
        # and the log still holds none of the words: the reopening says each was cleared, by its digest
        cleared = [entry.changes for entry in AuditLog.objects.filter(entity_id=str(task.pk), action='update')
                   .order_by('created_at') if entry.changes.get('Status', [None, {}])[1] == {'msgid': 'Open'}]
        self.assertEqual([change.get('Reason for cancelling') or change.get('Completion note') for change in cleared],
                         [[private(WHY), None], [private(FOUND), None]])
        everything = str(list(AuditLog.objects.values_list('changes', flat=True)))
        self.assertNotIn('wellboat', everything)
        self.assertNotIn('dead fish', everything)

    def test_a_task_closed_without_words_leaves_no_note_and_an_ordinary_note_is_an_ordinary_note(self):
        task = self.make_task(assignees=[self.ali])
        self.act(self.ali, 'note', task, {'body': 'Filter cleaned'})
        self.act(self.ali, 'complete', task, {'note': ''})
        self.act(self.boss, 'reopen', task)
        self.assertEqual(self.notes(task), [('note', self.ali, 'Filter cleaned')])
