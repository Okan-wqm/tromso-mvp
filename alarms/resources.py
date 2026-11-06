from django.utils.translation import gettext_lazy as _

from core.crud import Resource

from . import read
from .forms import RecipientRuleForm
from .models import RecipientRule


class RecipientRuleResource(Resource):
    """Who is notified of which alarms, at which level (Company › Alarms › Alarm recipients)."""

    model = RecipientRule
    form_class = RecipientRuleForm
    name, plural = _('alarm recipient rule'), _('alarm recipient rules')
    url_prefix = 'alarms/recipients'
    list_template = 'alarms/recipientrule_list.html'
    icon = 'send'
    page_size = 100

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'production_department', 'role', 'user')

    @classmethod
    def filter_list(cls, request, objects):
        return objects, {'connected': read.connected()}
