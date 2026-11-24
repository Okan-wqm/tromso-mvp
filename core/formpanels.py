"""The panels a tab's own form page adds to crud/form.html (its `form_template`: a site's contacts, a feed's suitability,
a device's channels, a credential's Replace the secret), as the record-form island draws them behind `?ui=next`
(frontend/islands/pages/RecordForm.tsx, `panels`), and the withdrawal guard's question a save may ask first.

A tab whose form page is a template of its own is drawn by the island only when its Resource words that template's
panels here (`Resource.next_panels`); any other keeps its classic page in the new look (core.formprops.drawable). Every
word is the msgid its classic template says, so the new page says nothing the old one did not, and
core/tests_formpanels.py holds every such tab to its classic page (core.pagesays.unsaid), new, editing and refused.

A panel is a tab of its own after the record's tabs (`tab` None), or more on one of the record's tabs (`tab`: the key of
the record's tab it stands on, a site's contacts on Contact). Its blocks, in order:
    help        a paragraph of help;
    notice      a sentence that stands out (`tone` info or warning);
    rows        a list of rows saved as a whole (core.crud.RowList): its own form, posted to the list's own address;
    table       a table read only (core.listprops' columns, cells and rows);
    status      a record's state as a chip and what goes with it (an entry's Reviewed, by whom and when);
    checks      lines ticked or not, read only (a started checklist);
    post        a form of one button and its hidden fields (Replace the secret, Mark as reviewed);
    link        a link drawn as a button (Move device)."""
from django.utils.translation import gettext as _

from .formpayload import plain


def said(text):
    """A template's msgid said from Python: a template's msgid has its per cent signs doubled (Django's trans tag looks a
    literal up with each % doubled and puts them back after), so a word of a template written in Python doubles them
    too, to be the same msgid, and is said with them put back here."""
    return str(text).replace('%%', '%')


def panel(key, label, blocks, *, tab=None, has_errors=False):
    return {'key': key, 'label': None if label is None else said(label), 'tab': tab, 'hasErrors': bool(has_errors),
            'blocks': [block for block in blocks if block]}


def help_text(text):
    return {'kind': 'help', 'text': said(text)} if text else None


def notice(text, tone='info'):
    if tone not in ('info', 'warning'):
        raise ValueError(f'no notice tone {tone!r}')
    return {'kind': 'notice', 'tone': tone, 'text': str(text)}


def table(label, columns, rows):
    """A table read only: `columns` and `rows` as core.listprops builds them (column, row of cell)."""
    return {'kind': 'table', 'label': str(label), 'columns': columns, 'rows': rows}


def status(chip, text):
    """A record's state as a chip and what goes with it (an entry's Reviewed, by whom and when)."""
    return {'kind': 'status', 'chip': chip, 'text': str(text)}


def moment(value, where=None):
    """A moment as a template says it with `site_clock` (a site's, else the company's) and DATETIME_FORMAT."""
    from django.utils import formats

    from .templatetags.dates import site_clock
    return formats.date_format(site_clock(value, where), 'DATETIME_FORMAT')


def checks(label, lines):
    """Lines ticked or not, read only: (text, done, sub-line or '') each."""
    return {'kind': 'checks', 'label': str(label),
            'lines': [{'text': str(text), 'done': bool(done), 'sub': str(sub or '')} for text, done, sub in lines]}


def post(action, label, fields=(), *, primary=False):
    """A form of one button (its own address, its hidden fields; the page's CSRF token is added by the island)."""
    return {'kind': 'post', 'action': action, 'label': str(label), 'primary': bool(primary),
            'fields': [{'name': name, 'value': str(value)} for name, value in fields]}


def link(href, label, icon=None):
    return {'kind': 'link', 'href': href, 'label': str(label), 'icon': icon}


def notices(title, texts, tone='warning'):
    """A titled list of sentences that stand out (an experiment's design: what to fix before it can start)."""
    if tone not in ('warning', 'critical'):
        raise ValueError(f'no notice tone {tone!r}')
    return {'kind': 'notices', 'title': str(title), 'tone': tone, 'texts': [str(text) for text in texts]} if texts else None


def _shown(bound):
    """A bound field's value as its widget writes it (a key as text, a number localised)."""
    from .formpayload import widget_payload
    return plain(widget_payload(bound)['value'])


# ---- a form of its own: a grid saved as a whole (a feeding table, an experiment's design and places) --------------------
def form(action, label, parts, *, hidden=(), errors=(), actions=()):
    """A form of its own on the record's page, posted to its own address: its hidden fields (the record's version, bound
    fields of the server's own forms), the errors of the whole, its parts in order (`fields`, `grid`, `button`, a heading,
    help) and its buttons at the end (`button`)."""
    from django.forms import BoundField
    return {'kind': 'form', 'action': action, 'label': said(label),
            'hidden': [{'name': each.html_name, 'value': _shown(each)} if isinstance(each, BoundField)
                       else {'name': each[0], 'value': plain(each[1])} for each in hidden],
            'errors': [str(error) for error in errors], 'parts': [part for part in parts if part],
            'actions': [each for each in actions if each]}


def fields(*bounds):
    """Fields of the server's own forms, drawn as the record's are (their label, help and errors)."""
    from .formpayload import field_payload
    return {'kind': 'fields', 'fields': [field_payload(bound) for bound in bounds]}


def heading(text):
    return {'kind': 'heading', 'text': said(text)}


def button(label, name='', value='', *, primary=False, disabled=False):
    """A submit button; with `name` and `value` it says which of the form's buttons was pressed (Randomise, Add factor)."""
    return {'kind': 'button', 'label': said(label), 'name': name, 'value': str(value), 'primary': bool(primary),
            'disabled': bool(disabled)}


