"""The Sensors pages beyond its tabs in the new look (behind `?ui=next`, core.ui.is_next): Overview (island `sensors-home`)
and the three operational lists, Live values, Dead letters and Alarm events, drawn by the shared list page (island
`list-page`, frontend/islands/ui/ListPage.tsx) from props made here with core/listprops.py's words. Each is read by its
view in sensors/views.py exactly as for the classic page (the same rows, the same page of them, the same filters) and
worded with the classic template's msgids (templates/sensors/home.html, live.html, dead_letters.html,
alarm_events.html), so core.pagesays holds each new page to its old one. A stale value is never drawn as fresh: the
state is the classic page's (read.latest's `fresh`), its chip the stale one."""
from django.middleware.csrf import get_token
from django.template.defaultfilters import truncatechars
from django.urls import reverse
from django.utils.translation import gettext as _

from core import listprops as L
from core.dates import company_zone
from core.formprops import when
from farm.templatetags.water import age, short_age

from .lists import DASH, moment
from .templatetags.sensors import measured


def page_props(request, *, label, columns, rows, filters=(), notices=(), empty, page=None, pager_query=''):
    """The list-page island's props of a page that is not a tab (core/listprops.py `list_props` is a tab's): its filters
    (a GET form, `filters` as listprops.choice), notices, table, the sentence said when there is no row, and the pager."""
    shown = {each['name'] for each in filters} | {'page', 'ui'}
    return {
        'csrfToken': get_token(request),
        'tabs': None,
        'toolbar': {'label': label, 'search': None,
                    'keep': [{'name': key, 'value': value} for key, value in request.GET.items() if key not in shown],
                    'filters': list(filters), 'submit': _('Filter'), 'add': None},
        'notices': list(notices),
        'lines': [],
        'table': {'label': label, 'columns': columns, 'rows': rows, 'actionsLabel': _('Actions')},
        'empty': {'title': empty, 'text': None, 'link': None, 'add': None},
        'pager': L.pager(page, pager_query),     # the tabs' pager (core/listprops.py), the one wording of it
    }


def live_props(request, rows):
    """Live values: each channel's last good value, how old it is, whether it is fresh, and where it is bound now."""
    def state(row):
        if row['channel'].state == 'maintenance':
            return L.cell(chip=L.chip('neutral', _('Maintenance')))
        if row['state'].value is None:
            return L.cell(_('No value yet'))
        return L.cell(chip=L.chip('ok', _('Fresh')) if row['state'].fresh else L.chip('stale', _('Stale')))

    def bound(row):
        binding = row['binding']
        if binding is None:
            return L.cell(_('Not bound'))
        return L.cell(str(binding.target) + (f" · {_('backup')}" if binding.role == 'backup' else ''))

    def quantity(channel):
        scale = channel.ph_scale_said
        return L.cell(channel.get_quantity_display(), sub=[
            _('As measured, on its pH scale: %(scale)s') % {'scale': scale} if scale else ''])

    def measured_at(row):
        at, channel = row['state'].at, row['channel']
        if not at:
            return L.cell(DASH)
        return L.cell(moment(at, channel.device.site), sub=[_('%(age)s ago') % {'age': age(at)}])

    columns = [L.column('channel', _('Channel')), L.column('quantity', _('Quantity')),
               L.column('value', _('Value'), numeric=True), L.column('measured', _('Measured')),
               L.column('state', _('State')), L.column('bound', _('Bound to'))]
    table = [L.row(row['channel'].pk, {
        'channel': L.cell(row['channel'].code, strong=True,
                          sub=[f"{row['channel'].device.code} · #{row['channel'].channel_no}"],
                          chips=[L.chip('hold', _('Simulated'))] if row['channel'].device.is_simulated else ()),
        'quantity': quantity(row['channel']),
        'value': L.cell(measured(row['state'].value, row['channel'].quantity)),
        'measured': measured_at(row),
        'state': state(row),
        'bound': bound(row),
    }, status='warning' if row['state'].value is not None and not row['state'].fresh
        and row['channel'].state != 'maintenance' else None) for row in rows]
    return page_props(request, label=_('Live values'), columns=columns, rows=table, notices=[L.notice(
        'fresh', 'neutral', _('A value is fresh while both its own time on the device and its arrival here are no older '
                              'than its channel’s own number of heartbeats (3 unless the channel is set otherwise). A '
                              'stale value is not used for a unit’s water: the next source counts (its system’s sensor, '
                              'then the latest sample).'))], empty=_('No channel is listened to yet.'))


