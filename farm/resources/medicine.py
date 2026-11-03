from django.utils.translation import gettext_lazy as _

from core.crud import Resource, filter_by

from ..forms.health import MedicineForm
from ..models import Medicine


class MedicineResource(Resource):
    """Setup › Reference data › Medicines: the medicines and vaccines the farm uses, with their withdrawal."""

    model = Medicine
    form_class = MedicineForm
    name, plural = _('medicine'), _('medicines')
    url_prefix = 'medicines'
    search_fields = ['name', 'active_substance', 'marketing_authorisation', 'manufacturer__name']
    list_template = 'farm/medicine_list.html'
    icon = 'pill'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('manufacturer')

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_kind = filter_by(request, objects, 'kind', Medicine.Kind.choices, 'kind')
        objects, chosen_administration = filter_by(request, objects, 'administration',
                                                   Medicine.Administration.choices, 'administration')
        objects, chosen_status = filter_by(request, objects, 'status', Medicine.Status.choices, 'status')
        return objects, {
            'kinds': Medicine.Kind.choices, 'chosen_kind': chosen_kind,
            'administrations': Medicine.Administration.choices, 'chosen_administration': chosen_administration,
            'statuses': Medicine.Status.choices, 'chosen_status': chosen_status,
        }
