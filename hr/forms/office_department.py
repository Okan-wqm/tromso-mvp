from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields
from farm.models import Site

from ..models import OfficeDepartment

TABS = [('details', _('Details'), ['name', 'code', 'parent', 'site', 'manager', 'status', 'description'])]


class OfficeDepartmentForm(CodedFormMixin, TabbedForm):
    """An office department. A new one needs a site (it gives its people their clock); the database allows a
    department whose site was deleted. A department cannot be nested under itself or under what is below it: the
    form says so on the field, and a trigger refuses it whatever writes."""

    tabs = TABS

    class Meta:
        model = OfficeDepartment
        fields = tab_fields(TABS)
        help_texts = {
            'parent': _('The department this one belongs to in the organisation chart; none for a top-level one.'),
            'site': _('The site whose clock the department’s people work on: the day and the time of every HR '
                      'page. Set the site’s time zone on the site.'),
            'manager': _('Sees and plans this department’s people, and those of the departments below it, in HR '
                         '(with a role that gives the HR pages).'),
            'status': _('Inactive: kept, shown as such, not offered for new placements.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Finance')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. FIN'), 'data-uppercase': ''}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        adding = self.instance._state.adding
        self.fields['parent'].queryset = OfficeDepartment.objects.all()
        self.fields['parent'].empty_label = _('No parent (top level)')
        site = self.fields['site']
        site.queryset = Site.objects.all()
        site.required = adding
        site.empty_label = _('Select a site') if adding else _('No site')
        self.fields['manager'].queryset = get_user_model().objects.filter(
            Q(is_active=True) | Q(pk=self.instance.manager_id)).order_by('username')
        self.fields['manager'].empty_label = _('No manager')

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get('parent')
        if parent is not None and not self.instance._state.adding:
            self.instance.parent = parent
            if self.instance.nested_under_itself():
                self.add_error('parent', ValidationError(_('A department cannot be nested under itself or under '
                                                         'one of its own departments.')))
        return cleaned
