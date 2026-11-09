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


POLICY_TABS = [('rule', _('Rule'), ['on_delay_seconds', 'off_delay_seconds', 'escalation_minutes', 'delivery_attempts'])]
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
        }


class ParameterDeadbandForm(TabbedForm):
    """How far past its limit a value must come back before an alarm on it clears (alarms.models.ParameterDeadband)."""

    tabs = DEADBAND_TABS

    class Meta:
        model = ParameterDeadband
        fields = tab_fields(DEADBAND_TABS)
        localized_fields = ['deadband']
        help_texts = {'deadband': _('In the parameter’s unit. 0: no deadband.')}
