"""The props of the new look's Company › Overview island (frontend/islands/company.tsx), from config.company.overview.

Every word and figure is finished here, in the request's language; the island only draws them. What the old page and the
area pages already say keeps their own msgids (the upcoming reports, the board's tiles, the activity log's sentences), so
a page says the same thing in both looks (core.pagesays holds the new page to the old one)."""
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.translation import gettext as _, ngettext

from core.dates import company_zone
from core.formprops import by, when
from farm.templatetags.stock import fish as whole, kilos, tonnes

from .company import overview


def count_of(said, number):
    """An ngettext sentence (called with its literals, so makemessages finds them) with its number put in."""
    return said % {'count': number}


def upcoming_props(upcoming):
    """reports/_upcoming.html in words."""
    from reports.kinds import ReportKind
    if upcoming is None:
        return None
    items = []
    for line in upcoming['duties']:
        overdue = line.status == 'overdue'
        items.append({'key': f'duty-{line.duty.pk}-{line.site.pk}-{line.year}', 'status': 'critical' if overdue else None,
                      'text': f'{line.duty.title} · {line.site.name} · {line.year}',
                      'sub': [formats.date_format(line.deadline, 'DATE_FORMAT'), *([_('Overdue')] if overdue else [])],
                      'link': {'href': upcoming['duties_url'], 'label': _('Outside this system')}})
    for index, row in enumerate(upcoming['rows']):
        parts = [str(ReportKind(row.kind).label), str(row.place), *([str(row.period.label())] if row.period else [])]
        sub = ([formats.date_format(row.deadline, 'DATE_FORMAT'), *([_('Overdue')] if row.overdue else [])]
               if row.deadline else [_('at once')])
        items.append({'key': f'row-{index}', 'status': 'critical' if row.overdue else None, 'text': ' · '.join(parts),
                      'sub': sub, 'link': None})
    if upcoming['rows']:
        label = (_('and %(count)s more: all reports') % {'count': upcoming['more']}) if upcoming['more'] else _('All reports')
        empty = None
    else:
        label = _('All reports')
        empty = None if upcoming['not_set_up'] else _('No report is due.')
    sites = len(upcoming['not_set_up'])
    return {
        'title': _('Upcoming reports'), 'items': items, 'empty': empty,
        'badge': count_of(ngettext('%(count)s overdue', '%(count)s overdue', upcoming['overdue']), upcoming['overdue']) if upcoming['overdue'] else None,
        'link': {'href': upcoming['url'], 'label': label},
        'notSetUp': count_of(ngettext(
            '%(count)s site with fish is not set up for reports: what it owes is not known, so nothing is listed as due '
            'for it.',
            '%(count)s sites with fish are not set up for reports: what they owe is not known, so nothing is listed as '
            'due for them.', sites), sites) if sites else None,
    }


def _water_chip(water, now):
    """A site's water in a chip, as the design words it: its worst value as the Water page judges it ("CO₂ (mg/L) 15.6"),
    with "No recent data" when that value is old, a critical one first; then a unit with fish whose oxygen has no fresh
    value ("O₂ (mg/L): no recent data", critical: owner decision of 2026-11-23, PointWater.silent_oxygen, for every
    viewer); then a warning value; else "No recent data · <age>" for a point whose values grew old; else "Not measured"
    or OK. The count of critical and warning points stays the tiles' and the Water page's."""
    from django.utils.timesince import timesince

    from farm.water.messages import no_fresh_oxygen_short
    from farm.water.read import said_value
    if water is None:
        return None
    worst = water['worst']
    if worst is not None and (worst[1] == 'critical' or not water.get('silent')):
        reading, judged, old = worst
        text = f'{reading.parameter.short} {said_value(reading)}'
        return {'kind': 'critical' if judged == 'critical' else 'warning',
                'text': f"{text} · {_('No recent data')}" if old else text}
    if water.get('silent'):
        return {'kind': 'critical', 'text': str(no_fresh_oxygen_short())}
    if water['stale_since'] is not None:
        return {'kind': 'stale', 'text': f"{_('No recent data')} · {timesince(water['stale_since'], now, depth=1)}"}
    if not water['measured']:
        return {'kind': 'nodata', 'text': _('Not measured')}
    return {'kind': 'ok', 'text': _('OK')}


