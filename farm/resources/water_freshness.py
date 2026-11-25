from django.utils.translation import gettext_lazy as _

from core.crud import Resource

from ..forms.water import WaterFreshnessForm
from ..models import WaterFreshness


class WaterFreshnessResource(Resource):
    """Setup › Reference data › Water freshness: per water parameter, how long a value says something about the water now
    (farm/water/freshness.py): one row each, seeded, changed only (cross review F10)."""

    model = WaterFreshness
    form_class = WaterFreshnessForm
    name, plural = _('water freshness'), _('water freshness')
    url_prefix = 'water-freshness'
    actions = ('change',)
    list_template = 'farm/water_freshness_list.html'
    icon = 'timer'

    # The list in the new look (core/listprops.py), in the classic list's words (farm/water_freshness_list.html).
    search_placeholder = _('Search')
    empty_text = _('One row per water parameter is made by the platform; it is changed, never added or deleted.')

    @classmethod
    def list_rows(cls, view, objects, context):
        from core import listprops as L
        return {
            'columns': [L.column('parameter', _('Parameter')), L.column('hours', _('Fresh for (hours)'), numeric=True)],
            'rows': [L.row(row.pk, {
                'parameter': L.cell(row.get_parameter_display(), strong=True),
                'hours': L.cell(str(row.fresh_hours)),
            }, L.edit_delete(view, context, row, str(row))) for row in objects],
        }
