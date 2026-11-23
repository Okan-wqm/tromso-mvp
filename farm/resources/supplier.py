from django.utils.translation import gettext_lazy as _

from core.crud import Resource, filter_by

from ..forms import SupplierContactFormSet, SupplierForm
from ..models import Site, Supplier
from .contact import ContactList


class SupplierContacts(ContactList):
    """A supplier's contact persons, saved as a whole list on the Contact tab, like a site's contacts."""

    formset = SupplierContactFormSet


class SupplierResource(Resource):
    model = Supplier
    form_class = SupplierForm
    name, plural = _('supplier'), _('suppliers')
    url_prefix = 'suppliers'
    search_fields = ['name', 'code', 'organisation_number', 'email', 'city', 'country']
    list_template = 'farm/supplier_list.html'
    form_template = 'farm/supplier_form.html'
    icon = 'truck'
    # A supplier may be one person (a vet, a diver) and the form cannot know: its own e-mail and phone are private in
    # the activity log like a site's contact e-mail (review R7). Its name, organisation number and address stay.
    private_fields = ('email', 'phone')
    row_lists = (SupplierContacts,)
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().prefetch_related('contacts', 'sites')

    @classmethod
    def filter_list(cls, request, objects):
        chosen_category = request.GET.get('supplies', '')
        if chosen_category in Supplier.Category.values:
            objects = objects.filter(supplies__contains=[chosen_category])
        else:
            chosen_category = ''
        objects, chosen_status = filter_by(request, objects, 'status', Supplier.Status.choices, 'status')
        sites = Site.objects.all()
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'sites')
        return objects, {
            'categories': Supplier.Category.choices, 'chosen_category': chosen_category,
            'statuses': Supplier.Status.choices, 'chosen_status': chosen_status,
            'sites': sites, 'chosen_site': chosen_site,
        }