def _tiles(found, now):
    tiles = []
    sites, alarms, people, reports, messages = (found[key] for key in ('sites', 'alarms', 'people', 'reports', 'messages'))
    if sites is not None:
        tiles.append({'key': 'sites', 'label': _('Sites'), 'figure': whole(sites['count']), 'href': reverse('farm:site_list'),
                      'sub': ' · '.join(f'{count} {str(label).lower()}' for label, count in sites['by_status']) or None})
        stocked = [row for row in sites['rows'] if row['biomass_kg'] is not None]
        if stocked:
            units = sum(row['units_stocked'] for row in stocked)
            tiles.append({'key': 'biomass', 'label': _('Biomass'),
                          'figure': tonnes(sum(row['biomass_kg'] for row in stocked)),
                          'sub': count_of(ngettext('%(count)s unit stocked', '%(count)s units stocked', units), units),
                          'source': _('Stock ledger · %(time)s') % {
                              'time': formats.time_format(timezone.localtime(now, company_zone()), 'TIME_FORMAT')},
                          'href': reverse('farm:production_units')})
    if alarms is not None:
        # alarms.read.attention, the one reader: the figure counts open alarms; its second line counts units (their water
        # as the alarm engine judges it now), and says so, never mixed with the Water chips' sampling points
        found = alarms['attention']
        tiles.append({'key': 'alarms', 'label': _('Open alarms'), 'figure': whole(found.alarms),
                      'href': reverse('alarms:alarm_list'), 'status': found.status or None,
                      'statusLabel': {'critical': _('Critical'), 'warning': _('Warning')}.get(found.status),
                      'sub': ' · '.join(_alarm_counts(found)) or None,
                      'sub2': ' · '.join(units_said(found)) or None})
    if people is not None:
        tiles.append({'key': 'on_site', 'label': _('On site now'), 'figure': whole(people['on_site']),
                      'href': reverse('hr:today'), 'sub': _('Everyone clocked in, all teams'),
                      'sub2': ' · '.join(f'{name} {count}' for name, count in people['on_site_by_site'].items()) or None})
    if reports is not None:
        late = len(reports['late']) + len(reports['late_duties'])
        tiles.append({'key': 'reports', 'label': _('Reports due'), 'figure': whole(reports['count']),
                      'href': reports['url'], 'status': 'warning' if late else None,
                      'statusLabel': _('Warning') if late else None,
                      'sub': count_of(ngettext('%(count)s overdue', '%(count)s overdue', late), late) if late else None})
    if messages is not None:
        tiles.append({'key': 'messages', 'label': _('Unread messages'), 'figure': whole(messages['unread']),
                      'href': reverse('messaging:inbox'),
                      'sub': count_of(ngettext('in %(count)s conversation', 'in %(count)s conversations', messages['conversations']), messages['conversations'])
                      if messages['unread'] else None})
    # Each figure says where it comes from and when it was read (the design's tile foot): the page it is read from, by the
    # menu's own name, and the moment, on the company's clock. The stock tile already names the ledger.
    time = formats.time_format(timezone.localtime(now, company_zone()), 'TIME_FORMAT')
    sources = {'sites': str(_('Sites')), 'alarms': f"{_('Alarms')} · {time}", 'on_site': f"{_('Today & attendance')} · {time}",
               'reports': f"{_('Regulatory reports')} · {time}", 'messages': f"{_('Messages')} · {time}"}
    for tile in tiles:
        tile.setdefault('source', sources.get(tile['key']))
    return tiles


def _alarm_counts(found):
    """The open alarms by severity: "1 critical · 2 warnings"."""
    warnings = found.alarms - found.alarms_critical
    return [*([count_of(ngettext('%(count)s critical', '%(count)s critical', found.alarms_critical), found.alarms_critical)]
              if found.alarms_critical else []),
            *([count_of(ngettext('%(count)s warning', '%(count)s warnings', warnings), warnings)] if warnings else [])]


def units_said(found):
    """The units' line of an Attention: the one wording (core.ui.attention_said) without the alarms, whose count is the
    figure it stands under."""
    from core.ui import attention_said
    return attention_said(found, alarms=False)


def farm_wide_said(found):
    """A site's open alarms hold the farm-wide ones (they are about every site): how many of its figure they are."""
    return [ngettext('%(count)s of them for the whole farm', '%(count)s of them for the whole farm', found.farm_wide)
            % {'count': found.farm_wide}] if found.farm_wide else []


