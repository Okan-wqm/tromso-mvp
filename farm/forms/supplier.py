from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields

from ..models import Supplier, SupplierContact
from ..models.supplier import RATINGS, SUPPLIES_MESSAGE, normalise_organisation_number
from .contact import contact_formset

SUPPLIER_FORM_TABS = [
    ('basic', _('Basic info'), ['name', 'code', 'organisation_number', 'supplies', 'status', 'rating']),
    ('contact', _('Contact'), ['email', 'phone', 'website']),
    ('address', _('Address'), ['street', 'postal_code', 'city', 'country']),
    ('sites', _('Sites'), ['sites']),
    ('terms', _('Terms and notes'), ['payment_terms', 'notes']),
]


class SupplierForm(CodedFormMixin, TabbedForm):
    """The supplier dialog. Its contact persons are a list of their own on the Contact tab (a RowList,
    like a site's contacts)."""

    tabs = SUPPLIER_FORM_TABS

    class Meta:
        model = Supplier
        fields = tab_fields(SUPPLIER_FORM_TABS)
        help_texts = {
            'code': _('Your own short code: capital letters, digits, hyphens and underscores.'),
            'organisation_number': _('Its company registration or VAT number, e.g. 923456789 in Norway; spaces are '
                                     'left out.'),
            'supplies': _('Everything the farm buys from it, goods and services. Equipment can be bought only from '
                          'a supplier of equipment and spare parts.'),
            'status': _('Active: buy from it. Inactive: not used at the moment. Suspended: on hold, e.g. during a '
                        'complaint. Blocked: never buy from it.'),
            'rating': _('Your own rating, from 1 (poor) to 5 (excellent).'),
            'email': _('The address for orders and questions; contact persons have their own below.'),
            'website': _('https:// is added when it is left out.'),
            'sites': _('The sites it delivers to or works at.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Fjord Feed AS')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. FJF'), 'data-uppercase': ''}),
            'organisation_number': forms.TextInput(attrs={'placeholder': _('e.g. 923456789'), 'data-uppercase': ''}),
            'supplies': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'email': forms.EmailInput(attrs={'placeholder': 'orders@example.com'}),
            'phone': forms.TextInput(attrs={'placeholder': '+47 XXX XX XXX', 'type': 'tel'}),
            'website': forms.URLInput(attrs={'placeholder': 'https://example.com'}),
            'street': forms.TextInput(attrs={'placeholder': _('e.g. Kaien 1')}),
            'country': forms.TextInput(attrs={'placeholder': _('e.g. Norway')}),
            'sites': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'payment_terms': forms.TextInput(attrs={'placeholder': _('e.g. 30 days net')}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
        error_messages = {'supplies': {'required': SUPPLIES_MESSAGE}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rating'].choices = [('', _('Not rated'))] + RATINGS

    def clean_organisation_number(self):
        return normalise_organisation_number(self.cleaned_data['organisation_number'])


SupplierContactFormSet = contact_formset(Supplier, SupplierContact)
