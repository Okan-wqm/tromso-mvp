"""What the data map (core.datamap) cannot read from the code, for the core tables."""
from .datamap import Screen, no, system
from .forms import UserForm
from .resources import UserResource
from .views import activity_log, set_language

SCREENS = {
    'PlatformSettings': Screen(
        create=no('the migration makes the one row'),
        delete=no('there is always exactly one row (the database refuses a delete)'),
        note="The platform owner's rules, read by core.platform only.",
    ),
    'AuditLog': Screen(
        create=no('written by the code: every create, change, delete, restore and void of every record logs itself '
                  '(core.audit)'),
        edit=no('append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'),
        delete=no('append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'),
        read=(activity_log,),
        note="A record's own rows are also shown on the History tab of its edit page.",
        columns={'*': system('written by core.audit when the change is saved')},
    ),
    'AccessEvent': Screen(
        create=no('written by the code: a read of a sealed experiment by someone outside its team (core.sealing.'
                  'log_access)'),
        edit=no('append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'),
        delete=no('append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'),
        read=('experiments:experiment_detail',),
        note='The read log of confidential records; an experiment’s lead reads its rows on the Who looked tab.',
        columns={'*': system('written by core.sealing.log_access when the record is read')},
    ),
    'EntryKey': Screen(
        create=no('written by the code: a new record a form creates stores the form\'s key with it (core.crud, '
                  'F-232)'),
        edit=no('a key belongs to the sending that created its record'),
        delete=no('kept, so a form sent again later still opens the record it created'),
        read=no('read only by the form path, to find the record a key created'),
        note='The same form sent twice creates one record: the second sending finds the first one\'s record here.',
        columns={'*': system('written by core.crud when a form creates a record')},
    ),
    'Profile': Screen(
        create=(set_language, UserResource),
        edit=(set_language, UserResource),
        delete=no('a profile goes with its person, and people are deactivated, never deleted'),
        read=(UserResource,),
        note='Today the profile holds the language only: chosen with the language switcher, or on the Users tab.',
        forms=(UserForm,),
        columns={'user': system('the person the profile belongs to')},
    ),
    'AccountMail': Screen(
        create=(UserResource, 'core:user_invite', 'password_reset'),
        edit=no('a row is what became of one mail'),
        delete=no('kept: the users tab shows what became of the last invitation, and the reset form counts an '
                  'account\'s mails of the last hour'),
        read=(UserResource,),
        note='Written when a mail is sent: creating a user and "Send invitation" on the users tab send an invitation, '
             '"Forgot your password?" a reset. Never the link or its token.',
        columns={'*': system('written by core.accountmail when the mail is sent')},
    ),
    'Rev': Screen(
        create=no('written by the database: a trigger of each tracked table moves its revision at commit (core.rev)'),
        edit=no('written by the database; `manage.py core_rev_rebuild` moves every revision after a restore'),
        delete=no('derived data, safe to rebuild: a revision is never deleted'),
        read=no('read by the code that proves a stored figure still valid; the database viewer shows the table'),
        columns={'*': system('moved by the revision triggers (core.operations.TrackRev)')},
    ),
    'RowVersion': Screen(
        create=no('written by the database: a trigger of each kept table opens a version when a row is made or '
                  'changed (core.versions)'),
        edit=no('written by the database: the trigger closes a version when its row is changed or deleted; the app '
                'may not write the table'),
        delete=no('kept: what a row was is never forgotten'),
        read=no('read by the plan from a past start, by the rows\' ids (core.versions.as_of); the database viewer '
                'shows the table with its values masked'),
        columns={'*': system('written by the versions\' triggers (core.operations.KeepVersions)')},
    ),
}