def _site_water(row, now):
    """A site's water in one judgement: the points' chip (_water_chip) unless it would say OK while the site's stocked units
    are flagged on the cards' ladder (alarms.read.attention: critical, cannot be read, warning, no recent data, no limit);
    then the units' line in the worst status, so the row never says "OK" beside a critical unit."""
    chip, found = _water_chip(row['water'], now), row['attention']
    flagged = units_said(found) if found is not None else []
    if flagged and (chip is None or chip['kind'] == 'ok'):
        return {'kind': 'critical' if found.critical or found.unreadable else 'warning', 'text': ' · '.join(flagged)}
    return chip


def _sites(user, sites, now):
    return {
        'title': _('Sites'), 'link': {'href': reverse('farm:site_list'), 'label': _('Sites')},
        'columns': {'site': _('Site'), 'type': _('Type'), 'units': _('Units stocked'), 'biomass': _('Biomass'),
                    'water': _('Water'), 'alarms': _('Open alarms'), 'onSite': _('On site now')},
        'rows': [{
            'key': str(row['site'].pk), 'name': row['site'].name, 'code': row['site'].code,
            'href': reverse('farm:site_edit', args=[row['site'].pk]) if user.has_perm('farm.change_site') else None,
            'type': str(row['site'].get_type_display()),
            'status': 'critical' if (row['water'] or {}).get('critical') or getattr(row['attention'], 'status', '') == 'critical'
                      else 'warning' if (row['water'] or {}).get('warning') or getattr(row['attention'], 'status', '')
                      else None,
            'units': None if row['units_stocked'] is None else whole(row['units_stocked']),
            'biomass': None if row['biomass_kg'] is None else tonnes(row['biomass_kg']),
            'water': _site_water(row, now),
            'alarms': None if row['attention'] is None else {
                'figure': whole(row['attention'].alarms),
                # why the row's edge is critical or warning: the farm-wide alarms it holds and its units' line
                'sub': ' · '.join([*farm_wide_said(row['attention']), *units_said(row['attention'])]) or None},
            'onSite': None if row['on_site'] is None else whole(row['on_site']),
        } for row in sites['rows']],
        'none': '—',
        'empty': _('No sites yet') if not sites['rows'] else None}


def _alarms(alarms):
    return {
        'title': _('Open alarms'), 'link': {'href': reverse('alarms:alarm_list'), 'label': _('Alarms')},
        # the classic page's test (alarms/_not_sent.html: connected.push), in words for a page with no outbox under it
        'safety': None if alarms['connected'].get('push') else _(
            'Nothing is sent yet: the push transport is not connected (the mobile app comes later). Every notification '
            'waits in the outbox on the Alarms page, with its recipient and level, and is sent once it is.'),
        'columns': {'severity': _('Severity'), 'what': _('What')},
        'rows': [{'key': str(alarm.pk), 'severity': str(alarm.get_severity_display()),
                  'kind': 'critical' if alarm.severity == 'critical' else 'warning', 'what': alarm.summary,
                  'href': reverse('alarms:alarm_detail', args=[alarm.pk]),
                  'where': ' · '.join(filter(None, [str(alarm.point) if alarm.point_id else '',
                                                    alarm.site.name if alarm.site_id else '', when(alarm.opened_at)]))}
                 for alarm in alarms['rows']],
        'more': (_('and %(count)s more: all alarms') % {'count': alarms['more']}) if alarms['more'] else None,
        # "No alarm is open." only when nothing needs a look (Attention.quiet, the strip's rule); with no alarm row but a
        # unit flagged, the plate says the units' line instead of an empty state
        # (and only when it lists no alarm either: the reading may be a few seconds old, the list is live)
        'empty': _('No alarm is open.') if alarms['attention'].quiet and not alarms['rows'] else None,
        'units': {'tone': 'critical' if alarms['attention'].critical or alarms['attention'].unreadable else 'warning',
                  'text': ' · '.join(units_said(alarms['attention']))} if units_said(alarms['attention']) else None}


def _people(people):
    board = people['board']
    words = {'upcoming': _('Upcoming'), 'here': _('Here now'), 'not_in': _('Not in yet'), 'absent': _('Absent'),
             'on_leave': _('On leave'), 'forgotten': _('Clock-out forgotten'), 'done': _('Done')}
    tiles = [{'key': 'planned', 'label': _('Planned today'), 'figure': whole(board.planned)}]
    for tile in board.tiles:
        if tile.key == 'forgotten' and not tile.count:
            continue
        warn = tile.key in ('absent', 'forgotten') and tile.count
        tiles.append({'key': tile.key, 'label': words.get(tile.key, words['done']), 'figure': whole(tile.count),
                      'status': 'warning' if warn else None, 'statusLabel': _('Warning') if warn else None,
                      'sub': ngettext('%(late)s late', '%(late)s late', board.late) % {'late': board.late}
                      if tile.key == 'here' and board.late else None})
    if people['to_decide'] is not None:
        tiles.append({'key': 'to_decide', 'label': _('Leave to decide'), 'figure': whole(people['to_decide']),
                      'href': reverse('hr:leaverequest_list')})
    return {'title': _('Office people today'), 'link': {'href': reverse('hr:today'), 'label': _('Today & attendance')},
            'tiles': tiles}


