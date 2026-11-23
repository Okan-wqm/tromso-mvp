"""Company › Administration › Opening balances (F-197): the fish the farm already had when it started using the platform,
registered once by the platform owner (services.record_opening_balance) and listed for who may read them. Registering is
the stocking dialog's form and unit rows with the takeover day, the real stocking date and the source document."""
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.urls import reverse
from django.utils.translation import gettext as _

from core import navigation
from core.crud import done, render_page

from ..forms.stock import InputLineFormSet, OpeningBalanceForm, stockable_units
from ..models import OpeningBalance, StockMovement
from ..templatetags.stock import number
from .services import OPENING_PERM, AlreadyRecorded
from .views import _lines, _refused, _unit_choices

READ = 'farm.view_openingbalance'


def _context(**extra):
    place = navigation.place(READ)
    return {'title': place.entry.label, 'eyebrow': place.heading, **extra}


@permission_required(READ, raise_exception=True)
def opening_balances(request):
    """Every opening balance, newest first, voided ones marked: batch, units, fish, takeover day, real stocking date, year
    class, document and who registered it."""
    rows = (OpeningBalance.all_objects.select_related('operation__created_by', 'operation__deleted_by')
            .prefetch_related(Prefetch('operation__movements', StockMovement.objects.select_related('unit', 'batch')))
            .order_by('-operation__date', '-operation__created_at'))
    return render_page(request, 'farm/opening_balances.html', _context(
        rows=rows, can_register=request.user.has_perm(OPENING_PERM)))


@permission_required(OPENING_PERM, raise_exception=True)
def opening_balance_create(request):
    """Registers an opening balance: the platform owner's right only."""
    kwargs = {'form_kwargs': _unit_choices(stockable_units()), 'prefix': 'units'}
    back = reverse('farm:opening_balances')
    page = _context(heading=_('Register an opening balance'), back_url=back,
                    intro=_('Fish the farm already had when it started using the platform: their real stocking date and '
                            'year class, and their count and average weight on the takeover day. The batch number is '
                            'given on saving.'),
                    submit_label=_('Register the opening balance'))
    if request.method == 'POST':
        form = OpeningBalanceForm(request.POST)
        rows = InputLineFormSet(request.POST, **kwargs)
        lines = _lines(form, rows)
        if lines is not None:
            try:
                operation = form.save(request.user, lines)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                batch = operation.movements.first().batch
                messages.success(request, _('Opening balance %(batch)s registered: %(count)s fish in %(units)s.') % {
                    'batch': batch.code, 'count': number(form.cleaned_data['count']),
                    'units': ', '.join(unit.code for unit, _count in lines)})
                return done(request, back)
        return _refused(request, 'farm/stock_input.html', {**page, 'form': form, 'rows': rows})
    return render_page(request, 'farm/stock_input.html', {**page, 'form': OpeningBalanceForm(),
                                                          'rows': InputLineFormSet(**kwargs)})
