"""The Sensors tabs' lists in the new look (core/listprops.py, island `list-page`): each tab's columns and rows, worded as
its classic list template words them (templates/sensors/*_list.html, the same msgids), so core.pagesays holds the new page
to the old one. Each function is the `list_rows` (or `list_filters`) of its tab in sensors/resources.py; the rows are the
ones the tab's list view read (search, filters and page applied there). A row's title opens the record's own page (the
record form), never the classic dialog; its actions are the classic row's (sensors/_row_actions.html)."""
from datetime import timedelta

from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from core import listprops as L
from core.templatetags.dates import company_clock, site_clock, zone_for

from .templatetags.sensors import measured

DASH = '—'


def moment(value, where=None):
    """A moment as the lists show it: dd.mm.yyyy HH:MM on the clock of `where` (a site or a zone), else the company's."""
    shown = site_clock(value, where) if where is not None else company_clock(value)
    return formats.date_format(shown, 'DATETIME_FORMAT')


def active(is_active, yes=None, no=None):
    """A record's Active / Inactive (or its own pair of words) as its chip."""
    return L.chip('ok', yes or _('Active')) if is_active else L.chip('neutral', no or _('Inactive'))


def connections(view, objects, context):
    return {'columns': [L.column('connection', _('Connection')), L.column('broker', _('Broker')),
                        L.column('client', _('Client id')), L.column('devices', _('Devices'), numeric=True),
                        L.column('state', _('State'))],
            'rows': [L.row(row.pk, {
                'connection': L.title(view, context, row, row.name),
                'broker': L.cell(f'{row.host}:{row.port}' + (' · TLS' if row.use_tls else '')),
                'client': L.cell(row.client_id),
                'devices': L.cell(row.device_count),
                'state': L.cell(chip=active(row.is_active)),
            }, L.edit_delete(view, context, row, row.name)) for row in objects]}


def payload_formats(view, objects, context):
    def time(row):
        # the design's: the path, its unit under it (the classic page says them on one line, "/ts · Milliseconds …")
        return L.cell(row.time_path, sub=[row.get_time_unit_display()]) if row.time_path else L.cell(_('When received'))
    return {'columns': [L.column('format', _('Payload format')), L.column('shape', _('Shape')),
                        L.column('time', _('Time')), L.column('devices', _('Devices'), numeric=True)],
            'rows': [L.row(row.pk, {
                'format': L.title(view, context, row, row.name),
                'shape': L.cell(row.get_shape_display()),
                'time': time(row),
                'devices': L.cell(row.device_count),
            }, L.edit_delete(view, context, row, row.name)) for row in objects]}


def devices(view, objects, context):
    """The devices with where each is placed now and, for one whose clock is off past the alarm rules' warning limit, the
    note saying how far (the classic list's `placed_and_clock`); a simulated device is marked so (the design's mark: its
    values are stored marked simulated and used nowhere)."""
    from .templatetags.sensors_places import placed_and_clock

    can_move = view.request.user.has_perm('sensors.add_binding')
    rows = []
    for device, places, clock in placed_and_clock(objects):
        title = L.title(view, context, device, device.name, sub=[
            device.code + (f' · {device.manufacturer} {device.model}' if device.manufacturer else '')])
        if device.is_simulated:
            title['chips'] = [L.chip('hold', _('Simulated'))]
        moves = [L.link(f"{reverse('sensors:device_move')}?device={device.pk}", _('Move device'), 'target')] \
            if can_move else []
        rows.append(L.row(device.pk, {
            'device': title,
            'topic': L.cell(device.topic),
            'connection': L.cell(device.connection.name),
            'site': L.cell(device.site.name),
            'placed': L.cell(' · '.join(str(place) for place in places)) if places
            else L.cell(chip=L.chip('neutral', _('Not placed'))),
            'channels': L.cell(device.channel_count, href=f"{reverse('sensors:channel_list')}?device={device.pk}"),
            'state': L.cell(chip=active(device.is_active), chips=[L.chip('warning', clock)] if clock else ()),
        }, moves + L.edit_delete(view, context, device, device.name)))
    return {'columns': [L.column('device', _('Device')), L.column('topic', _('Topic')),
                        L.column('connection', _('Connection')), L.column('site', _('Site')),
                        L.column('placed', _('Placed at')), L.column('channels', _('Channels'), numeric=True),
                        L.column('state', _('State'))],
            'rows': rows}


