"""The company overview's figures (Company › Overview, the redesigned board): what the company is doing now, read by each
area's own functions, each block only for a person who may read its area (None for the others).

Nothing here is worked out twice: the stock is the ledger's (farm.stock.read.stock_of), the water the Water chemistry
page's own rows (farm.water.views._latest), what needs a look the one reader of open alarms and the units' water
(alarms.read.attention, attention_by_site: the status strip's), the open alarms listed the Alarms page's (alarms.read.listing), the people the Today
page's board and muster (hr.read), the reports the overview's due list (config.views._upcoming), the feed the Storage
overview (inventory.read.overview), the messages the inbox (messaging.read), the activity what the person may read of
the log (core.audit.readable). Only the split per site is done here, and it reads the same rows."""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from farm.models import Site, Tank

ACTIVITY = 5        # the latest log entries shown
KNOWLEDGE = 3       # the latest knowledge entries shown
MESSAGES = 3        # the latest conversations with unread messages shown
ALARMS = 5          # the open alarms listed; the rest are a link


def _nothing():
    from alarms.read import Attention
    return Attention(alarms=0, alarms_critical=0, critical=0, warning=0, blind=0, unreadable=False)


def _site_of_point(point):
    """The site of a sampling point (farm.models.water_point.site_of, the one resolver), or None for one of equipment
    whose production department has none."""
    from farm.models.water_point import site_of
    try:
        return site_of(point)
    except AttributeError:
        return None


def _sites(user, now):
    if not user.has_perm('farm.view_site'):
        return None
    sites = list(Site.objects.order_by('name'))
    rows = {site.pk: {'site': site, 'units_stocked': None, 'biomass_kg': None, 'water': None, 'attention': None,
                      'on_site': None} for site in sites}
    if user.has_perm('farm.view_stockoperation'):
        from farm.stock import read as stock
        units = list(Tank.objects.select_related('production_department'))
        held = stock.stock_of(units)
        for row in rows.values():
            row['units_stocked'], row['biomass_kg'] = 0, Decimal(0)
        for unit in units:
            item = held.get(unit.pk)
            if item is None or unit.production_department is None:
                continue
            row = rows.get(unit.production_department.site_id)
            if row is not None:
                row['units_stocked'] += 1
                row['biomass_kg'] += item.biomass_kg
    if user.has_perm('farm.view_watermeasurement'):
        from farm.water.evaluate import Status
        from farm.water.views import _latest
        latest = _latest(None)
        for row in rows.values():
            row['water'] = {'critical': 0, 'warning': 0, 'points': 0, 'measured': 0, 'worst': None, 'stale_since': None}
        for water_row in latest['rows']:
            point, water = water_row['point'], water_row['water']
            site = _site_of_point(point) if point is not None else None
            if site is None or site.pk not in rows:
                continue
            said = rows[site.pk]['water']
            said['points'] += 1
            said['measured'] += bool(water.readings)
            if water.point_status == Status.CRITICAL:
                said['critical'] += 1
            elif water.point_status == Status.WARNING:
                said['warning'] += 1
            # The site's line says its worst value as the Water page judges it (PointWater.worst_alert: a critical
            # first, a fresh one before an old one), the first such point in the page's order; or, with no alert, since
            # when a point with limited values has had no recent data.
            alert = water.worst_alert
            if alert is not None and (said['worst'] is None or (alert[1] == Status.CRITICAL, not alert[2])
                                      > (said['worst'][1] == Status.CRITICAL, not said['worst'][2])):
                said['worst'] = alert
            if water.point_status == Status.STALE and water.newest_at is not None:
                said['stale_since'] = min(filter(None, [said['stale_since'], water.newest_at]))
    if user.has_perm('alarms.view_alarm'):
        # a site's open alarms and its units' water now, from the one reader (a site with neither is not in its answer)
        from alarms import read as alarms
        found = alarms.attention_by_site(now)
        for site_id, row in rows.items():
            row['attention'] = found.get(site_id) or _nothing()
    return {'rows': list(rows.values()), 'count': len(sites),
            'by_status': [(label, sum(1 for site in sites if site.status == value)) for value, label in Site.Status.choices
                          if any(site.status == value for site in sites)]}


def _alarms(user, now):
    """The open alarms and the units' water now (alarms.read.attention, the one reader: never a count of our own), and the
    first open alarms to list (the Alarms page's listing); the rest are a link."""
    if not user.has_perm('alarms.view_alarm'):
        return None
    from alarms import read as alarms
    attention = alarms.attention(now)
    shown = list(alarms.listing('open')[:ALARMS])
    return {'attention': attention, 'rows': shown, 'more': max(attention.alarms - len(shown), 0),
            'connected': alarms.connected()}


def _people(user, moment):
    if not user.has_perm('hr.view_attendancerecord'):
        return None
    from hr import read as hr
    from hr.scope import OFFICE
    board = hr.board(user, moment, realm=OFFICE)
    return {'board': board, 'on_site': board.on_site, 'on_site_by_site': dict(board.muster_sites),
            'to_decide': hr.pending_leave(user, OFFICE) if user.has_perm('hr.view_leaverequest') else None}


def _messages(user):
    if not user.has_perm('messaging.view_conversation'):
        return None
    from messaging import read as messaging
    rows = [row for row in messaging.inbox(user) if row.unread]
    return {'unread': messaging.unread_total(user), 'conversations': len(rows), 'rows': rows[:MESSAGES]}


def _feed(user):
    if not user.has_perm('inventory.view_inventoryoperation'):
        return None
    from inventory import read as inventory
    found = inventory.overview()
    return {'rows': [row for row in found.site_items if row.item.feed_id], 'low': found.low}


def _activity(user):
    if not user.has_perm('core.view_auditlog'):
        return None
    from core import audit
    return list(audit.readable(user)[:ACTIVITY])


def _knowledge(user):
    if not user.has_perm('knowledge.view_knowledgeentry'):
        return None
    from knowledge.models import KnowledgeEntry
    return list(KnowledgeEntry.objects.order_by('-created_at', '-pk')[:KNOWLEDGE])


def overview(user, moment=None):
    """Every block of the company overview, read now (`moment` for the people's board)."""
    from .views import _upcoming
    moment = moment or timezone.now()
    sites = _sites(user, moment)
    people = _people(user, moment)
    if sites is not None and people is not None:
        by_name = people['on_site_by_site']
        for row in sites['rows']:
            # The muster splits by site only when people are on more than one; one site holds them all.
            row['on_site'] = by_name.get(row['site'].name, 0) if by_name else (
                people['on_site'] if len(sites['rows']) == 1 else None)
    return {'now': moment, 'zone': settings.COMPANY_TIME_ZONE, 'sites': sites, 'alarms': _alarms(user, moment),
            'people': people, 'reports': _upcoming(user), 'messages': _messages(user), 'feed': _feed(user),
            'activity': _activity(user), 'knowledge': _knowledge(user)}
