from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields
from core.widgets import DayInput

from ..models import Site, SiteContact
from ..models.site import company_zone
from .contact import contact_formset

# The source form's inner tabs (Basic info / Location info / Contact info) and their fields.
SITE_FORM_TABS = [
    ('basic', _('Basic info'), [
        'name', 'code', 'lokalitetsnummer', 'description',
        'type', 'status', 'area_m2', 'timezone',
    ]),
    ('location', _('Location'), [
        'country', 'region', 'lice_area', 'street', 'city', 'state', 'postal_code', 'latitude', 'longitude',
        'altitude',
    ]),
    ('contact', _('Contact'), ['site_manager', 'contact_email', 'contact_phone']),
    # What the regulatory reports need of the site (Production › Reports).
    ('reports', _('Reports'), ['organisation_number', 'production_form', 'reports_from']),
]


class OrganisationNumberField(forms.CharField):
    """Nine digits, typed as printed (987 654 321) or plain, stored plain."""

    default_validators = [RegexValidator(r'^[0-9]{9}$', _('An organisation number is 9 digits.'))]

    def to_python(self, value):
        return ''.join(super().to_python(value).split())

    def widget_attrs(self, widget):
        return {**super().widget_attrs(widget), 'maxlength': '11'}    # with its two spaces


class SiteForm(CodedFormMixin, TabbedForm):
    tabs = SITE_FORM_TABS

    class Meta:
        model = Site
        fields = tab_fields(SITE_FORM_TABS)
        # Quantities are typed and shown the way the language writes them (50000,5 or 50000.5), so
        # they are text inputs: a number input would use the browser's own language instead.
        localized_fields = ['area_m2', 'latitude', 'longitude', 'altitude']
        field_classes = {'organisation_number': OrganisationNumberField}
        help_texts = {
            'lokalitetsnummer': _('Akvakulturregisteret locality number (5 digits). '
                                  'Norwegian regulatory reports cannot be filed without it.'),
            'timezone': _('The site’s day and clock: feeding days, shifts, punches and plans are read in it. The '
                          'company’s is offered first.'),
            'organisation_number': _('The permit holder’s, which owns the fish: the reports to Mattilsynet and '
                                     'Fiskeridirektoratet carry it. Nine digits.'),
            'production_form': _('Juveniles, food fish, broodstock, or research and other production: it decides the reports '
                                 'the site owes.'),
            'reports_from': _('Its reports are listed as due from this day; leave it empty while they are filed '
                              'elsewhere.'),
            'latitude': _('Required for a sea cage.'),
            'lice_area': _('For a sea site with salmonids: the lower sea-lice limit of spring runs in weeks 16–21 '
                           'from Nord-Trøndelag southwards and in weeks 21–26 in Nordland, Troms and Finnmark '
                           '(lakselusforskriften § 8).'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Main Production Site')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. MPS-001'), 'data-uppercase': ''}),
            'lokalitetsnummer': forms.NumberInput(attrs={'placeholder': _('e.g. 12345'), 'min': 10000, 'max': 99999}),
            'organisation_number': forms.TextInput(
                attrs={'placeholder': _('9-digit Norwegian organisation number'), 'inputmode': 'numeric'}),
            'reports_from': DayInput(),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': _('Brief description of the site')}),
            'area_m2': forms.TextInput(attrs={'placeholder': _('e.g. 50000'), 'inputmode': 'decimal'}),
            'country': forms.TextInput(attrs={'placeholder': _('e.g. Norway')}),
            'region': forms.TextInput(attrs={'placeholder': _('e.g. Vestland')}),
            'latitude': forms.TextInput(attrs={'placeholder': _('e.g. 60.3913'), 'inputmode': 'decimal'}),
            'longitude': forms.TextInput(attrs={'placeholder': _('e.g. 5.3221'), 'inputmode': 'decimal'}),
            'altitude': forms.TextInput(attrs={'placeholder': _('Optional'), 'inputmode': 'decimal'}),
            'site_manager': forms.TextInput(attrs={'placeholder': _('Full name of the site manager')}),
            'contact_email': forms.EmailInput(attrs={'placeholder': 'email@example.com'}),
            'contact_phone': forms.TextInput(attrs={'placeholder': '+47 XXX XX XXX', 'type': 'tel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        zone = self.fields['timezone']
        listed = Site.TIMEZONES if company_zone() in dict(Site.TIMEZONES) else [(company_zone(), company_zone())] + Site.TIMEZONES
        zone.choices = sorted(listed, key=lambda choice: choice[0] != company_zone())             # the company's first
        if not self.instance.pk:
            zone.initial = company_zone()
        self.fields['lice_area'].choices = [('', _('Not set'))] + list(Site.LiceArea.choices)
        self.fields['production_form'].choices = [('', _('Not set'))] + list(Site.ProductionForm.choices)

    def clean(self):
        cleaned = super().clean()
        latitude, longitude = cleaned.get('latitude'), cleaned.get('longitude')
        if cleaned.get('type') == Site.Type.SEA_CAGE:
            if latitude is None and 'latitude' not in self.errors:
                self.add_error('latitude', _('Latitude is required for a sea cage.'))
            if longitude is None and 'longitude' not in self.errors:
                self.add_error('longitude', _('Longitude is required for a sea cage.'))
        elif (latitude is None) != (longitude is None):
            field = 'longitude' if longitude is None else 'latitude'
            self.add_error(field, _('Latitude and longitude must be provided together.'))
        return cleaned


SiteContactFormSet = contact_formset(Site, SiteContact)