def _feed(feed):
    rows = []
    for row in feed['rows']:
        short = next(((location, level) for location, item, _quantity, level in feed['low']
                      if location.site_id == row.site.pk and item.pk == row.item.pk), None)
        rows.append({'key': f'{row.site.pk}-{row.item.pk}', 'item': str(row.item), 'site': row.site.name,
                     'onHand': kilos(row.on_hand),
                     'cover': formats.number_format(row.cover_days, 1, use_l10n=True) if row.cover_days is not None else None,
                     'status': 'warning' if short else None,
                     'note': _('%(location)s, below the reorder level of %(level)s') % {
                         'location': short[0].code, 'level': kilos(short[1])} if short else None})
    return {'title': _('Feed on hand'), 'link': {'href': reverse('inventory:storage'), 'label': _('Storage')},
            'columns': {'item': _('Site · item'), 'onHand': _('On hand'), 'cover': _('Days of cover')},
            'rows': rows, 'none': '—', 'empty': _('Nothing on hand') if not rows else None}


def _messages(messages):
    def last_text(row):
        if row.last is None:
            return ''
        return _('Message deleted') if row.last.is_deleted else row.last.body
    return {'title': _('Unread messages'), 'link': {'href': reverse('messaging:inbox'), 'label': _('Messages')},
            'rows': [{'key': str(row.conversation.pk), 'title': str(row.title),
                      'href': reverse('messaging:conversation', args=[row.conversation.pk]),
                      'text': last_text(row), 'when': when(row.last.created_at) if row.last is not None else ''}
                     for row in messages['rows']],
            'empty': _('No unread messages') if not messages['rows'] else None}


def _activity(entries):
    return {'title': _('Recent activity'), 'link': {'href': reverse('core:activity_log'), 'label': _('Activity log')},
            'critical': _('Critical'),
            'entries': [{'key': str(entry.pk), 'action': str(entry.get_action_display()),
                         'critical': entry.severity == 'critical',
                         'record': f'{str(entry.shown_type())[:1].upper()}{str(entry.shown_type())[1:]} · {entry.entity_label}',
                         'by': by(entry.user_name), 'when': when(entry.created_at)}
                        for entry in entries],
            'empty': _('Nothing recorded yet.') if not entries else None}


def _knowledge(entries):
    return {'title': _('Latest knowledge entries'),
            'link': {'href': reverse('knowledge:knowledgeentry_list'), 'label': _('Knowledge entries')},
            'rows': [{'key': str(entry.pk), 'text': entry.statement, 'source': entry.source_label(),
                      'href': reverse('knowledge:knowledgeentry_detail', args=[entry.pk]),
                      'kind': 'ok' if entry.reviewed_by_id else 'neutral',
                      'chip': str(entry.get_status_display())} for entry in entries],
            'empty': _('No knowledge entries yet') if not entries else None}


def overview_props(user, moment=None):
    """The overview island's props: the blocks the person may read, each in words; a block the person may not read is
    left out (None)."""
    found = overview(user, moment)
    now = found['now']
    return {
        'today': {'title': _('Company today'),
                  'meta': _('Worked out %(when)s · %(zone)s') % {'when': when(now), 'zone': found['zone']},
                  'tiles': _tiles(found, now)},
        'sites': _sites(user, found['sites'], now) if found['sites'] is not None else None,
        'alarms': _alarms(found['alarms']) if found['alarms'] is not None else None,
        'people': _people(found['people']) if found['people'] is not None else None,
        'upcoming': upcoming_props(found['reports']),
        'feed': _feed(found['feed']) if found['feed'] is not None else None,
        'messages': _messages(found['messages']) if found['messages'] is not None else None,
        'activity': _activity(found['activity']) if found['activity'] is not None else None,
        'knowledge': _knowledge(found['knowledge']) if found['knowledge'] is not None else None,
    }
