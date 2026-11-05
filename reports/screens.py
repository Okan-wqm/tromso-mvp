"""What the data map (core.datamap) cannot read from the code, for the report tables the Reports tab does not save:
the filing freezes a snapshot, and a correction starts a new report. The rows a report owns (treatment answers,
resistance suspicions, sensitivity tests, unit answers) are row lists of the tab and come from the code."""
from core.datamap import Screen, no, system

from . import views
from .forms import CloseForm, DutyDoneForm, SubmitForm
from .resources import ReportResource

APPEND_ONLY = 'append-only: a database trigger refuses UPDATE and DELETE'

SCREENS = {
    'OutsideDutyDone': Screen(
        create=(views.duty_done,),
        edit=no('a record is undone, not edited: undoing deletes it'),
        delete=(views.duty_undo,),
        read=(views.outside_duties,),
        note='The record of a person that an annual duty outside this system (the driftsplan, the lice coordination plan) was done.',
        forms=(DutyDoneForm,),
        columns={'duty': system('the duty the link names'), 'site': system('the site the link names'),
                 'year': system('the year the link names'), 'recorded_by': system('the person who recorded it')},
    ),
    'DueClosure': Screen(
        create=(views.close,),
        edit=no('a closure is reopened, not edited: reopening deletes it'),
        delete=(views.reopen,),
        read=(ReportResource,),
        note='A report that was owed and will not be filed, closed with the reason (the due list stops listing it).',
        forms=(CloseForm,),
        columns={'kind': system('the due row the closing link names'), 'site': system('the due row the closing link names'),
                 'facility': system('the due row the closing link names'),
                 'period_start': system('the due row the closing link names'),
                 'closed_by': system('the person who closed it')},
    ),
    'Report': Screen(
        create=(views.correct,),
        edit=(views.submit,),
        read=(views.print_page, views.export),
        note='Recording the filing freezes the report (ReportSnapshot); a correction of a filed report is a new report.',
        forms=(SubmitForm,),
        columns={'corrects': system('set when a correction of a filed report is started'),
                 'deadline_on': system('the deadline when the filing is recorded'),
                 'filed_late': system('whether the filing came after the deadline, set when it is recorded'),
                 'submitted_by': system('the person who recorded the filing')},
    ),
    'ReportSnapshot': Screen(
        create=(views.submit,),
        edit=no(APPEND_ONLY),
        delete=no(APPEND_ONLY),
        read=(ReportResource, views.print_page, views.export),
        note='What was told to the authority, frozen when the filing is recorded; shown, exported again and compared '
             'with what the records say now.',
        columns={'*': system('frozen by reports/services.py when the filing is recorded')},
    ),
}