def device_filters(view, context):
    return [L.choice('placed', _('Placed'), context['placed'],
                     [('', _('Placed or not')), ('yes', _('Placed now')), ('no', _('Not placed'))])]


def channels(view, objects, context):
    def quantity(row):
        sub = []
        if row.ph_scale_said:
            said = f"{_('pH scale')}: {row.ph_scale_said}"
            if row.ph_scale_from:
                said += ' · ' + _('changed %(moment)s') % {'moment': moment(row.ph_scale_from, row.device.site)}
            sub.append(said)
        return L.cell(row.get_quantity_display(), sub=sub)

    def storing(row):
        kept = _('Every value') if row.reduction == 'all' else \
            _('Moves of %(deadband)s') % {'deadband': floatformat(row.deadband, '-4')}
        return f"{kept} · {_('at least every %(seconds)s s') % {'seconds': row.heartbeat_s}}"
    return {'columns': [L.column('channel', _('Channel')), L.column('device', _('Device')),
                        L.column('quantity', _('Quantity')), L.column('storing', _('Storing')),
                        L.column('state', _('State'))],
            'rows': [L.row(row.pk, {
                'channel': L.title(view, context, row, row.code, sub=[f'{row.name} · #{row.channel_no}']),
                'device': L.cell(row.device.code),
                'quantity': quantity(row),
                'storing': L.cell(storing(row)),
                'state': L.cell(row.get_state_display()),
            }, L.edit_delete(view, context, row, row.code)) for row in objects]}


def channel_filters(view, context):
    return [L.choice('device', _('Device'), context['device'],
                     [('', _('All devices')), *((str(item.pk), str(item)) for item in context['devices'])])]


def credentials(view, objects, context):
    return {'columns': [L.column('user', _('User name')), L.column('made', _('Secret made at')),
                        L.column('devices', _('Devices'), numeric=True), L.column('state', _('State'))],
            'rows': [L.row(row.pk, {
                'user': L.title(view, context, row, row.username),
                'made': L.cell(moment(row.rotated_at) if row.rotated_at else DASH),
                'devices': L.cell(row.device_count),
                'state': L.cell(chip=active(row.is_enabled, _('Enabled'), _('Disabled'))),
            }, L.edit_delete(view, context, row, row.username)) for row in objects]}


def bindings(view, objects, context):
    """Where each channel's values belong and since when, newest first; a channel's own history is its code's link. With
    `?place=` the sensors at that place: said in a notice, and the tabs lead back to every binding."""
    listed = reverse('sensors:binding_list')
    table = {'columns': [L.column('channel', _('Channel')), L.column('target', _('Bound to')),
                         L.column('role', _('Role')), L.column('from', _('From')), L.column('until', _('Until'))],
             'rows': [L.row(row.pk, {
                 'channel': L.cell(row.channel.code, href=f'{listed}?channel={row.channel_id}', strong=True,
                                   sub=[f'{row.channel.device.code} · #{row.channel.channel_no}']),
                 'target': L.cell(row.target, sub=[row.note]),
                 'role': L.cell(row.get_role_display()),
                 'from': L.cell(moment(row.valid_from, row.clock)),
                 'until': L.cell(moment(row.valid_to, row.clock)) if row.valid_to
                 else L.cell(chip=L.chip('accent', _('now'))),
             }, L.edit_delete(view, context, row, row.channel.code)) for row in objects]}
    if context.get('channel'):
        table['timeline'] = binding_timeline(objects, timezone.now())
    place = context.get('place')
    if place is not None:
        table['tabs'] = L.tabs(_('Bindings'), [(listed, _('Show every binding'), None, False),
                                               (view.request.get_full_path(), str(place), None, True)])
        table['notices'] = [L.notice('place', 'neutral', _(
            'The sensors at %(place)s: those there now first, then those there before.') % {'place': place})]
    return table