def dead_letters_props(request, rows, *, page, reasons, reason, show, pager_query, can_resolve):
    """Dead letters: what the ingest could not store, the payload as text (cut, then whole) and as hex, its size; the
    payload is whatever a device sent, drawn as text only (React escapes it, as the classic template does)."""
    def payload(row):
        return L.cell(truncatechars(row['text'], 60), sub=[row['text'], row['hex'], _('%(size)s bytes') % {
            'size': row['letter'].payload_len}])

    def actions(letter):
        if letter.resolved_at or not can_resolve:
            return []
        return [L.post(reverse('sensors:dead_letter_resolve', args=[letter.pk]), _('Resolve'), 'check-circle')]

    columns = [L.column('topic', _('Topic')), L.column('reason', _('Reason')), L.column('times', _('Times'), numeric=True),
               L.column('last', _('Last')), L.column('payload', _('Payload'))]
    table = [L.row(row['letter'].pk, {
        'topic': L.cell(row['letter'].topic, strong=True, sub=[row['connection']],
                        chips=[L.chip('neutral', _('Resolved'))] if row['letter'].resolved_at else ()),
        'reason': L.cell(row['letter'].get_reason_display()),
        'times': L.cell(row['letter'].count),
        'last': L.cell(moment(row['letter'].last_at)),
        'payload': payload(row),
    }, actions(row['letter'])) for row in rows]
    filters = [L.choice('reason', _('Reason'), reason, [('', _('Every reason')), *reasons]),
               L.choice('show', _('Show'), show, [('', _('Open ones')), ('all', _('Resolved ones too'))])]
    notice = L.notice('kept', 'neutral', _(
        'A message the ingest could not store is kept here with how often it came. Beyond 1000 new ones per connection '
        'and hour the rest are counted on one row. Readings are never refused for the dead letters’ sake. Kept 90 days.'))
    return page_props(request, label=_('Dead letters'), columns=columns, rows=table, filters=filters, notices=[notice],
                      empty=_('No dead letters.'), page=page, pager_query=pager_query)


