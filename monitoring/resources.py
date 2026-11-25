"""The monitoring tabs on top of core.crud: Setup › Facility structure › Monitoring boards (the boards of the Monitoring
page, with their cards saved as a list on a tab of their own) and Setup › Reference data › Card templates and Card
template rules (what a card holds, and which unit's card gets which; monitoring/cards/) and pH window scales (the two
ends of a card's pH window, per water type)."""
from django.contrib import messages
from django.db.models import Case, Count, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.urls import path
from django.utils.formats import number_format
from django.utils.translation import gettext_lazy as _, ngettext, ngettext_lazy

from core import formpanels
from core.crud import Resource, RowList

from .forms import (BoardUnitFormSet, CardTemplateAssignmentForm, CardTemplateForm, MonitorBoardForm,
                    PhWindowScaleForm)
from .models import CardTemplate, CardTemplateAssignment, MonitorBoard, MonitorBoardUnit, PhWindowScale

# A board whose screen and distance leave room for this many cards a page or fewer is saved with a warning.
FEW_A_PAGE = 2


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
    def after_commit(cls, request, obj, created):
        """Saved, but its screen and distance leave room for FEW_A_PAGE cards a page or fewer: the person is told what
        the wall will do and what shows more (review round 2, B3). A pair at which no card can be read never saves
        (MonitorBoard.clean)."""
        found = obj.reach()
        if found is not None and 0 < found.per_page <= FEW_A_PAGE:
            messages.warning(request, ngettext(
                'From %(distance)s m this screen shows %(count)d card a page: the wall turns its pages. A nearer '
                'distance or a larger screen shows more.',
                'From %(distance)s m this screen shows %(count)d cards a page: the wall turns its pages. A nearer '
                'distance or a larger screen shows more.', found.per_page) % {
                    'distance': number_format(obj.distance_m, 1), 'count': found.per_page})

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


# ---- the lists in the new look (core/listprops.py), in the classic lists' words -----------------------------------------
def _board_rows(cls, view, objects, context):
    """Monitoring boards (monitoring/board_list.html): a board, how its cards are drawn, its cards, its refresh, its
    screen and the distance it is read from; Open (its wall), Edit and Delete."""
    from django.urls import reverse
    from django.utils.formats import localize
    from django.utils.http import urlencode
    from django.utils.translation import gettext

    from core import listprops as L

    def screen(board):
        if not board.screen:
            shown = '—'
        elif board.screen == 'other':
            shown = gettext('%(inches)s″ screen') % {'inches': localize(board.screen_inches)}
        else:
            shown = board.get_screen_display()
        return L.cell(shown, sub=[gettext('Read from %(metres)s m') % {'metres': localize(board.distance_m)}
                                  if board.distance_m else ''])

    return {
        'columns': [L.column('board', _('Board')), L.column('template', _('Cards are drawn with')),
                    L.column('cards', _('Cards'), numeric=True), L.column('refresh', _('Refresh (s)'), numeric=True),
                    L.column('screen', _('Wall screen'))],
        'rows': [L.row(board.pk, {
            'board': L.title(view, context, board, board.name, sub=[board.description]),
            'template': L.cell(str(board.default_template) if board.default_template else _('As the rules say')),
            'cards': L.cell(localize(board.cards)),
            'refresh': L.cell(localize(board.refresh_seconds) if board.refresh_seconds else '—'),
            'screen': screen(board),
        }, [L.link(f"{reverse('monitoring:monitor')}?{urlencode({'board': board.pk})}",
                   gettext('Open %(name)s') % {'name': board.name}, 'monitor'),
            *L.edit_delete(view, context, board, board.name)]) for board in objects],
    }


