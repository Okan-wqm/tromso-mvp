from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm

from ..models import ProductionDepartment, Site


class ProductionDepartmentForm(CodedFormMixin, TabbedForm):
    tabs = [('details', _('Details'), ['name', 'code', 'type', 'site', 'manager', 'capacity', 'notes'])]
    fixed_after_creation = ('site',)

    class Meta:
        model = ProductionDepartment
        fields = ['name', 'code', 'type', 'site', 'manager', 'capacity', 'notes']
        localized_fields = ['capacity']
        help_texts = {
            'site': _('A production department stays on the site it was created on.'),
            'manager': _('Sees and plans this department’s people in HR (with a role that gives the HR pages).'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Hatchery hall A')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. HAT-A'), 'data-uppercase': ''}),
            'capacity': forms.TextInput(attrs={'inputmode': 'decimal'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        site = self.fields['site']
        site.queryset = Site.objects.all()
        site.empty_label = _('Select a site')
        # Anyone who can sign in; the person already chosen stays offered after their account is deactivated.
        self.fields['manager'].queryset = get_user_model().objects.filter(
            Q(is_active=True) | Q(pk=self.instance.manager_id)).order_by('username')
        self.fields['manager'].empty_label = _('No manager')
        # The Manager decides whose people a person reaches in HR, so only those who administer HR choose it: someone who
        # edits production departments cannot make themselves the manager of a team.
        if editor is None or not (editor.has_perm('hr.all_employee') or editor.has_perm('hr.change_officedepartment')):
            self.fields['manager'].disabled = True
            self.fields['manager'].help_text = _('Chosen by the people who administer HR.')
