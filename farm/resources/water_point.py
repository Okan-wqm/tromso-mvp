import uuid

from django.db.models import Case, F, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from core.crud import Resource, filter_by

from ..forms.water_point import OWNER_TYPES, SamplingPointForm
from ..models import Equipment, SamplingPoint, Site, System, Tank
from ..models.water_point import EQUIPMENT, OWNER_FIELDS, SYSTEM, UNIT, PointKind
from ..water import points

OWNER_MODELS = {UNIT: Tank, SYSTEM: System, EQUIPMENT: Equipment}


class SamplingPointResource(Resource):
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
