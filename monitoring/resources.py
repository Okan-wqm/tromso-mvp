"""Setup › Facility structure › Monitoring boards: the boards of the Monitoring page on top of core.crud, with their cards saved
as a list on a tab of their own."""
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import Resource, RowList

from .forms import BoardUnitFormSet, MonitorBoardForm
from .models import MonitorBoard, MonitorBoardUnit


class BoardUnits(RowList):
    """A board's cards, one per unit, saved as a whole list."""

    key, tab, label = 'units', 'units', _('Units')
    formset = BoardUnitFormSet
    saved = ngettext_lazy('%(count)d card saved.', '%(count)d cards saved.', 'count')

    @classmethod
    def describe(cls, row):
        """e.g. "T-01: detailed", in English."""
        return f'{row.unit.code}: {row.get_mode_display() or "as the board"}'


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
    def queryset(cls):
        # A subquery, not a join with a count: an edit locks the row (FOR UPDATE), which a GROUP BY refuses.
        cards = (MonitorBoardUnit.objects.filter(board=OuterRef('pk'), unit__is_deleted=False).order_by().values('board')
                 .annotate(n=Count('pk')).values('n'))
        return super().queryset().annotate(
            cards=Coalesce(Subquery(cards, output_field=IntegerField()), Value(0))).order_by('name')
