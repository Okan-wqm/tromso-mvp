from django.utils.translation import gettext as _now, gettext_lazy as _, ngettext_lazy

from core import formpanels, listprops as L
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

    # The list in the new look (core/listprops.py), in the classic list's words (farm/medicine_list.html).
    search_placeholder = _('Search by name, substance, MT number or manufacturer')
    empty_text = _('The medicines and vaccines the farm uses, with their withdrawal before harvest.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('kind', _('Kind'), context['chosen_kind'], [('', _('All kinds')), *context['kinds']]),
            L.choice('administration', _('Administration'), context['chosen_administration'],
                     [('', _('Every way of giving')), *context['administrations']]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.template.defaultfilters import floatformat

        def withdrawal_cell(medicine):
            lines = withdrawal.rule_lines(medicine)
            if not lines:
                return L.cell(_('Not recorded'),
                              sub=[_('A treatment with it holds the fish with an unknown end until a withdrawal is added.')])
            several = len(medicine.withdrawals.all()) > 1
            return L.cell('; '.join(f'{who}: {rule.text()}' if several else rule.text() for who, rule in lines),
                          sub=[rule.row.note for _who, rule in lines])

        notices = [L.notice('withdrawal', 'info', _(
            'The withdrawal is the product’s, as its SPC states it per species, in degree-days, days or both, with your own '
            'safety margin on top; nothing is filled in for you. A treatment counts it from its last day, on the water '
            'temperature of the fish’s units (Operations › Treatments). Fish of a species with no withdrawal recorded are '
            'held with an unknown end.'))]
        return {
            'columns': [L.column('medicine', _('Medicine')), L.column('kind', _('Kind')),
                        L.column('substance', _('Active substance')), L.column('strength', _('Strength')),
                        L.column('withdrawal', _('Withdrawal')), L.column('manufacturer', _('Manufacturer')),
                        L.column('status', _('Status'))],
            'notices': notices,
            'rows': [L.row(medicine.pk, {
                'medicine': L.title(view, context, medicine, medicine.name, sub=[' · '.join(
                    str(part) for part in (medicine.marketing_authorisation,
                                           _('Prescription only') if medicine.prescription_only else '') if part)]),
                'kind': L.cell(medicine.get_kind_display(), sub=[medicine.get_administration_display()]),
                'substance': L.cell(medicine.active_substance, sub=[
                    medicine.get_lice_report_code_display() if medicine.lice_report_code else '']),
                'strength': L.cell(f'{floatformat(medicine.strength_value, "-3")} {medicine.get_strength_unit_display()}'
                                   if medicine.strength_value is not None else '—'),
                'withdrawal': withdrawal_cell(medicine),
                'manufacturer': L.cell(medicine.manufacturer.name if medicine.manufacturer else '—'),
                'status': L.badge(medicine.status, medicine.get_status_display()),
            }, L.edit_delete(view, context, medicine, medicine.name)) for medicine in objects],
        }
