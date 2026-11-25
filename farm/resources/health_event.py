from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.crud import Resource, filter_by

from ..forms.health import HealthEventForm
from ..health import diseases, lists, notices
from ..health.read import with_deaths
from ..models import HealthEvent, Site, Tank
from ..stock import views as stock_views

OPEN, CLOSED = 'open', 'closed'
NOTIFIABLE = 'notifiable'


class HealthEventResource(Resource):
    """Operations › Health events: observations, vet visits, lab results and rises in mortality, recorded and
    edited on their form and voided with a reason instead of deleted (farm/health/views.py)."""

    model = HealthEvent
    form_class = HealthEventForm
    name, plural = _('health event'), _('health events')
    url_prefix = 'operations/health/events'
    search_fields = ['findings', 'recommendations', 'examined_by', 'lab_reference', 'outcome', 'site__name',
                     'units__code']
    list_template = 'farm/health_event_list.html'
    icon = 'stethoscope'
    # the new look's list (farm/health/lists.py) in the classic list's words (farm/health_event_list.html)
    search_placeholder = _('Search findings, units, site or vet')
    empty_text = _("What was seen, found or advised about the fish's health: observations, vet and fish-health visits, "
                   'lab results and rises in mortality.')
    list_rows = staticmethod(lists.events)
    list_filters = staticmethod(lists.event_filters)
    actions = ('add', 'change')       # a health event is voided with a reason, not deleted
    page_size = 50

    @classmethod
    def form(cls, request, *args, **kwargs):
        """A new event from a unit's drawer starts on its site and with the unit ticked (`?unit=`)."""
        if not args and 'instance' not in kwargs and 'draft' not in kwargs:
            chosen = request.GET.get('unit', '')
            unit = Tank.objects.select_related('production_department').filter(pk=chosen).first() \
                if stock_views._is_uuid(chosen) else None
            if unit is not None and unit.production_department.site_id:
                kwargs['initial'] = {'site': unit.production_department.site_id, 'units': [unit.pk]}
        return cls.form_class(*args, **kwargs)

    @classmethod
    def queryset(cls):
        return with_deaths(super().queryset().select_related('site', 'vet', 'lab').prefetch_related('units'))

    @classmethod
    def list_queryset(cls, request):
        if request.GET.get('voided') == '1':
            return with_deaths(HealthEvent.all_objects.select_related('site', 'vet', 'lab', 'deleted_by')
                               .prefetch_related('units'))
        return cls.queryset()

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.filter(health_events__isnull=False).distinct().order_by('name')
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site_id')
        objects, chosen_kind = filter_by(request, objects, 'kind', HealthEvent.Kind.choices, 'kind')
        states = [(OPEN, _('Open')), (CLOSED, _('Closed')), (NOTIFIABLE, _('Notifiable diagnosis'))]
        chosen_state = request.GET.get('state', '')
        conditions = {OPEN: Q(closed_on__isnull=True), CLOSED: Q(closed_on__isnull=False),
                      NOTIFIABLE: Q(diagnosis__in=diseases.NOTIFIABLE)}
        if chosen_state in conditions:
            objects = objects.filter(conditions[chosen_state])
        else:
            chosen_state = ''
        if request.GET.get('q'):
            objects = objects.distinct()      # a search in the units can match an event twice
        listed = HealthEvent.objects.filter(diagnosis__in=diseases.NOTIFIABLE).select_related('site')
        events = list(listed)
        return objects, {
            'sites': sites, 'chosen_site': chosen_site,
            'kinds': HealthEvent.Kind.choices, 'chosen_kind': chosen_kind,
            'states': states, 'chosen_state': chosen_state,
            'show_voided': request.GET.get('voided') == '1',
            # Whom Mattilsynet has been told of: the filed notices (farm/health/notices.py); None: not checked.
            'told': notices.told(HealthEvent.all_objects.filter(diagnosis__in=diseases.NOTIFIABLE)),
            'to_notify': [(event, notices.start_url(event, request.user)) for event in notices.pending(events) or []],
            'can_void': request.user.has_perm('farm.delete_healthevent'),
        }
