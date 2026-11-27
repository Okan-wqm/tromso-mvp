from django import forms
from django.conf import settings
from django.contrib.auth import forms as auth_forms, get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import access, accountmail, navigation
from .crud import TabbedForm, tab_fields
from .language import account_language, save_account_language
from .models import PlatformSettings

User = get_user_model()


class PermissionMatrix(forms.CheckboxSelectMultiple):
    """A role's permissions as the access matrix (core.access): a row per area under its group, a
    column per action, a box only where the area offers the action. Create, Edit and Delete point at
    their row's Read box (data-requires, see frontend/components.ts), as access.implied adds it on save."""

    template_name = 'core/widgets/permission_matrix.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        options = {access.perm_name(option['value'].instance): option
                   for _, group, _ in context['widget']['optgroups'] for option in group}
        sections = {}
        for area in access.areas():
            cells = {action: options.get(area.perm(action)) for action in area.actions}
            read = cells.get(access.READ)
            for action, cell in cells.items():
                if cell and read and action in access.INCLUDES_READ:
                    cell['attrs']['data-requires'] = read['attrs']['id']
            sections.setdefault(area.group, []).append(
                {'label': area.label, 'cells': [(label, cells.get(action)) for action, label in access.ACTIONS],
                 # under the area: what its rights also reach (Area.note), then its lines shown only to some
                 'notes': [*([area.note] if area.note else []), *([area.duties] if area.duties else []),
                           *navigation.notes(area.perm(access.READ))]})
        context['widget']['columns'] = [label for _, label in access.ACTIONS]
        context['widget']['sections'] = sections.items()
        return context


ROLE_FORM_TABS = [('role', _('Role'), ['name', 'permissions'])]


class RoleForm(TabbedForm):
    tabs = ROLE_FORM_TABS

    class Meta:
        model = Group
        fields = tab_fields(ROLE_FORM_TABS)
        labels = {'name': _('Role name'), 'permissions': _('Permissions')}
        help_texts = {'permissions': _('Create, Edit and Delete include Read. '
                                       'Roles and users are managed by the platform admin only.')}
        error_messages = {'name': {'unique': _('Another role already uses this name.')}}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Site manager')}),
            'permissions': PermissionMatrix,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only what the matrix offers: saving the role sets exactly the ticked boxes.
        self.fields['permissions'].queryset = access.permissions()

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean_permissions(self):
        names = access.implied(access.perm_name(permission) for permission in self.cleaned_data['permissions'])
        return [permission for permission in self.fields['permissions'].queryset
                if access.perm_name(permission) in names]


USER_FORM_TABS = [('account', _('Account'), [
    'username', 'first_name', 'last_name', 'email', 'language', 'is_active', 'groups'])]


class UserForm(TabbedForm):
    """A person's account. Who may sign in is `is_active`: people are deactivated, not deleted, so
    their name stays on their history. Platform admin status is not set here. The language is kept on
    the person's profile (core.language)."""

    tabs = USER_FORM_TABS
    language = forms.ChoiceField(
        label=_('Language'), required=False, choices=[('', _('Browser default'))] + settings.LANGUAGES,
        help_text=_('The language of the console and of the emails this person gets. '
                    'Left empty, it follows their browser.'),
    )

    class Meta:
        model = User
        fields = tab_fields(USER_FORM_TABS)
        labels = {'username': _('Username'), 'first_name': _('First name'), 'last_name': _('Last name'),
                  'email': _('Email'), 'is_active': _('Active'), 'groups': _('Roles')}
        help_texts = {
            'username': _('Used to sign in. Letters, digits and @ . + - _ only.'),
            'email': _('The invitation to set a password is sent here. Without an address the person cannot be '
                       'invited, and cannot sign in until one is added.'),
            'is_active': _('Inactive people cannot sign in.'),
            'groups': _('What the person can open and change. Without a role they see only the overview.'),
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': _('e.g. kari.nordmann')}),
            'email': forms.EmailInput(attrs={'placeholder': 'email@example.com'}),
            'groups': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
        }

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.initial['language'] = account_language(self.instance) or ''
        self.fields['groups'].queryset = Group.objects.order_by('name')
        if self.instance._state.adding:
            # A new person has no password until they set one through the invitation link.
            self.instance.set_unusable_password()

    def _save_m2m(self):
        super()._save_m2m()
        save_account_language(self.instance, self.cleaned_data['language'])

    def clean_email(self):
        """An address belongs to one person; it may be left out (the person then cannot be invited: accountmail)."""
        email = self.cleaned_data['email']
        if email and User.objects.exclude(pk=self.instance.pk).filter(email__iexact=email).exists():
            raise ValidationError(_('Another user already uses this email.'))
        return email

    def clean_is_active(self):
        active = self.cleaned_data['is_active']
        if not active and self.instance.pk == self.editor.pk:
            raise ValidationError(_('You cannot deactivate your own account.'))
        return active


