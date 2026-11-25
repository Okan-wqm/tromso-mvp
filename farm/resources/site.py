from django.utils.translation import gettext_lazy as _

from core import formpanels
from core.crud import Resource

from ..forms import SiteContactFormSet, SiteForm
from ..models import Site
from .contact import ContactList


class SiteContacts(ContactList):
    """A site's contacts, saved as a whole list on the Contact tab (the source replaces them too)."""

    formset = SiteContactFormSet
    help_text = _('The site’s operational contacts. At most one can be the primary contact. Contacts are saved separately '
                  'from the site details.')
    pending_text = _('Contacts can be added once the site is created.')


class SiteResource(Resource):
    model = Site
    form_class = SiteForm
    name, plural = _('site'), _('sites')
    url_prefix = 'sites'
    search_fields = ['name', 'code', 'region']
    list_template = 'farm/site_list.html'
    form_template = 'farm/site_form.html'
    icon = 'building'
    row_lists = (SiteContacts,)
    # A person's address and number: private in the activity log like a contact's (ContactList.describe, F-059).
    private_fields = ('contact_email', 'contact_phone')

    @classmethod
    def next_panels(cls, view, form, obj, extra):
        """farm/site_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

    # The list in the new look (core/listprops.py): the classic page's cards (farm/site_list.html), in its words.
    search_placeholder = _('Search by name, code or region')
    empty_text = _('Add the first site; production departments, systems and tanks are set up under a site.')

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.template.defaultfilters import floatformat
        from django.utils import formats

        from core import listprops as L
        from core.templatetags.dates import site_clock

        def location(site):
            return ', '.join(part for part in (site.region, site.country) if part) or None

        return {
            'columns': [L.column('site', _('Site')), L.column('status', _('Status')), L.column('type', _('Type')),
                        L.column('location', _('Location')), L.column('area', _('Area')),
                        L.column('contact', _('Contact')), L.column('created', _('Created'))],
            'cards': L.cards(chip='status', foot=['created']),
            'rows': [L.row(site.pk, {
                'site': L.title(view, context, site, site.name, sub=[site.code]),
                'status': L.badge(site.status, site.get_status_display()),
                'type': L.cell(site.get_type_display()),
                'location': L.cell(location(site)),
                'area': L.cell(f"{floatformat(site.area_m2, '-2g')} m²" if site.area_m2 is not None else None),
                'contact': L.cell(site.contact_email or None),
                'created': L.cell(_('Created %(date)s') % {
                    'date': formats.date_format(site_clock(site.created_at, site), 'DATE_FORMAT')}),
            }, L.edit_delete(view, context, site, site.name)) for site in objects],
        }
