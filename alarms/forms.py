from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from farm.models import ProductionDepartment, Site

from .models import ParameterDeadband, RecipientRule, SeverityPolicy

RULE_TABS = [
    ('where', _('Which alarms'), ['site', 'production_department', 'min_severity', 'level']),
    ('who', _('Who'), ['role', 'user', 'on_shift_only', 'channel', 'is_active']),
]


class RecipientRuleForm(TabbedForm):
    """Who is notified of which alarms (alarms.models.RecipientRule)."""

    tabs = RULE_TABS

    class Meta:
        model = RecipientRule
        fields = tab_fields(RULE_TABS)
        help_texts = {
            'site': _('Empty: the alarms of every site.'),
            'production_department': _('Empty: every department of the site. A department must be on the site.'),
            'min_severity': _('Warning reaches warnings and criticals; Critical reaches criticals only.'),
            'level': _('0: notified when the alarm opens. 1: when nobody acknowledged level 0 in the escalation time of '
                       'its severity (Alarm severity rules); and so on, up to 9.'),
            'role': _('Everyone active with this role; or choose one person below instead.'),
            'on_shift_only': _('Only the people on shift by the roster when the alarm reaches this level.'),
            'channel': _('Push: the mobile app. Nothing is sent until the push transport is connected.'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['site'].queryset = Site.objects.order_by('name')
        self.fields['production_department'].queryset = ProductionDepartment.objects.select_related('site').order_by(
            'site__name', 'name')
        self.fields['role'].queryset = Group.objects.order_by('name')
        self.fields['user'].queryset = get_user_model().objects.filter(is_active=True).order_by('username')
        self.fields['user'].label_from_instance = lambda person: person.get_full_name() or person.get_username()
        for name, empty in (('site', _('Every site')), ('production_department', _('Every department')),
                            ('role', _('None')), ('user', _('None'))):
            self.fields[name].empty_label = empty


POLICY_TABS = [('rule', _('Rule'), ['on_delay_seconds', 'off_delay_seconds', 'escalation_minutes', 'delivery_attempts',
                                     'retry_seconds', 'shelve_max_minutes', 'flood_count', 'flood_window_seconds']),
               ('clock', _('Device clock'), ['clock_skew_seconds', 'clock_skew_deadband_seconds',
                                             'clock_behind_window_seconds'])]
DEADBAND_TABS = [('deadband', _('Deadband'), ['parameter', 'deadband'])]


class SeverityPolicyForm(TabbedForm):
    """How alarms of one severity behave (alarms.models.SeverityPolicy); the bounds are the database's."""

    tabs = POLICY_TABS

    class Meta:
        model = SeverityPolicy
        fields = tab_fields(POLICY_TABS)
        help_texts = {
            'on_delay_seconds': _('How long the condition must hold, counted from the first value past the limit, before '
                                  'the alarm is raised. 0: at once.'),
            'off_delay_seconds': _('How long the value must be back inside the limit, by the deadband, before the alarm '
                                   'clears.'),
            'escalation_minutes': _('How long the people notified at one level have to acknowledge before the next level '
                                    'is notified.'),
            'delivery_attempts': _('How many times a failing transport is tried with one notification.'),
            'retry_seconds': _('How long after a failed attempt the notification is tried again. 1 to 3600.'),
            'flood_count': _('From this many alarms of one kind (one site, this severity, one quantity, rule or check) '
                             'within the flood window, a person gets one flood message for them. 2 to 1000.'),
            'flood_window_seconds': _('How long the alarms of a flood are counted together, and how long a flood message '
                                      'covers the ones that come after it. 10 to 3600.'),
            'shelve_max_minutes': _('The longest an alarm of this severity may be snoozed: nobody is notified of it and '
                                    'it is not escalated meanwhile. Critical 1 to 480, warning 1 to 1440.'),
            'clock_skew_seconds': _('A device whose clock is further ahead of or behind the platform’s than this, '
                                    'measured from its newest value against when it was received, raises this alarm. '
                                    '1 to 3600; the warning’s below the critical’s. Ahead: the ingest replaces a '
                                    'device time further ahead than its contract’s future skew (60 s by default) by '
                                    'the time it received the value, so the values stay right and ahead is measured '
                                    'as “more than” that: a limit above the future skew is reached only behind.'),
            'clock_skew_deadband_seconds': _('How far back inside the limit the clock must come before the alarm clears. '
                                             'Below the limit.'),
            'clock_behind_window_seconds': _('A device behind is raised only when it is behind on every pass for this '
                                             'long: values delivered late (an ingest restart, a gateway sending what it '
                                             'stored during a link drop) are not a slow clock. While the ingest reports '
                                             'waiting messages, behind is not judged at all. Ahead is judged at once. '
                                             '0 to 3600; 600 until you set another.'),
        }


class ParameterDeadbandForm(TabbedForm):
    """How far past its limit a value must come back before an alarm on it clears (alarms.models.ParameterDeadband)."""

    tabs = DEADBAND_TABS

    class Meta:
        model = ParameterDeadband
        fields = tab_fields(DEADBAND_TABS)
        localized_fields = ['deadband']
        help_texts = {'deadband': _('In the parameter’s unit. 0: no deadband.')}
