"""System › Water (behind ?ui=next): a recirculating system's water history, each of its active points side by side, loop
first (calculation.points_for), on the one time axis of the window. The data is the system's `history_data` (the JSON of
`farm:water_system_chart?view=history`): the same charts, worked-out values, events, Deffeyes for the range and window as
Tank › Water, drawn by the same island (`water`, frontend/islands/water.tsx) with nothing of its own in the browser.
A system has several points, so each chart says its point in its title ("Loop · Dissolved oxygen"). Without the new look
the address is the system's history on Water chemistry, today's page for it (as Tank › Water's)."""
from datetime import datetime

from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import formats
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from core import navigation, ui
from core.crud import render_page
from core.widgets import EXAMPLE

from ..models import System
from ..models.site import zone_of
from ..models.water_point import site_of
from .views import HISTORY_RANGES, RECORD, VIEW, _history_words, history_data, history_url


def _named_by_point(places):
    """Each chart's and each worked-out value's title with its point first, when the system has more than one point."""
    if len(places) < 2:
        return places
    for place in places:
        for chart in place['charts']:
            chart['quantity'] = {**chart['quantity'], 'label': f"{place['point']} · {chart['quantity']['label']}"}
        for item in place['worked'].values():
            item['label'] = f"{place['point']} · {item['label']}"
    return places


@permission_required(VIEW, raise_exception=True)
def system_water(request, pk):
    system = get_object_or_404(System.objects.select_related('site'), pk=pk)
    if not ui.is_next(request):
        return redirect(history_url(system))
    data = history_data(request, system)
    data['places'] = _named_by_point(data['places'])
    here = reverse('farm:system_water', args=[system.pk])
    zone = zone_of(site_of(system))
    words = _history_words()
    data.update({
        'unit': {'code': system.code, 'name': system.name, 'place': str(system.site) if system.site else ''},
        'ranges': [{'key': key, 'label': key, 'href': f'{here}?{urlencode({"range": key})}',
                    'current': data['range'] == key} for key in HISTORY_RANGES],
        'custom': {'action': here, 'current': data['range'] == 'custom',
                   'start': formats.localize_input(datetime.fromtimestamp(data['start'], tz=zone).replace(tzinfo=None)),
                   'end': formats.localize_input(datetime.fromtimestamp(data['end'], tz=zone).replace(tzinfo=None)),
                   'example': formats.localize_input(EXAMPLE)},
        'words': {**words, 'zoneNote': words['zoneNote'] % {'zone': zone.key}},
        'locale': request.LANGUAGE_CODE,
    })
    place = navigation.place('farm.view_system')
    return render_page(request, 'farm/system_water.html', {
        'title': f'{system.code} · {_("Water")}', 'eyebrow': f'{place.section.label} · {place.entry.label}',
        'props': data, 'can_record': request.user.has_perm(RECORD),
        'systems_url': reverse('farm:system_list')})
