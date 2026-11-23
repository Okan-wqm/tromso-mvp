"""How the tasks are sealed (core.sealing): a task at a sealed unit or system, due inside its cell, does not exist for
someone the cell's owner has not granted; its assignees, checklist and notes go with it. A recurring task is sealed while
its days overlap a cell."""
from core.sealing import declare


def declare_all():
    from . import models as m
    declare(m.Task, unit='unit', system='system', day='due_date', via=('batch',))
    declare(m.TaskSeries, unit='unit', system='system', day=('starts_on', 'ends_on'))
    for model in (m.TaskAssignee, m.TaskChecklistItem, m.TaskNote):
        declare(model, via=('task',))
    for model in (m.TaskSeriesAssignee, m.TaskSeriesChecklistItem):
        declare(model, via=('series',))
