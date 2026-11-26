from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _

from core import listprops as L
from core.crud import Resource

from ..forms.weight_source import WeightSourceForm
from ..models import WeightSource

HOW = _('How an average weight was measured. Every weighing names its source, so a production plan reads the measured '
        'weights one way whatever measured them: a sample weighed by hand today, a biomass camera when the farm has '
        'one. A weighing takes “Manual sample” unless another source is chosen; the choice is offered in the weighing '
        'dialog once there is more than one source.')


class WeightSourceResource(Resource):
    """Setup › Reference data › Weight sources: what measured a weighing's average (a sample by hand, later a
    camera), named by every weighing line."""

    model = WeightSource
    form_class = WeightSourceForm
    name, plural = _('weight source'), _('weight sources')
    url_prefix = 'weight-sources'
    search_fields = ['name', 'code', 'notes']
    list_template = 'farm/weight_source_list.html'
    icon = 'gauge'
    search_placeholder = _('Search by name, code or notes')
    empty_text = _('How an average weight was measured: a sample weighed by hand, a biomass camera.')

    @classmethod
    def queryset(cls):
        return super().queryset().annotate(used=Count('weighings', filter=Q(weighings__operation__is_deleted=False)))

    @classmethod
    def filter_list(cls, request, objects):
        return objects, {'how': HOW}

    @classmethod
    def list_rows(cls, view, objects, context):
        return {
            'columns': [L.column('name', _('Name')), L.column('code', _('Code')),
                        L.column('used', _('Weighings'), numeric=True), L.column('notes', _('Notes'))],
            'notices': [L.notice('how', 'info', HOW)],
            'rows': [L.row(source.pk, {
                'name': L.title(view, context, source, source.name),
                'code': L.cell(source.code), 'used': L.cell(source.used), 'notes': L.cell(source.notes or '—'),
            }, L.edit_delete(view, context, source, str(source))) for source in objects],
        }
