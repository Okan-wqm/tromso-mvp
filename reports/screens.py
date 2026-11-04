"""What the data map (core.datamap) cannot read from the code, for the report tables the Reports tab does not save:
the filing freezes a snapshot, and a correction starts a new report. The rows a report owns (treatment answers,
resistance suspicions, sensitivity tests, unit answers) are row lists of the tab and come from the code."""
from core.datamap import Screen, no, system

from . import views
from .forms import SubmitForm
from .resources import ReportResource

APPEND_ONLY = 'append-only: a database trigger refuses UPDATE and DELETE'

SCREENS = {
    'Report': Screen(
        create=(views.correct,),
        edit=(views.submit,),
        read=(views.print_page, views.export),
        note='Recording the filing freezes the report (ReportSnapshot); a correction of a filed report is a new report.',
        forms=(SubmitForm,),
        columns={'corrects': system('set when a correction of a filed report is started'),
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