def alarm_events_props(request, events, *, page, connected, can_acknowledge):
    """Alarm events: the times a rule held, open ones first, each with who acknowledged it; Acknowledge is the row's
    action (a POST with the page's token) for a person who may, on an event nobody acknowledged yet. "Nothing is sent
    yet" (alarms/_not_sent.html) while no push transport is connected."""
    def clock(event):
        return event.binding.clock if event.binding else None

    def acknowledged(event):
        alarm = getattr(event, 'alarm', None)
        ack = alarm.acknowledgements.all()[0] if alarm is not None and alarm.acknowledgements.all() else None
        if ack is None:
            return L.cell(DASH)
        return L.cell(f'{ack.user or DASH} · {moment(ack.acknowledged_at, clock(event))}')

    def actions(event):
        alarm = getattr(event, 'alarm', None)
        if not can_acknowledge or (alarm is not None and alarm.acknowledgements.all()):
            return []
        return [L.post(reverse('sensors:alarm_event_acknowledge', args=[event.pk]), _('Acknowledge'), 'check-circle')]

    columns = [L.column('rule', _('Rule')), L.column('channel', _('Channel')), L.column('place', _('Place')),
               L.column('severity', _('Severity')), L.column('opened', _('Opened')), L.column('closed', _('Closed')),
               L.column('peak', _('Furthest value'), numeric=True), L.column('acknowledged', _('Acknowledged'))]
    table = [L.row(event.pk, {
        'rule': L.cell(str(event.rule), strong=True),
        'channel': L.cell(f'#{event.channel_no}'),
        'place': L.cell(str(event.binding.target) if event.binding else DASH),
        'severity': L.cell(chip=L.chip('critical' if event.rule.severity == 'critical' else 'warning',
                                       event.rule.get_severity_display())),
        'opened': L.cell(moment(event.opened_at, clock(event))),
        'closed': L.cell(moment(event.closed_at, clock(event))) if event.closed_at
        else L.cell(chip=L.chip('accent', _('Open'))),
        'peak': L.cell(measured(event.peak, event.rule.quantity_code)),
        'acknowledged': acknowledged(event),
    }, actions(event), status=None if event.closed_at else (
        'critical' if event.rule.severity == 'critical' else 'warning')) for event in events]
    notices = [] if connected.get('push') else [L.notice('not-sent', 'warning', _(
        'Nothing is sent yet: the push transport is not connected (the mobile app comes later). Every notification waits '
        'in the outbox below, with its recipient and level, and is sent once it is.'))]
    return page_props(request, label=_('Alarm events'), columns=columns, rows=table, notices=notices,
                      empty=_('No alarm events.'), page=page)


# The design's order of the state tiles (the ingest, then what needs a look, then what the ingest could not keep).
STATE_ORDER = ('ingest', 'online', 'stale', 'alarms', 'dead', 'qos0', 'refused', 'unplaced')


def _state_tile(each, now):
    """One state tile in the design's words: its figure, a sub-line from the same read (the ingest's last heartbeat, how
    many devices are offline) and its status: critical for an ingest that is down or never heard, or an open alarm;
    warning for an offline device, a channel without a fresh value, a dead letter, a message lost. Never OK by default:
    a tile without a status is plain grey, as the classic page's."""
    key, count = each['key'], each['count']
    sub = status = None
    if key == 'ingest':
        status = None if each['text'] == _('Alive') else 'critical'
        if each.get('heartbeat'):
            sub = _('Heartbeat %(age)s ago') % {'age': short_age(each['heartbeat'], now)}
    elif key == 'online':
        status = 'warning' if each['offline'] else None
        sub = _('%(count)s offline') % {'count': each['offline']} if each['offline'] else None
    elif key == 'alarms':
        status = 'critical' if count else None
    elif key in ('stale', 'dead', 'qos0', 'refused', 'unplaced'):
        status = 'warning' if count and key != 'unplaced' else None
    return {'key': key, 'label': str(each['label']), 'figure': str(count), 'href': each['url'], 'sub': sub,
            'status': status, 'statusLabel': {'critical': _('Critical'), 'warning': _('Warning')}.get(status)}


def home_props(setup_tiles, state_tiles, now):
    """Overview: the ingest's state and the configuration counted (sensors.views.state_tiles and the setup counts, as the
    classic page reads them), in the design's order and words, worked out at `now` on the company's clock."""
    ordered = sorted(state_tiles, key=lambda each: STATE_ORDER.index(each['key']))
    return {
        'state': {'title': _('Ingest and devices'), 'tiles': [_state_tile(each, now) for each in ordered],
                  'meta': _('Worked out %(when)s · %(zone)s') % {'when': when(now), 'zone': company_zone().key}}
        if state_tiles else None,
        'setup': {'title': _('Setup'), 'tiles': [
            {'key': each['url'], 'label': str(each['label']), 'figure': str(each['count']), 'href': each['url'], 'sub': None,
             'status': None, 'statusLabel': None} for each in setup_tiles]} if setup_tiles else None,
        'empty': None if setup_tiles or state_tiles else _(
            'Nothing of the sensors is open to you yet: ask for a right on the Roles page.'),
    }
