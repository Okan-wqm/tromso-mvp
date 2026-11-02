from django.utils.translation import gettext_lazy as _

from core.database import Section, Viewer

# What Administration › Database shows (core.database). Tables come from the models of the apps
# listed here, so a new tab's table appears by itself; every other app's tables (sessions, the
# Django admin's log) are not shown at all.
VIEWER = Viewer(
    sections=[
        Section(_('Facility'), ('farm',)),
        Section(_('Administration'), ('core', 'auth')),
    ],
    # Tables of a listed app that stay hidden, by table name.
    excluded=(),
    # Columns never read from the database: their cells show a placeholder, they cannot be sorted or
    # filtered (that would reveal them), and the CSV export leaves them out. Every column that holds
    # a secret belongs here.
    masked={'auth_user': ('password',)},
    # One line per table where the model's docstring does not say it in the project's words.
    descriptions={
        'auth_user': _('People who can sign in: account details and a hash of the password.'),
        'auth_group': _('Roles: a name and the permissions it allows.'),
        'auth_permission': _('Every permission that exists: view, add, change and delete of each model, and the custom ones.'),
        'auth_group_permissions': _('Which permissions each role allows.'),
        'auth_user_groups': _('Which roles each user has.'),
        'auth_user_user_permissions': _('Permissions given to one user directly instead of through a role.'),
        'supplier_sites': _('Which sites each supplier delivers to or works at.'),
    },
)
