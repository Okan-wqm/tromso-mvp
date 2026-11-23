"""A person's free text on a task is private in the activity log (owner decision F-061; review R7): the description of
a task and of a recurring task, like a note, a completion note and a reason for cancelling. The log says that it was
given or changed, never its words; the task itself shows them to who reads it."""
from django.urls import reverse

from core.audit import private
from core.models import AuditLog

from ..models import Task, TaskSeries
from .. import places
from . import TasksTestCase, form_data
from .test_series import series_data

WORDS = 'Call Kari on 98989898 before you open the hatch'


class DescriptionTests(TasksTestCase):
    def everything(self):
        return str(list(AuditLog.objects.values_list('changes', flat=True)))

    def test_a_tasks_description_is_private_in_the_log_and_shown_on_the_task(self):
        self.client.post(reverse('tasks:task_create'), form_data(
            site=places.site_key(self.t1), location=places.token(self.t1), due_date=self.today.isoformat(),
            assignees=[self.ali.pk], description=WORDS))
        task = Task.objects.get()
        self.assertEqual(task.description, WORDS)
        created = AuditLog.objects.get(entity_id=str(task.pk), action='create')
        self.assertEqual((created.changes['Description'], created.changes['Title']),
                         ([None, private(WORDS)], [None, 'Clean the drum filter']))
        self.client.post(reverse('tasks:task_edit', args=[task.pk]), form_data(
            site=places.site_key(self.t1), location=places.token(self.t1), due_date=self.today.isoformat(),
            assignees=[self.ali.pk], description='Ask at the gate', version=str(task.version)))
        edited = AuditLog.objects.get(entity_id=str(task.pk), action='update')
        self.assertEqual(edited.changes, {'Description': [private(WORDS), private('Ask at the gate')]})
        self.assertNotIn('98989898', self.everything())
        self.assertNotIn('gate', self.everything())

    def test_a_recurring_tasks_description_is_private_too(self):
        self.client.post(reverse('tasks:taskseries_create'), series_data(
            self.t1, starts_on=self.today.isoformat(), assignees=[self.ali.pk], title='Oxygen round', description=WORDS))
        series = TaskSeries.objects.get()
        self.assertEqual(series.description, WORDS)
        created = AuditLog.objects.get(entity_type='recurring task', entity_id=str(series.pk), action='create')
        self.assertEqual(created.changes['Description'], [None, private(WORDS)])
        self.assertNotIn('98989898', self.everything())