def grid(formset, columns, cells, *, legend, empty_text, add=None, can_add=True, head=None, label_of=None):
    """A formset as a table (farm/_band_row.html, experiments/_group_row.html): a heading row (`columns`; the Remove column
    is the last cell's own box), each row's hidden fields and errors and its cells (`cells(row)`: the bound fields of each
    cell, in the columns' order), a row's own heading (`head(row)`: a replicate's name), and, when rows can be added
    (`add`, its button's words, switched off while `can_add` is false; None: none), the formset's empty row. `label_of(bound)` words a field's label for a screen
    reader where its template does (SFR at 8 °C)."""
    from .formpayload import field_payload

    def field(bound):
        found = field_payload(bound)
        if bound.name == 'DELETE':
            found['label'] = _('Remove')
        elif label_of is not None:
            found['label'] = said(label_of(bound))
        return found

    def row_of(row):
        return {'head': str(head(row)) if head else None,
                'hidden': [{'name': bound.html_name, 'value': _shown(bound)} for bound in row.hidden_fields()],
                'errors': [str(error) for error in row.non_field_errors()],
                'cells': [[field(bound) for bound in cell] for cell in cells(row)]}
    return {'kind': 'grid', 'prefix': formset.prefix, 'legend': said(legend), 'columns': [said(each) for each in columns],
            'management': [{'name': bound.html_name, 'value': _shown(bound)} for bound in formset.management_form],
            'errors': [str(error) for error in formset.non_form_errors()], 'rows': [row_of(row) for row in formset.forms],
            'empty': row_of(formset.empty_form) if add is not None else None,
            'add': None if add is None else said(add), 'addDisabled': not can_add, 'emptyText': said(empty_text)}


def question(change):
    """The withdrawal guard's question (farm/_withdrawal_change.html, given its `withdrawal_change`): what the write does to
    a medicine withdrawal, and the box to go on (its value the warnings' fingerprint, so changed warnings are asked again)
    or, when a second person must approve, why a tick cannot go past it. None when nothing is asked."""
    if not change:
        return None
    from farm.health.withdrawal import FIELD
    second = str(change.second_person or '')
    return {'title': _('Medicine withdrawal'), 'messages': [str(text) for text in change.messages()],
            'secondPerson': second or None,
            'box': None if second else {
                'name': FIELD, 'value': change.fingerprint, 'label': _('Go on despite these warnings'),
                'help': _('Fish under a medicine withdrawal must not go to food. Going on is stored with what is shown '
                          'here and logged as critical.')}}


# The templates of the questions a save may ask first (Resource.question_template) that the island draws (`question`).
QUESTIONS = {'farm/_withdrawal_change.html'}


def list_words(row_list, obj):
    """A RowList's words for `obj` (RowList.words), said: the one source of them for both looks (the classic templates read
    them as `row_words`, core.crud.FormView.page)."""
    return {**{key: said(text) if text else '' for key, text in row_list.words(obj).items()},
            'fields': {name: said(text) for name, text in row_list.field_words().items()}}


def template_words(words):
    """Words for a classic template, escaped as a text node needs (&, <, >, ") and marked safe, so a template prints them
    with the bytes its own trans tag printed (it printed a msgid as it is: an apostrophe stays an apostrophe, where
    autoescape would write &#x27;). Only ever put between tags, never in an attribute: an apostrophe there would be
    harmless only in double quotes (core/tests_formpanels.py, TemplateWordsTests: hostile text)."""
    from django.utils.safestring import mark_safe

    def text(value):
        value = str(value)
        for raw, shown in (('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'), ('"', '&quot;')):
            value = value.replace(raw, shown)
        return mark_safe(value)
    return {key: template_words(value) if isinstance(value, dict) else text(value) for key, value in words.items()}


def rows(view, obj, row_list, formset, extra):
    """A RowList's own form (crud/_row_list.html, farm/_contacts.html): where it is saved, the record's version that travels
    with it, its rows with their fields under the list's words, an empty row to add, and what its save asked first (the
    withdrawal guard's question, on a refused save of a medicine's withdrawal)."""
    words = list_words(row_list, obj)
    named = words['fields']
    heads = [str(named.get(bound.name, bound.label)) for bound in formset.empty_form.visible_fields()
             if bound.name != 'DELETE']
    return {'kind': 'rows', 'action': view.url(row_list.key, obj.pk), 'version': plain(getattr(obj, 'version', None)),
            'save': words['save'],
            'grid': grid(formset, heads, lambda row: [[bound] for bound in row.visible_fields()], legend=words['legend'],
                         empty_text=words['empty'], add=words['add'], label_of=lambda bound: named.get(bound.name, bound.label)),
            'question': question(extra.get('withdrawal_change')) if row_list.question_field else None}


def row_list_panel(view, obj, row_list, extra):
    """The panel of one RowList: its help and its rows once the record can have them, else its `pending` sentence (a new
    record; a piece of equipment of a type without calibrations). None when the list says nothing then (a report's)."""
    formset = extra.get(row_list.key) if obj is not None else None
    words = list_words(row_list, obj)
    if formset is not None:
        blocks = [help_text(words['help']), rows(view, obj, row_list, formset, extra)]
        errors = bool(formset.non_form_errors()) or any(formset.errors)
    elif words['pending']:
        blocks, errors = [help_text(words['pending'])], False
    else:
        return None
    return panel(row_list.tab, words['title'], blocks, tab=row_list.tab if row_list.on_record_tab else None,
                 has_errors=errors)


def row_list_panels(resource, view, obj, extra, only=None):
    """The panels of the tab's RowLists (`only`: those of them the page shows), in their order."""
    return [found for row_list in resource.row_lists if only is None or row_list in only
            for found in [row_list_panel(view, obj, row_list, extra)] if found]
