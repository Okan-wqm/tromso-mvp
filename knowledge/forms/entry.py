from django import forms
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields

from ..models import Document, KnowledgeEntry, SourceKind
from ..models.entry import ALL_SOURCE_FIELDS, SOURCE_FIELDS, TOPICS_MESSAGE

ENTRY_FORM_TABS = [
    ('statement', _('Statement'), ['statement', 'topics', 'species']),
    ('source', _('Source'), ['source_kind', *ALL_SOURCE_FIELDS]),
]


class DocumentChoiceField(forms.ModelChoiceField):
    """A library document as a person picks it: how it is cited and its title."""

    def label_from_instance(self, document):
        return f'{document.short_citation()} · {document.short_title()}'


class KnowledgeEntryForm(TabbedForm):
    """The knowledge entry dialog. The Source tab shows the fields of the kind of source chosen; choosing another
    kind renders the form again with that kind's fields (TabbedForm.refresh_on), and saving empties the fields of
    the other kinds (KnowledgeEntry.clean), so an entry has exactly one source.

    The review is not typed here: it is the Review action (knowledge.views.review_entry), which records who
    reviewed it and when. Changing the statement, topics, species or source of a reviewed entry takes it back to
    draft (`returned_to_draft` says so after saving), so a review always covers what the entry says now."""

    tabs = ENTRY_FORM_TABS
    refresh_on = ('source_kind',)

    document = DocumentChoiceField(queryset=Document.objects.all(), required=False, label=_('Document'),
                                   help_text=_('The document in the library the knowledge comes from.'))

    class Meta:
        model = KnowledgeEntry
        fields = tab_fields(ENTRY_FORM_TABS)
        help_texts = {
            'statement': _('The knowledge in your own words, as one statement someone can act on, e.g. “In Atlantic '
                           'salmon under 50 g, free CO₂ above 15 mg/L leads to nephrocalcinosis.” or “A feed order is '
                           'at least 20 t and arrives 3 days after it is placed.”'),
            'topics': _('What it is about. AI agents will read the entries of the topics they watch.'),
            'species': _('The species it holds for; none when it holds for any.'),
            'source_kind': _('Where the knowledge comes from: every entry has exactly one source.'),
            'pages': _('Where in the document, e.g. 4 or 12–13.'),
            'section': _('e.g. 3.2 Results, Table 4.'),
            'quote': _('The source’s own words that say it, copied exactly.'),
            'citation': _('The source as a reference list cites it: authors, year, title, where it was published.'),
            'url': _('https:// is added when it is left out.'),
            'expert': _('Whose observation or advice it is, e.g. “Kari Nordmann, fish health vet” or your own name.'),
            'observed_on': _('When it was observed or said, if it matters.'),
        }
        widgets = {
            'statement': forms.Textarea(attrs={'rows': 4}),
            'topics': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'species': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'source_kind': forms.RadioSelect(attrs={'class': 'choices'}),
            'pages': forms.TextInput(attrs={'placeholder': _('e.g. 4')}),
            'quote': forms.Textarea(attrs={'rows': 4}),
            'citation': forms.Textarea(attrs={'rows': 3}),
            'url': forms.URLInput(attrs={'placeholder': 'https://example.com/article'}),
            'observed_on': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }
        error_messages = {'topics': {'required': TOPICS_MESSAGE}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source_kind'].choices = SourceKind.choices     # no empty choice: a radio per kind
        # Decided before any field is read: a bound field keeps the initial value it first saw.
        if self.is_bound or self.draft is not None:
            kind = self.current('source_kind')
        else:
            kind = self.initial.get('source_kind') or self.instance.source_kind
        kind = kind or SourceKind.DOCUMENT
        self.initial.setdefault('source_kind', kind)
        for name in ALL_SOURCE_FIELDS:
            if name not in SOURCE_FIELDS.get(kind, ()):
                del self.fields[name]
        # The Source tab in the order of the kind's own fields (a quote comes last for a published source).
        key, label, _names = ENTRY_FORM_TABS[1]
        self.tabs = [ENTRY_FORM_TABS[0], (key, label, ['source_kind', *SOURCE_FIELDS.get(kind, ())])]
        self.order_fields(tab_fields(self.tabs))

    def save(self, commit=True):
        entry = self.instance
        if not entry._state.adding and entry.status == KnowledgeEntry.Status.REVIEWED and self.changed_data:
            entry.return_to_draft()
            entry.returned_to_draft = True     # for the message after saving (KnowledgeEntryResource.after_save)
        return super().save(commit)
