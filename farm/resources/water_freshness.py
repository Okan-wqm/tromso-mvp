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
