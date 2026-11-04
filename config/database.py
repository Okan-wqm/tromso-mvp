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
    masked={'auth_user': ('password',), 'messages': ('body',)},
    # One line per table where the model's docstring does not say it in the project's words.
    descriptions={
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
        'monitor_boards': _('The named wall screens of Monitoring: a name, how its cards are drawn by default and how often its screens ask.'),
        'monitor_board_units': _('The cards of each monitoring board: a unit and, when it differs from the board, how its card is drawn.'),
        'treatment_units': _('Which units each treatment was given in.'),
        'health_event_units': _('Which units each health event concerns; none for the whole site.'),
        'document_species': _('Which species each library document is about.'),
        'knowledge_entry_species': _('Which species each knowledge entry holds for.'),
        'slaughter_facility_species': _('Which species each slaughter facility takes.'),
    },
)
