from django.utils.translation import gettext as _now, gettext_lazy as _, ngettext_lazy

from core.crud import Resource, RowList, filter_by
from core.models import AuditLog

from ..forms.health import MedicineForm, MedicineWithdrawalFormSet
from ..health.withdrawal import Rule
from ..models import Medicine


class MedicineWithdrawalList(RowList):
    """A medicine's withdrawal per species (and for every species without a row of its own), saved as a whole list
    on its Withdrawal tab, like a feed's suitability."""

    key, tab, label = 'withdrawals', 'withdrawal', _('Withdrawal')
    formset = MedicineWithdrawalFormSet
    saved = ngettext_lazy('%(count)d withdrawal row saved.', '%(count)d withdrawal rows saved.', 'count')

    @classmethod
    def severity(cls, medicine):
        """Critical once the medicine was given (a live treatment): its withdrawal is worked out live from these rows
        (HLT-02), so a change moves the end of every course already given, of fish held now or harvested (F-196)."""
        given = medicine.treatments.exists()
        return AuditLog.Severity.CRITICAL if given else AuditLog.Severity.NORMAL

    @classmethod
    def describe(cls, row):
        """e.g. "Atlantic salmon: 150 degree-days + 20 % safety margin = 180 degree-days (SPC 2024)", in English."""
        text = f'{row.species.common_name if row.species_id else _now("Every species")}: {Rule.of(row).text()}'
        return f'{text} ({row.note})' if row.note else text


class MedicineResource(Resource):
    """Setup › Reference data › Medicines: the medicines and vaccines the farm uses, with their withdrawal per
    species."""

    model = Medicine
    form_class = MedicineForm
    name, plural = _('medicine'), _('medicines')
    url_prefix = 'medicines'
    search_fields = ['name', 'active_substance', 'marketing_authorisation', 'manufacturer__name']
    list_template = 'farm/medicine_list.html'
    form_template = 'farm/medicine_form.html'
    icon = 'pill'
    row_lists = (MedicineWithdrawalList,)
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('manufacturer').prefetch_related('withdrawals__species')

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
