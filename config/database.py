from django.utils.translation import gettext_lazy as _

from core.database import Section, Viewer

# What Administration › Database shows (core.database). Tables come from the models of the apps
# listed here, so a new tab's table appears by itself; every other app's tables (sessions, the
# Django admin's log) are not shown at all.
VIEWER = Viewer(
    sections=[
        Section(_('Facility'), ('farm',)),
        Section(_('Knowledge'), ('knowledge',)),
        Section(_('Storage'), ('inventory',)),
        Section(_('Messages'), ('messaging',)),
        Section(_('Reports'), ('reports',)),
        Section(_('Tasks'), ('tasks',)),
        Section(_('People'), ('hr',)),
        Section(_('Research'), ('experiments',)),
        Section(_('Monitoring'), ('monitoring',)),
        Section(_('Administration'), ('core', 'auth')),
    ],
    # Tables of a listed app that stay hidden, by table name.
    excluded=(),
    # Columns never read from the database: their cells show a placeholder, they cannot be sorted or
    # filtered (that would reveal them), and the CSV export leaves them out. Every column that holds
    # a secret belongs here, and so does what people write to each other: a message's text is for the
    # members of its conversation, which the platform admin reading the database is not (README, Messages).
    masked={'auth_user': ('password',), 'messages': ('body',), 'shift_assignments': ('note',),
            'leave_requests': ('reason', 'decision_note'), 'attendance_records': ('note',)},
    # One line per table where the model's docstring does not say it in the project's words.
    descriptions={
        'employees': _('The people of the company for HR: number, name (or the account that names them), type and the '
                       'first and last day. No pay, bank or identity number is kept.'),
        'shifts': _('The shift patterns of the roster: a start and an end on the wall clock of the site, a break and a grace.'),
        'holidays': _('Days that are not working days, for every site or for one.'),
        'scheduling_settings': _('The one row of scheduling limits and defaults (rest, weekly hours, days in a row, working '
                                 'weekdays, punch window).'),
        'shift_assignments': _('One person’s plan for one day: the shift they start that day, or none for planned off.'),
        'leave_types': _('The kinds of leave the company grants (annual, sick, parental), with the days a year and whether a request needs approval.'),
        'leave_requests': _('A person’s request to be away from a first to a last day, and how it was decided; its reason and note are masked.'),
        'attendance_records': _('One stretch of a person’s presence: from a clock-in to a clock-out, by the person or entered by hand; its note is masked.'),
        'postings': _('Where each person works from a day: one department, production or office, and the title.'),
        'office_departments': _('The company’s office departments (finance, administration), nested under one another.'),
        'auth_user': _('People who can sign in: account details and a hash of the password.'),
        'auth_group': _('Roles: a name and the permissions it allows.'),
        'auth_permission': _('Every permission that exists: view, add, change and delete of each model, and the custom ones.'),
        'auth_group_permissions': _('Which permissions each role allows.'),
        'auth_user_groups': _('Which roles each user has.'),
        'auth_user_user_permissions': _('Permissions given to one user directly instead of through a role.'),
        'supplier_sites': _('Which sites each supplier delivers to or works at.'),
        'water_sampling_points': _('Where a water sample is taken: a named place on one unit, one system’s loop or one '
                                   'piece of equipment, of a kind that says whether it sees the stream in, the water '
                                   'within or the stream out.'),
        'monitor_boards': _('The named wall screens of Monitoring: a name, the template its cards are drawn with by default, '
                            'how wide its cards are and how often its screens ask.'),
        'monitor_board_units': _('The cards of each monitoring board: a unit and, when it differs from the board, the '
                                 'template its card is drawn with.'),
        'monitor_card_templates': _('The monitoring card templates: a name, the widgets of the card as a layout and the '
                                    'template its flip link shows. Three are built in and never change.'),
        'monitor_card_assignments': _('Which template a unit’s card gets: a rule for one unit, system, system type, species '
                                      'or kind of unit, or the one rule for every unit.'),
        'treatment_units': _('Which units each treatment was given in.'),
        'health_event_units': _('Which units each health event concerns; none for the whole site.'),
        'document_species': _('Which species each library document is about.'),
        'knowledge_entry_species': _('Which species each knowledge entry holds for.'),
        'slaughter_facility_species': _('Which species each slaughter facility takes.'),
    },
)
