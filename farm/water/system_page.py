"""System › Water (behind ?ui=next): a recirculating system's water history, each of its active points side by side, loop
first (calculation.points_for), on the one time axis of the window. The data is the system's `history_data` (the JSON of
`farm:water_system_chart?view=history`): the same charts, worked-out values, events, Deffeyes for the range and window as
Tank › Water, drawn by the same island (`water`, frontend/islands/water.tsx) with nothing of its own in the browser.
A system has several points: the island heads each point's charts with the point's name. Without the new look the
address is the system's history on Water chemistry, today's page for it (as Tank › Water's)."""
from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from core import navigation, ui
from core.crud import render_page

from ..models import System
from ..models.site import zone_of
from ..models.water_point import site_of
from .views import RECORD, VIEW, history_data, history_url, window_props


@permission_required(VIEW, raise_exception=True)
def system_water(request, pk):
    system = get_object_or_404(System.objects.select_related('site'), pk=pk)
    if not ui.is_next(request):
        return redirect(history_url(system))
    data = history_data(request, system)
    data.update(window_props(request, data, reverse('farm:system_water', args=[system.pk]), zone_of(site_of(system))))
    data['unit'] = {'code': system.code, 'name': system.name, 'place': str(system.site) if system.site else ''}
    place = navigation.place('farm.view_system')
    return render_page(request, 'farm/system_water.html', {
        'title': f'{system.code} · {_("Water")}', 'eyebrow': f'{place.section.label} · {place.entry.label}',
        'props': data, 'can_record': request.user.has_perm(RECORD),
        'systems_url': reverse('farm:system_list')})
