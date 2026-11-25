from django.utils.translation import gettext_lazy as _

from core import formpanels, listprops as L
from core.crud import Resource, filter_by

from ..forms import SupplierContactFormSet, SupplierForm
from ..models import Site, Supplier
from .contact import ContactList


class SupplierContacts(ContactList):
    """A supplier's contact persons, saved as a whole list on the Contact tab, like a site's contacts."""

    formset = SupplierContactFormSet
    help_text = _('The people to contact at the supplier: sales, orders, technical support, the vet on call. At most one can '
                  'be the primary contact. Contacts are saved separately from the supplier details.')
    pending_text = _('Contacts can be added once the supplier is created.')


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
    def next_panels(cls, view, form, obj, extra):
        """farm/supplier_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

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

    # The list in the new look (core/listprops.py), in the classic list's words (farm/supplier_list.html).
    search_placeholder = _('Search by name, code, organisation number, email or place')
    empty_text = _('The companies the farm buys from: feed, live fish and eggs, equipment, medicines and services such as '
                   'vets, divers and wellboats.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('supplies', _('Supplies'), context['chosen_category'],
                     [('', _('Everything supplied')), *context['categories']]),
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        def contact(supplier):
            person = supplier.primary_contact()
            reach = ' · '.join(part for part in (supplier.email, supplier.phone) if part)
            if person is None:
                return L.cell(reach or '–')
            return L.cell(person.name, sub=[person.role, reach])

        def rating(supplier):
            if not supplier.rating:
                return L.cell('–')
            return L.cell(f'{supplier.rating}/5', sub=[_('%(rating)s of 5') % {'rating': supplier.rating}])

        return {
            'columns': [L.column('supplier', _('Supplier')), L.column('supplies', _('Supplies')),
                        L.column('contact', _('Contact')), L.column('place', _('Place')),
                        L.column('sites', _('Sites served')), L.column('rating', _('Rating')),
                        L.column('status', _('Status'))],
            'rows': [L.row(supplier.pk, {
                'supplier': L.title(view, context, supplier, supplier.name, sub=[' · '.join(
                    part for part in (supplier.code, supplier.organisation_number) if part)]),
                'supplies': L.cell(', '.join(str(each) for each in supplier.supplies_labels())),
                'contact': contact(supplier),
                'place': L.cell(', '.join(part for part in (supplier.city, supplier.country) if part) or '–'),
                'sites': L.cell(', '.join(site.name for site in supplier.sites.all()) or '–'),
                'rating': rating(supplier),
                'status': L.badge(supplier.status, supplier.get_status_display()),
            }, L.edit_delete(view, context, supplier, supplier.name)) for supplier in objects],
        }