def binding_filters(view, context):
    """Bindings' selects in the new look (BindingResource.filter_list reads them): the channel's device's site, the role,
    and those bound now or every one."""
    return [L.choice('site', _('Site'), context.get('chosen_site', ''),
                     [('', _('All sites')), *((site.pk, site.name) for site in context.get('sites', ()))]),
            L.choice('bound', _('Bound'), context.get('chosen_bound', ''),
                     [('', _('Now and before')), ('now', _('Now bound'))]),
            L.choice('role', _('Role'), context.get('chosen_role', ''), [('', _('All roles')), *context.get('roles', ())])]


def binding_timeline(rows, now):
    """One channel's bindings (the list's own rows under `?channel=`) as lanes (frontend/islands/ui/Timeline.tsx): a
    lane per place in the order the channel first went there, each binding a span from its start to its end (to now
    while it holds), placed in % of the window from its first start to now, worded as the table's From and Until on the
    place's clock; about five day ticks and "now" at the end. None without rows."""
    rows = sorted(rows, key=lambda row: row.valid_from)
    if not rows:
        return None
    start = rows[0].valid_from
    end = max([now, *(row.valid_to for row in rows if row.valid_to)])
    seconds = max((end - start).total_seconds(), 3600)

    def at(when):
        return round(min(max((when - start).total_seconds() / seconds * 100, 0), 100), 2)

    lanes = {}
    for row in rows:
        label = f'{row.get_role_display()} · {moment(row.valid_from, row.clock)} – ' + (
            moment(row.valid_to, row.clock) if row.valid_to else _('now'))
        lane = lanes.setdefault(f'{row.target_kind}:{row.target.pk}', {
            'key': f'{row.target_kind}:{row.target.pk}', 'label': str(row.target), 'spans': []})
        lane['spans'].append({'key': str(row.pk), 'x': at(row.valid_from),
                              'width': round(at(row.valid_to or end) - at(row.valid_from), 2), 'tone': row.role,
                              'open': row.valid_to is None, 'label': label})
    zone = zone_for(rows[0].clock)
    local_start, local_end = timezone.localtime(start, zone), timezone.localtime(end, zone)
    step = timedelta(days=max(1, round(seconds / 86400 / 5)))
    ticks = [{'x': 0, 'label': formats.date_format(local_start, 'd.m')}]
    # midnights on the place's clock, aware, so they are placed on the same axis as the bindings' moments
    day = local_start.replace(hour=0, minute=0, second=0, microsecond=0) + step
    while day < local_end:
        x = at(day)
        if 8 <= x <= 90:
            ticks.append({'x': x, 'label': formats.date_format(day, 'd.m')})
        day += step
    ticks.append({'x': 100, 'label': _('now')})
    channel = rows[0].channel
    return {'title': f'{channel.code} #{channel.channel_no} · {channel.device.code} · {_("History")}',
            'label': _('Where %(channel)s was bound over time') % {'channel': channel.code},
            'ticks': ticks, 'lanes': list(lanes.values())}


def alarm_rules(view, objects, context):
    return {'columns': [L.column('rule', _('Rule')), L.column('threshold', _('Threshold'), numeric=True),
                        L.column('for', _('For (seconds)'), numeric=True), L.column('severity', _('Severity')),
                        L.column('state', _('State'))],
            'notices': [L.notice('sent', 'neutral', _('Each time a rule holds it is an alarm of Company › Alarms: its '
                                                      'recipient rules say who is notified.'))],
            'rows': [L.row(row.pk, {
                'rule': L.title(view, context, row, str(row)),
                'threshold': L.cell(measured(row.threshold, row.quantity_code)),
                'for': L.cell(row.for_s),
                'severity': L.cell(chip=L.chip('critical' if row.severity == 'critical' else 'warning',
                                               row.get_severity_display())),
                'state': L.cell(chip=active(row.is_active)),
            }, L.edit_delete(view, context, row, str(row))) for row in objects]}
