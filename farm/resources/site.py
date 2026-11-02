from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.crud import Resource, RowList

from ..forms import SiteContactFormSet, SiteForm
from ..models import Site


class SiteContacts(RowList):
    """A site's contacts, saved as a whole list on the Contact tab (the source replaces them too)."""

    key, tab, label = 'contacts', 'contact', _('Contacts')
    formset = SiteContactFormSet
    saved = ngettext_lazy('%(count)d contact saved.', '%(count)d contacts saved.', 'count')

    @classmethod
    def describe(cls, contact):
        """e.g. "Kari (Manager, kari@x.no, primary)"; the word "primary" is stored in English."""
        details = [value for value in (contact.role, contact.email, contact.phone) if value]
        if contact.is_primary:
            details.append(gettext('primary'))
        return f'{contact.name} ({", ".join(details)})' if details else contact.name


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
