import uuid

from django.db.models import Case, F, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from core import listprops as L
from core.crud import Resource, filter_by

from ..forms.water_point import OWNER_TYPES, SamplingPointForm
from ..models import Equipment, SamplingPoint, Site, System, Tank
from ..models.water_point import EQUIPMENT, OWNER_FIELDS, SYSTEM, UNIT, PointKind
from ..water import points
from .withdrawal_input import WithdrawalInput

OWNER_MODELS = {UNIT: Tank, SYSTEM: System, EQUIPMENT: Equipment}


class SamplingPointResource(WithdrawalInput, Resource):
    """Setup › Facility structure › Sampling points: where in the water a sample is taken, on a unit, a loop or a piece
    of equipment, of a kind that says whether it sees the stream in, the water within or the stream out. The default
    points of a new unit or system are made when it is created (farm/water/points.py)."""

    model = SamplingPoint
    form_class = SamplingPointForm
    name, plural = _('sampling point'), _('sampling points')
    url_prefix = 'sampling-points'
    search_fields = ['name', 'description', 'unit__code', 'unit__name', 'system__code', 'system__name',
                     'equipment__code', 'equipment__name']
    list_template = 'farm/samplingpoint_list.html'
    icon = 'droplet'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().with_owners()

    @classmethod
    def reached(cls, request, point):
        """Only an active middle point counts a unit's or a loop's water (farm/water/read.py), so its active flag, kind
        and owner move the degree-days of a withdrawal: every fish of the units of the owner it had and of the one it
        is given."""
        unit_ids = set()
        for owner_type in (UNIT, SYSTEM):
            owners = {getattr(point, f'{owner_type}_id'), request.POST.get(owner_type) or None} - {None}
            owners = [owner for owner in owners if cls._is_uuid(owner)]
            if owner_type == UNIT:
                unit_ids.update(Tank.all_objects.filter(pk__in=owners).values_list('pk', flat=True))
            else:
                unit_ids.update(Tank.all_objects.filter(system_id__in=owners).values_list('pk', flat=True))
        return unit_ids, None

    @staticmethod
    def _is_uuid(value):
        try:
            uuid.UUID(str(value))
        except ValueError:
            return False
        return True

    @classmethod
    def snapshot(cls, point):
        return points.snapshot(point)

    @classmethod
    def form(cls, request, *args, **kwargs):
        """A new point opened from an owner's page (?unit=, ?system= or ?equipment=) starts on that owner."""
        if not args and 'instance' not in kwargs and request.method == 'GET':
            owner_type, owner = cls.owner_of(request)
            if owner is not None:
                kwargs['initial'] = {'owner_type': owner_type, owner_type: owner.pk}
        return super().form(request, *args, **kwargs)

    @staticmethod
    def owner_of(request):
        """('unit', the unit) the address names with ?unit=, ?system= or ?equipment=; (None, None) when it names none."""
        for owner_type, model in OWNER_MODELS.items():
            value = request.GET.get(owner_type, '')
            try:
                uuid.UUID(value)
            except ValueError:
                continue
            owner = model.objects.filter(pk=value).first()
            if owner is not None:
                return owner_type, owner
        return None, None

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.all()
        chosen_site = request.GET.get('site', '')
        if chosen_site in {str(pk) for pk in sites.values_list('pk', flat=True)}:
            objects = objects.filter(Q(unit__production_department__site=chosen_site) | Q(system__site=chosen_site)
                                     | Q(equipment__production_department__site=chosen_site))
        else:
            chosen_site = ''
        chosen_type = request.GET.get('owner_type', '')
        if chosen_type in OWNER_FIELDS:
            objects = objects.filter(**{f'{chosen_type}__isnull': False})
        else:
            chosen_type = ''
        objects, chosen_kind = filter_by(request, objects, 'kind', PointKind.choices, 'kind')
        owner_type, owner = cls.owner_of(request)
        if owner is not None:
            objects = objects.filter(**{owner_type: owner})
        kind_order = Case(*(When(kind=kind, then=Value(rank)) for rank, kind in enumerate(PointKind.values)),
                          output_field=IntegerField())
        objects = objects.annotate(
            owner_code=Coalesce(F('unit__code'), F('system__code'), F('equipment__code')), kind_rank=kind_order,
        ).order_by('owner_code', 'kind_rank', 'name', 'pk')
        return objects, {
            'sites': sites, 'chosen_site': chosen_site,
            'owner_types': OWNER_TYPES, 'chosen_owner_type': chosen_type,
            'kinds': PointKind.choices, 'chosen_kind': chosen_kind,
            'narrowed': owner, 'narrowed_type': owner_type, 'share_notes': points.share_notes(sites.filter(pk=chosen_site).first()
                                                                  if chosen_site else None),
        }

    # The list in the new look (core/listprops.py), in the classic list's words (farm/samplingpoint_list.html).
    search_placeholder = _('Search by point or owner')
    empty_text = _('A point is a named place on a unit, a loop or a piece of equipment where water is sampled: its inlet, its '
                   'middle, its outlets. A new unit or system gets its points when it is created.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('owner_type', _('Owner'), context['chosen_owner_type'],
                     [('', _('All owners')), *context['owner_types']]),
            L.choice('kind', _('Kind'), context['chosen_kind'], [('', _('All kinds')), *context['kinds']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.template.defaultfilters import floatformat
        from django.urls import reverse
        from django.utils.http import urlencode
        user = view.request.user
        owner_word = {UNIT: _('Unit'), SYSTEM: _('System'), EQUIPMENT: _('Equipment')}

        def figure(value, digits='-2g'):
            return L.cell('–' if value is None else floatformat(value, digits))

        def owner(point):
            kind = UNIT if point.unit_id else SYSTEM if point.system_id else EQUIPMENT
            return L.cell(point.owner.code, strong=True, sub=[f'{point.owner.name} · {owner_word[kind]}'])

        def actions(point):
            done = []
            if user.has_perm('farm.view_watermeasurement'):
                done.append(L.link(f"{reverse('farm:water')}?{urlencode({'point': point.pk})}", _('History'), 'history'))
            return done + L.edit_delete(view, context, point, str(point))

        notices = []
        narrowed, narrowed_type = context['narrowed'], context['narrowed_type']
        if narrowed is not None:
            more = [(f"{context['create_url']}?{urlencode({narrowed_type: narrowed.pk})}", _('Add a point to it'))] \
                if context.get('can_add') else []
            notices.append(L.notice('narrowed', 'info', _('The points of %(owner)s.') % {'owner': narrowed.code},
                                    link=(context['list_url'], _('Show all')), more=more))
        for note in context['share_notes']:
            said = {'owner': note.owner.code, 'total': floatformat(note.total, '-2')}
            notices.append(L.notice(f'share-{note.owner.pk}', 'warning', (
                _('The outlets of %(owner)s take %(total)s %% of its outflow: more than 100 %%. Correct the shares.')
                if note.over else _('The outlets of %(owner)s take %(total)s %% of its outflow, not 100 %%.')) % said))
        notices.append(L.notice('points', 'info', _(
            'A sample says where it was taken: at one of these points. A unit’s water, as the rations, the withdrawal and '
            'the Production units page read it, is its middle point. The flow and the share of the outflow are the design '
            'or last-known figures a mass balance will start from; nothing here is measured.')))
        return {
            'columns': [L.column('owner', _('Owner')), L.column('point', _('Sampling point')), L.column('kind', _('Kind')),
                        L.column('flow', _('Flow (m³/h)'), numeric=True),
                        L.column('share', _('Share of the outflow (%)'), numeric=True),
                        L.column('depth', _('Depth (m)'), numeric=True), L.column('status', _('Status'))],
            'notices': notices,
            'rows': [L.row(point.pk, {
                'owner': owner(point),
                'point': L.title(view, context, point, point.name, sub=[point.description]),
                'kind': L.cell(point.get_kind_display(), sub=[point.role.label]),
                'flow': figure(point.flow_m3_h),
                'share': figure(point.flow_share_pct),
                'depth': figure(point.depth_m, '-1g'),
                'status': L.badge('active', _('Active')) if point.is_active else L.badge('inactive', _('Inactive')),
            }, actions(point), voided=not point.is_active) for point in objects],
        }
