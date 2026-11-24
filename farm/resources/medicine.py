from django.utils.translation import gettext as _now, gettext_lazy as _, ngettext_lazy

from core import formpanels
from core.crud import Resource, RowList, filter_by
from core.models import AuditLog

from ..forms.health import MedicineForm, MedicineWithdrawalFormSet
from ..health import withdrawal
from ..health.withdrawal import Rule
from ..models import Medicine, Treatment
from ..stock.dates import earliest_today
from ..stock.services import lock_fish


class MedicineWithdrawalList(RowList):
    """A medicine's withdrawal per species (and for every species without a row of its own), saved as a whole list
    on its Withdrawal tab, like a feed's suitability."""

    key, tab, label = 'withdrawals', 'withdrawal', _('Withdrawal')
    question_field = withdrawal.FIELD
    formset = MedicineWithdrawalFormSet
    # Its panel's words (farm/medicine_form.html; its per cent sign doubled, as the template's msgid has it:
    # core.formpanels.said); a refused save asks the guard's question above the rows.
    title = _('Withdrawal')
    help_text = _('The withdrawal after the last treatment day, as the SPC states it: degree-days (døgngrader) and days, one '
                  'or both, per species; leave the species empty for every species without a row of its own. Give both '
                  'when the SPC gives both: the later end wins. 0 means none. The safety margin is your own, on top of the '
                  'SPC’s value: the value used is rounded up, e.g. 150 degree-days and 20 %% is 180. Fish of a species with '
                  'no row (and no row for every species) are held with an unknown end. One row per species, at most 50. '
                  'They are saved separately from the medicine details.')
    empty_text = _('No withdrawal yet. Use “Add species” to add a row.')
    add_label, save_label = _('Add species'), _('Save withdrawal')
    pending_text = _('The withdrawal can be added once the medicine is created.')
    row_kind = 'withdrawal-row'
    saved = ngettext_lazy('%(count)d withdrawal row saved.', '%(count)d withdrawal rows saved.', 'count')

    @classmethod
    def severity(cls, medicine):
        """Critical once the medicine was given (a live treatment): its withdrawal is worked out live from these rows
        (HLT-02), so a change moves the end of every course already given, of fish held now or harvested (F-196)."""
        given = medicine.treatments.exists()
        return AuditLog.Severity.CRITICAL if given else AuditLog.Severity.NORMAL

    @classmethod
    def save(cls, user, medicine, rows, entity_type, seen=None):
        """The rows saved through the withdrawal guard (farm.health.withdrawal.guarded): the withdrawal is worked out live
        from them, so a change moves every course already given with the medicine, and a harvest it brings inside a
        withdrawal or fish held today that it frees are asked about first. The batches those courses reached are locked,
        as a stock operation locks them."""
        treatments = Treatment.objects.filter(medicine=medicine).prefetch_related('units')
        unit_ids = {unit.pk for treatment in treatments for unit in treatment.units.all()}
        first = min((treatment.start_date for treatment in treatments), default=None)
        units, batch_ids = lock_fish(unit_ids, first) if first else ({}, set())
        today = earliest_today(units.values())
        withdrawal.guarded(user, batch_ids, today, lambda: super(MedicineWithdrawalList, cls).save(
            user, medicine, rows, entity_type) or medicine, record_of=lambda _result: medicine, seen=seen)

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
    def next_panels(cls, view, form, obj, extra):
        """farm/medicine_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

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
