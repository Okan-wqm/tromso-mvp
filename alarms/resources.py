from django.utils.translation import gettext_lazy as _

from core.crud import Resource
from core.dbgrid import PAGE_SIZE

from . import read
from .forms import ParameterDeadbandForm, RecipientRuleForm, SeverityPolicyForm
from .models import ParameterDeadband, RecipientRule, SeverityPolicy


class RecipientRuleResource(Resource):
    """Who is notified of which alarms, at which level (Company › Alarms › Alarm recipients)."""

    model = RecipientRule
    form_class = RecipientRuleForm
    name, plural = _('alarm recipient rule'), _('alarm recipient rules')
    url_prefix = 'alarms/recipients'
    list_template = 'alarms/recipientrule_list.html'
    icon = 'send'
    page_size = PAGE_SIZE

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'production_department', 'role', 'user')

    @classmethod
    def filter_list(cls, request, objects):
        return objects, {'connected': read.connected()}


class SeverityPolicyResource(Resource):
    """The rules of each severity (Company › Alarms › Alarm severity rules): one row per severity, seeded, changed only."""

    model = SeverityPolicy
    form_class = SeverityPolicyForm
    name, plural = _('alarm severity rule'), _('alarm severity rules')
    url_prefix = 'alarms/severity-rules'
    actions = ('change',)
    list_template = 'alarms/severitypolicy_list.html'
    icon = 'timer'

    @classmethod
    def filter_list(cls, request, objects):
        """The unusual values of the rows (SeverityPolicy.advice), shown above them."""
        return objects, {'advice': [line for policy in objects for line in policy.advice()]}


class ParameterDeadbandResource(Resource):
    """The deadband of each water parameter (Company › Alarms › Alarm deadbands)."""

    model = ParameterDeadband
    form_class = ParameterDeadbandForm
    name, plural = _('alarm deadband'), _('alarm deadbands')
    url_prefix = 'alarms/deadbands'
    list_template = 'alarms/parameterdeadband_list.html'
    icon = 'gauge'

    @classmethod
    def filter_list(cls, request, objects):
        """The unusual deadbands (ParameterDeadband.advice against the live water limits), shown above them."""
        from farm.models import WaterLimit
        limits = {}
        for row in WaterLimit.objects.all():
            limits.setdefault(row.parameter, []).append(row)
        return objects, {'advice': [line for row in objects for line in row.advice(limits.get(row.parameter, []))]}
