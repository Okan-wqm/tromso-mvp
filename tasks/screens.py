"""What the data map (core.datamap) cannot read from the code, for the task tables: what a person does to a task from
its drawer (start, complete, cancel, reopen, tick a line, add a note) is written by the task services, and the place
of a task is chosen as one `location` field that fills up to four columns."""
from core.datamap import Screen, no, system

from . import views
from .forms import NoteForm
from .resources import TaskResource

PLACE = ('production_department', 'system', 'unit', 'equipment')

SCREENS = {
    'Task': Screen(
        edit=(views.start, views.complete, views.cancel, views.reopen),
        note='A status changes only through start, complete, cancel and reopen (tasks/services.py).',
        fills={'location': PLACE},
        columns={'status': system('moved by start, complete, cancel and reopen'),
                 'series': system('the recurring task that planned it; none for a task made by hand')},
    ),
    'TaskSeries': Screen(fills={'location': PLACE}),
    'TaskChecklistItem': Screen(edit=(views.tick,), note='A tick is its own logged write (tasks.services.tick).'),
    'TaskNote': Screen(
        create=(views.add_note,),
        edit=no('part of the task\'s record, never edited'),
        delete=no('part of the task\'s record, never removed'),
        read=(TaskResource,),
        note="Shown in the task's drawer.",
        forms=(NoteForm,),
        columns={'task': system('the task the note is added to'), 'author': system('the person who adds it')},
    ),
}