def _template_rows(cls, view, objects, context):
    """Card templates (monitoring/template_list.html): the built-ins first (shown, copied, never changed), each with
    how many rules, boards and board cards use it; Copy (a post), Edit (the designer's page) and Delete."""
    from django.urls import reverse
    from django.utils.formats import localize
    from django.utils.translation import gettext

    from core import listprops as L

    def actions(template):
        name = template.shown_name
        done = [L.post(reverse('monitoring:cardtemplate_copy', args=[template.pk]),
                       gettext('Copy %(name)s') % {'name': name}, 'plus')] if context.get('can_add') else []
        if not template.is_builtin:
            if context.get('can_change'):
                done.append(L.link(view.url('edit', template.pk), gettext('Edit %(name)s') % {'name': name}, 'pencil'))
            if context.get('can_delete'):
                done.append(L.link(view.url('delete', template.pk), gettext('Delete %(name)s') % {'name': name}, 'trash',
                                   danger=True))
        return done

    return {
        'columns': [L.column('template', _('Template')), L.column('rules', _('Rules'), numeric=True),
                    L.column('boards', _('Boards'), numeric=True), L.column('cards', _('Cards'), numeric=True)],
        'rows': [L.row(template.pk, {
            'template': L.cell(template.shown_name, strong=True,
                               href=view.url('edit', template.pk) if context.get('can_change') and not template.is_builtin
                               else None, sub=[template.description],
                               chips=[L.chip('neutral', _('Built in'))] if template.is_builtin else ()),
            'rules': L.cell(localize(template.rules)),
            'boards': L.cell(localize(template.boards)),
            'cards': L.cell(localize(template.cards)),
        }, actions(template)) for template in objects],
    }


def _rule_rows(cls, view, objects, context):
    """Card template rules (monitoring/rule_list.html), in the ladder's order: what a rule is for and its template; the
    global rule is never deleted."""
    from django.utils.translation import gettext

    from core import listprops as L

    def actions(rule):
        name = rule.scope_label
        done = [L.link(view.url('edit', rule.pk), gettext('Edit %(name)s') % {'name': name}, 'pencil')] \
            if context.get('can_change') else []
        if context.get('can_delete') and not rule.is_global:
            done.append(L.link(view.url('delete', rule.pk), gettext('Delete %(name)s') % {'name': name}, 'trash',
                               danger=True))
        return done

    return {
        'columns': [L.column('scope', _('For')), L.column('template', _('Template'))],
        'rows': [L.row(rule.pk, {
            'scope': L.cell(rule.scope_label, strong=True,
                            href=view.url('edit', rule.pk) if context.get('can_change') else None),
            'template': L.cell(str(rule.template.shown_name)),
        }, actions(rule)) for rule in objects],
    }


def _scale_rows(cls, view, objects, context):
    """pH window scales (monitoring/ph_scale_list.html): per water type, the two ends of a card's pH window, and the
    help sentence the classic page says under it."""
    from django.utils.formats import localize
    from django.utils.translation import gettext

    from core import listprops as L
    return {
        'columns': [L.column('water', _('Water type')), L.column('low', _('From pH'), numeric=True),
                    L.column('high', _('To pH'), numeric=True)],
        'notices': [L.notice('scale', 'info', _('A card’s pH window is drawn on the scale of its unit’s water type. A pH '
                                                'beyond the scale is shown as an arrow and the number.'))],
        'rows': [L.row(row.pk, {
            'water': L.cell(row.get_water_type_display(), strong=True),
            'low': L.cell(localize(row.ph_low)),
            'high': L.cell(localize(row.ph_high)),
        }, [L.link(view.url('edit', row.pk), gettext('Edit'), 'pencil')] if context.get('can_change') else [])
            for row in objects],
    }


# each tab's list in the new look, with its classic template's search placeholder and empty sentence (the same msgids)
for _tab, _rows, _placeholder, _empty in (
        (MonitorBoardResource, _board_rows, _('Search by name'), _(
            'A board is a named wall screen: the units it shows and how each card is drawn. Everyone who may read '
            'Monitoring can open it.')),
        (CardTemplateResource, _template_rows, _('Search by name'), _(
            'A card template places widgets on a monitoring card; the card’s frame (the unit, its state and why) is '
            'always shown.')),
        (CardTemplateAssignmentResource, _rule_rows, _('Search by template, unit, system or species'), _(
            'A rule gives a template to a unit, a system, a type of system, a species or a kind of unit; the most '
            'specific rule wins.')),
        (PhWindowScaleResource, _scale_rows, _('Search'), _(
            'One row per water type is made by the platform; it is changed, never added or deleted.'))):
    _tab.list_rows, _tab.search_placeholder, _tab.empty_text = classmethod(_rows), _placeholder, _empty
