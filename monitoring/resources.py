"""The monitoring tabs on top of core.crud: Setup › Facility structure › Monitoring boards (the boards of the Monitoring
page, with their cards saved as a list on a tab of their own) and Setup › Reference data › Card templates and Card
template rules (what a card holds, and which unit's card gets which; monitoring/cards/) and pH window scales (the two
ends of a card's pH window, per water type)."""
from django.db.models import Case, Count, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.urls import path
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core import formpanels
from core.crud import Resource, RowList

from .forms import (BoardUnitFormSet, CardTemplateAssignmentForm, CardTemplateForm, MonitorBoardForm,
                    PhWindowScaleForm)
from .models import CardTemplate, CardTemplateAssignment, MonitorBoard, MonitorBoardUnit, PhWindowScale


class BoardUnits(RowList):
    """A board's cards, one per unit, saved as a whole list."""

    key, tab, label = 'units', 'units', _('Units')
    # Its panel's words (monitoring/board_form.html).
    title = _('Units')
    help_text = _('One card per unit, in the farm’s order. A card is drawn as the board says unless its row says otherwise. '
                  'A unit that is deleted keeps its row and its card comes back when the unit does; saving this list drops '
                  'the row. The cards are saved separately from the board’s details.')
    empty_text = _('No cards yet. Use “Add unit” to add a row.')
    add_label, save_label = _('Add unit'), _('Save cards')
    pending_text = _('Cards can be added once the board is created.')
    row_kind = 'monitor-board-row'
    formset = BoardUnitFormSet
    saved = ngettext_lazy('%(count)d card saved.', '%(count)d cards saved.', 'count')

    @classmethod
    def describe(cls, row):
        """e.g. "T-01: Detailed", in English (a template's name as stored: a built-in's is its msgid)."""
        return f'{row.unit.code}: {row.template.name if row.template else "as the board"}'


class MonitorBoardResource(Resource):
    model = MonitorBoard
    form_class = MonitorBoardForm
    name, plural = _('monitoring board'), _('monitoring boards')
    # Its own prefix, so the menu does not mark the Monitoring page while a board is edited.
    url_prefix = 'monitoring-boards'
    search_fields = ['name']
    list_template = 'monitoring/board_list.html'
    form_template = 'monitoring/board_form.html'
    icon = 'monitor'
    row_lists = (BoardUnits,)
    page_size = 50

    @classmethod
    def next_panels(cls, view, form, obj, extra):
        """monitoring/board_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

    @classmethod
    def queryset(cls):
        # A subquery, not a join with a count: an edit locks the row (FOR UPDATE), which a GROUP BY refuses.
        cards = (MonitorBoardUnit.objects.filter(board=OuterRef('pk'), unit__is_deleted=False).order_by().values('board')
                 .annotate(n=Count('pk')).values('n'))
        return super().queryset().select_related('default_template').annotate(
            cards=Coalesce(Subquery(cards, output_field=IntegerField()), Value(0))).order_by('name')


def _count(queryset, link):
    """A subquery counting the rows of `queryset` per template through `link` (an edit locks the row FOR UPDATE,
    which a GROUP BY of a join refuses)."""
    return Coalesce(Subquery(queryset.filter(**{link: OuterRef('pk')}).order_by().values(link)
                             .annotate(n=Count('pk')).values('n'), output_field=IntegerField()), Value(0))


def layout_lines(layout):
    """One English line per widget, for the activity log: 'w3 value 3x2 at 0,0 binds oxygen_mg_l'."""
    lines = []
    for widget in (layout or {}).get('widgets', []):
        line = (f"{widget.get('id')} {widget.get('type')} {widget.get('w')}x{widget.get('h')} "
                f"at {widget.get('x')},{widget.get('y')}")
        bind = widget.get('bind') or {}
        if bind.get('parameter'):
            line += f" binds {bind['parameter']}" + (f" at {bind['point']}" if bind.get('point') else '')
        if widget.get('opts'):
            line += ' ' + ', '.join(f'{key} {value}' for key, value in sorted(widget['opts'].items()))
        lines.append(line)
    return '; '.join(lines) or 'no widgets'


class CardTemplateResource(Resource):
    model = CardTemplate
    form_class = CardTemplateForm
    name, plural = _('card template'), _('card templates')
    url_prefix = 'card-templates'
    search_fields = ['name', 'description']
    list_template = 'monitoring/template_list.html'
    form_template = 'monitoring/template_form.html'
    icon = 'layout-dashboard'
    page_size = 50

    @classmethod
    def queryset(cls):
        return super().queryset().annotate(
            rules=_count(CardTemplateAssignment.objects.all(), 'template'),
            boards=_count(MonitorBoard.objects.all(), 'default_template'),
            cards=_count(MonitorBoardUnit.objects.filter(board__is_deleted=False, unit__is_deleted=False), 'template'),
        ).order_by('-is_builtin', 'name')

    @classmethod
    def snapshot(cls, obj):
        """The form's fields, the layout said as one line per widget instead of its JSON."""
        found = super().snapshot(obj)
        found[str(CardTemplate._meta.get_field('layout').verbose_name)] = layout_lines(obj.layout)
        return found

    @classmethod
    def urls(cls):
        from . import views
        return [path(f'{cls.url_prefix}/preview/', views.preview, name='cardtemplate_preview'), *super().urls(),
                path(f'{cls.url_prefix}/<uuid:pk>/copy/', views.copy_template, name='cardtemplate_copy')]


class CardTemplateAssignmentResource(Resource):
    model = CardTemplateAssignment
    form_class = CardTemplateAssignmentForm
    name, plural = _('card template rule'), _('card template rules')
    url_prefix = 'card-template-rules'
    search_fields = ['template__name', 'unit__code', 'system__name', 'species__common_name']
    list_template = 'monitoring/rule_list.html'
    icon = 'list-checks'
    page_size = 50

    @classmethod
    def queryset(cls):
        """In the ladder's order: unit, system, system type, species, kind, then the global rule."""
        rank = Case(When(unit__isnull=False, then=Value(1)), When(system__isnull=False, then=Value(2)),
                    When(system_type__isnull=False, then=Value(3)), When(species__isnull=False, then=Value(4)),
                    When(kind__isnull=False, then=Value(5)), default=Value(6), output_field=IntegerField())
        return (super().queryset().select_related('template', 'unit', 'system', 'species')
                .annotate(rank=rank).order_by('rank', 'created_at'))


class PhWindowScaleResource(Resource):
    """Setup › Reference data › pH window scales: per water type, the two ends of the pH window on the monitoring cards
    (owner decision 15): one row each, seeded, changed only."""

    model = PhWindowScale
    form_class = PhWindowScaleForm
    name, plural = _('pH window scale'), _('pH window scales')
    url_prefix = 'ph-window-scales'
    actions = ('change',)
    list_template = 'monitoring/ph_scale_list.html'
    icon = 'gauge'
