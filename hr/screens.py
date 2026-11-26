"""What the data map (core.datamap) cannot read from the code, for the HR tables: the placements a person's form writes through
a service, the decisions on a leave request, a person's own clock-in, the roster's batch plan, and the rows nobody deletes.
The tabs of people, attendance, leave requests and plans hand every save to hr.services, their one writer."""
from core.datamap import Screen, no, system

from . import views

SCREENS = {
    'Employee': Screen(
        delete=no('a person leaves with a last day (left_on); the record and its history stay readable'),
        extra_fields={
            'department': 'chooses the department of the dated placement the Placement tab writes (hr.services.move)',
            'title': 'the title of that placement',
            'from_day': 'the day that placement starts',
        },
        note='Where a person works is a dated placement, not a column: the Placement tab saves it through hr.services.move. '
             'The form saves through hr.services.add_employee and change_employee; a last day is hr.services.leave_company.',
    ),
    'Posting': Screen(
        part_of='hr.Employee',
        columns={'*': system('written by hr.services.move from the Placement tab of the employee form, and closed by a last day')},
        read=(views.organisation_chart,),
        note='One placement covers any day (exclusion constraint); a move closes the open one the day before.',
    ),
    'ShiftAssignment': Screen(
        create=(views.plan,), edit=(views.plan,), delete=(views.plan,),
        note='A cell is planned on its own dialog (hr.services.plan_day) or in a batch (hr.services.plan_shifts): all '
             'cells or none, by the same rules.',
    ),
    'AttendanceRecord': Screen(
        create=(views.punch,), edit=(views.punch,), read=(views.today,),
        columns={'via': system('self for a person\'s own clock-in and out, entered for a lead\'s form and for a stretch '
                               'whose time a lead\'s correction changed (a forgotten clock-out closed by hand)')},
        note="A person's own clock-in and clock-out are written by hr.services at the server's time; a clock-in left open "
             "longer than Scheduling settings' limit is a forgotten clock-out, closed on the Attendance page. The "
             "Attendance page's entries, corrections and voids are hr.services.enter_presence, correct_presence and "
             "void_presence.",
    ),
    'LeaveRequest': Screen(
        edit=(views.approve, views.reject, views.cancel),
        delete=no('a wrong request is cancelled, not deleted'),
        columns={'status': system('moved by approve, reject and cancel (hr.services.decide_leave, cancel_leave)'),
                 'decision_note': system('typed in the reject dialog'),
                 'decided_by': system('the person who approved or rejected it'),
                 'decided_at': system('when it was decided, or when a type that needs no approval was filed')},
        note='One approval step: Edit also approves, rejects and cancels; nobody decides their own request. Filed and '
             'changed through hr.services.file_leave and change_leave.',
    ),
    'SchedulingSettings': Screen(
        create=no('the migration makes the one row'),
        delete=no('there is always exactly one row (the database refuses a delete)'),
    ),
}
