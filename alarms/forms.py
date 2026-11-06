from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields
from farm.models import ProductionDepartment, Site

from .models import RecipientRule

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
                       'the Platform settings; and so on, up to 9.'),
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
