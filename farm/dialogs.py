"""The farm's operation dialogs in the new look (behind `?ui=next`, core.ui.is_next): a feeding, a treatment, its last day,
a sea-lice count and the voids of a feeding, a treatment, a count and a health event, opened as a page (never inside the
classic dialog: an X-Modal request keeps the classic dialog, whose module the island could not run) and drawn by the
record-form island (core.formprops.dialog_props) from the same form, view, address and context as the classic dialog.

`page(request, template, context)` is what the views call where they rendered the classic dialog's template: the classic
template in the classic look, else the island with the props of the template's builder (DIALOGS). What a dialog says
before its fields is rendered by the very partial its classic template includes (farm/_operation_context.html,
_feeding_intro.html, a void's entry …) and read as the island's blocks (core.formpanels.blocks_of), so its words have one
source. A refused save (422) is drawn again with the server's reasons on their fields; the withdrawal guard's question is
core.formpanels.question; a handling check's warnings, and the box to go on past them, are the form's
(`form.handling`, farm.handling.check), never worked out here."""
from django.template.loader import render_to_string

from core import formpanels
from core.crud import is_modal, render_page
from core.formprops import DRAWN, dialog_props
from core.ui import is_next

from . import words


def page(request, template, context, refused=False):
    """The dialog `template` with `context`: classic, or the island in the new look; `refused`: the 422 of a save refused."""
    builder = DIALOGS.get(template)
    props = builder(request, context) if builder is not None and is_next(request) and not is_modal(request) else None
    if props is not None:
        response = render_page(request, 'farm/dialog_next.html', {**context, 'props': props})
    else:
        response = render_page(request, template, context)
    if refused:
        response.status_code = 422
    return response


def _said(request, partial, context):
    """The blocks of a classic partial rendered with the dialog's context."""
    return formpanels.blocks_of(render_to_string(partial, context, request=request))


def _unshown_acks(form):
    """The acknowledgement boxes the classic dialog does not show yet (asked for by the service, or ticked: shown_acks)."""
    shown = {bound.name for bound in getattr(form, 'shown_acks', ())}
    return [name for name in getattr(form, 'ack_fields', ()) if name in form.fields and name not in shown]


def _handling(form):
    """A handling check's blocks (farm/_handling_panel.html: Before handling, its notes, its warnings, why a second person
    must approve) and the fields the classic panel leaves out: its box, unless there are warnings a tick may go past."""
    handling = getattr(form, 'handling', None)
    if handling is None or 'handling_ack' not in form.fields:
        return [], []
    title = formpanels.said(words.BEFORE_HANDLING)
    blocks = [formpanels.help_text(f'{title}: {note}') for note in handling.notes] or [formpanels.help_text(title)]
    if not handling.warnings:
        return blocks, ['handling_ack']
    # a warning's message is a method of the check (the classic template calls it)
    blocks.append(formpanels.notices(title, [warning.message() if callable(warning.message) else warning.message
                                             for warning in handling.warnings]))
    if handling.second_person:
        blocks.append(formpanels.notice(handling.second_person, 'warning'))
        return blocks, ['handling_ack']
    return blocks, []


def _dialog(request, context, intro, *, fieldsets=None, submit=None, danger=False, grid=None):
    form = context['form']
    handling, hidden = _handling(form)
    return dialog_props(request, form, action=request.get_full_path(), submit=submit or context['heading'],
                        cancel=context['back_url'], intro=[*intro, *handling], fieldsets=fieldsets,
                        leave_out=[*_unshown_acks(form), *hidden],
                        question=formpanels.question(getattr(form, 'withdrawal_change', None)), danger=danger, grid=grid)


def operation(request, context):
    """A stock operation on one unit (farm/stock_operation.html: a mortality, a cull, a harvest, a transfer, a grading),
    its rows (the units a transfer's or a grading's fish go into) posted with it. The classic dialog stays where the island
    cannot draw it all: no fish to record (its notice and Close), a weighing (its estimate is drawn again as its fields
    change), a widget the island does not draw."""
    from core.formpayload import UnknownWidget, kind_of
    form, rows = context.get('form'), context.get('rows')
    if not form or form.refresh_on:
        return None
    forms = [form, *((*rows.forms, rows.empty_form) if rows is not None else ())]
    try:
        if not all(kind_of(bound.field.widget) in DRAWN for each in forms for bound in each):
            return None
    except UnknownWidget:
        return None
    grid = None
    if rows is not None:
        shown = [bound.name for bound in rows.empty_form.visible_fields()]
        grid = formpanels.grid(rows, [rows.empty_form[name].label for name in shown],
                               lambda row: [[row[name]] for name in shown], legend=form.rows_label,
                               empty_text='', add=words.ADD_UNIT)
    intro = [*_said(request, 'farm/_operation_context.html', context), *_said(request, 'farm/_operation_lines.html', context)]
    return _dialog(request, context, intro, grid=grid)


def feeding(request, context):
    """Record feeding (farm/feeding_form.html): the unit and its fish, the split, a fast, the next meal filled in."""
    intro = [*_said(request, 'farm/_operation_context.html', context), *_said(request, 'farm/_operation_lines.html', context),
             *_said(request, 'farm/_feeding_intro.html', context)]
    return _dialog(request, context, intro)


def treatment(request, context):
    """Record treatment (farm/treatment_form.html): its fields in the classic groups, the handling check last."""
    return _dialog(request, context, _said(request, 'farm/_treatment_intro.html', context), fieldsets=[
        ('', ['units']),
        (words.WHAT_WAS_GIVEN, ['method', 'medicine', 'reason', 'start_date', 'end_date', 'bath_minutes']),
        (words.DOSE_AND_AMOUNT, ['dose_value', 'dose_unit', 'amount_value', 'amount_unit']),
        (words.PRESCRIPTION, ['prescribed_by', 'prescription_ref', 'vet', 'health_event']),
        ('', ['notes']), (words.BEFORE_HANDLING, ['handling_ack'])])


def last_day(request, context):
    return _dialog(request, context, _said(request, 'farm/_last_day_intro.html', context))


def lice(request, context):
    return _dialog(request, context, _said(request, 'farm/_lice_intro.html', context))


def voiding(partial):
    """A void (farm/stock_void.html's dialog): what is voided, the reason, and Void as the danger button."""
    def build(request, context):
        return _dialog(request, context, _said(request, partial, context), submit=words.VOID, danger=True)
    return build


DIALOGS = {
    'farm/stock_operation.html': operation,
    'farm/stock_void.html': voiding('farm/_stock_void_entry.html'),
    'farm/feeding_form.html': feeding,
    'farm/treatment_form.html': treatment,
    'farm/treatment_last_day.html': last_day,
    'farm/lice_form.html': lice,
    'farm/feeding_void.html': voiding('farm/_feeding_void_entry.html'),
    'farm/treatment_void.html': voiding('farm/_treatment_void_entry.html'),
    'farm/lice_void.html': voiding('farm/_lice_void_entry.html'),
    'farm/health_event_void.html': voiding('farm/_event_void_entry.html'),
}