class PasswordResetForm(auth_forms.PasswordResetForm):
    """Django's "Forgot your password?" form, also for people who have not set a password yet: users the platform
    admin creates start without one, so this is how an invited person whose link has expired gets a new one
    themselves. The mail takes the one path every account e-mail takes (core.accountmail)."""

    def save(self, **kwargs):
        """Hands the address over and nothing else (accountmail.reset_later): no account is looked up here, so the
        request does the same work and takes the same time for every address, and the page is told nothing: an
        address without an account, a request held back and a mail that failed are answered like one that went
        out. What Django's view hands over (the request, the templates' names) is not used: the link starts with the
        configured public address."""
        accountmail.reset_later(self.cleaned_data['email'])


PLATFORM_TABS = [
    ('records', _('Records'), ['correction_window_days', 'second_approval_withdrawal', 'unknown_withdrawal_days']),
    ('clocks', _('Clocks'), ['clock_tolerance_seconds']),
    ('plans', _('Plans'), ['plan_horizon_days']),
    ('degree_days', _('Degree-days'), ['sensor_day_hours', 'sensor_hold_seconds', 'assumption_cap_days',
                                         'probe_sample_tolerance_c']),
]


class PlatformSettingsForm(TabbedForm):
    """The platform owner's settings (core.models.PlatformSettings); the bounds are the database's."""

    tabs = PLATFORM_TABS

    class Meta:
        model = PlatformSettings
        fields = tab_fields(PLATFORM_TABS)
        help_texts = {
            'correction_window_days': _('How many days back a daily record (a stock operation, a feeding, a water sample, '
                                        'a movement of the store, a plan, a treatment) may be dated, and how old a record '
                                        'may be voided. Older records stay as they are. 1 to 3650; 31 until you set '
                                        'another.'),
            'second_approval_withdrawal': _('When ticked, going on past a medicine withdrawal (a harvest during one, a '
                                            'treatment reaching back over a harvest) needs a second person’s approval. '
                                            'That approval is not built yet: while this is ticked, every such step is '
                                            'refused, so nobody goes on alone.'),
            'unknown_withdrawal_days': _('How many days after a course’s last day a medicine withdrawal whose end is '
                                         'unknown because nothing says how long it lasts (a medicine with no '
                                         'withdrawal recorded for the species, medicated feed with no treatment) '
                                         'holds the fish. After them the fish are no longer held, and the course is '
                                         'listed as unresolved on the Treatments page until it is given an end. A '
                                         'withdrawal in degree-days is never let go this way: it holds until the water '
                                         'temperature is recorded or the species’ assumed temperature is set. 1 to '
                                         '3650; 180 until you set another. A change that would free fish held today, '
                                         'hold fish again or bring a recorded harvest inside a withdrawal asks '
                                         'first.'),
            'clock_tolerance_seconds': _('How far ahead of the server’s clock a water value may be stamped and still '
                                         'count as fresh (a device or tablet clock a little fast). A value further ahead, '
                                         'up to an hour, still decides its unit’s status and its alarm, but is not shown '
                                         'as the newest. 0 to 3600; 300 until you set another.'),
            'plan_horizon_days': _('How many days ahead a production plan walks a batch’s growth. A target weight not '
                                   'reached within them is said as not reached. 7 to 3650; 730 until you set '
                                   'another.'),
            'sensor_day_hours': _('How many of a day’s hours must each hold a good reading of a temperature probe before '
                                  'the probe’s daily mean counts for a medicine withdrawal or a purging fast. 12 to '
                                  '24; 20 until you set another. It applies to the days closed from now on: a closed '
                                  'day keeps the hours it was closed with.'),
            'sensor_hold_seconds': _('How long one probe reading stands for the water when no next one comes: its part '
                                     'of the daily mean. 60 to 3600 (an hour at most); 3600 until you set another. A '
                                     'closed day keeps the value it was closed with.'),
            'assumption_cap_days': _('A day without a measured water temperature counts at the species’ assumed '
                                     'temperature, but never above the coldest daily mean measured in this many '
                                     'calendar days before its gap of days without a measurement began (counted back '
                                     'from the gap, each day measured or not), nor above the first day measured after '
                                     'the gap. 1 to 30; 7 until you set another. A change that would free fish held '
                                     'today or bring a recorded harvest inside a withdrawal asks first.'),
            'probe_sample_tolerance_c': _('When a probe’s daily mean and the same day’s water samples differ by more '
                                          'than this, the withdrawal says so; the lower always counts. 0 to 10 °C; 1.0 '
                                          'until you set another.'),
        }
