from django.utils.translation import gettext_lazy as _

from core.crud import Resource

from ..forms import SiteContactFormSet, SiteForm
from ..models import Site
from .contact import ContactList


class SiteContacts(ContactList):
    """A site's contacts, saved as a whole list on the Contact tab (the source replaces them too)."""

    formset = SiteContactFormSet


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
