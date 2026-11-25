from django import forms
from django.conf import settings
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _

from core.crud import TabbedForm, tab_fields

from ..models import Document
from ..models.document import normalise_authors, normalise_doi

DOCUMENT_FORM_TABS = [
    ('reference', _('Reference'), ['title', 'authors', 'year', 'venue', 'volume', 'issue', 'page_range', 'doi', 'url']),
    ('content', _('Content'), ['abstract', 'language', 'topics', 'species']),
    ('file', _('File'), ['file']),
]


class DocumentFileInput(forms.ClearableFileInput):
    """The PDF input: a stored file is shown by its own name and opened through the library's file view, never
    through a storage address (there is none: the file is not a public static file)."""

    template_name = 'knowledge/widgets/file_input.html'
    clear_checkbox_label = _('Remove the file')

    def current_url(self, value):
        """The stored file's address on the library's own file view, which checks who may read it (the form layer of the
        new look links it: core.formpayload)."""
        from django.urls import reverse
        return reverse('knowledge:document_file', args=[value.instance.pk])

    def is_initial(self, value):
        """A file the document already has (not one just chosen and refused)."""
        return bool(value) and getattr(value, 'instance', None) is not None and getattr(value, '_committed', False)


class DocumentForm(TabbedForm):
    """The document dialog. Saving a new PDF reads its text at once (Document.save); the File tab says what came
    of it."""

    tabs = DOCUMENT_FORM_TABS

    class Meta:
        model = Document
        fields = tab_fields(DOCUMENT_FORM_TABS)
        help_texts = {
            'title': _('As the document itself gives it.'),
            'authors': _('One author per line, in the order of the document, family name first: “Olsen, Bjørn '
                         'Erik”. An organisation as it is named: “Mattilsynet”.'),
            'year': _('The year it was published.'),
            'venue': _('The journal, book, conference, report series or publisher.'),
            'volume': _('The journal’s volume.'),
            'issue': _('The journal’s issue.'),
            'page_range': _('The pages in the journal or book, e.g. 45–67.'),
            'doi': _('e.g. 10.1016/j.aquaculture.2019.01.001; a link to doi.org is read as its DOI. Two documents of '
                     'the library cannot have the same DOI.'),
            'url': _('Where it can be read, when it has no DOI or the DOI is not enough. https:// is added when it is '
                     'left out.'),
            'abstract': _('The abstract or summary, as the document gives it.'),
            'topics': _('What it is about. The knowledge entries taken from it have topics of their own.'),
            'species': _('The species it is about, if any.'),
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': _('e.g. Carbon dioxide and the growth of Atlantic salmon')}),
            'authors': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Olsen, Bjørn Erik\nHansen, Kari'}),
            'year': forms.NumberInput(attrs={'placeholder': _('e.g. 2019')}),
            'venue': forms.TextInput(attrs={'placeholder': _('e.g. Aquaculture')}),
            'doi': forms.TextInput(attrs={'placeholder': '10.1016/j.aquaculture.2019.01.001'}),
            'url': forms.URLInput(attrs={'placeholder': 'https://example.com/report.pdf'}),
            'abstract': forms.Textarea(attrs={'rows': 6}),
            'topics': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'species': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
            'file': DocumentFileInput(attrs={'accept': 'application/pdf,.pdf'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The uploaded file's own name may be long; it is kept on the document (file_name), not as the stored name.
        self.fields['file'].max_length = None
        self.fields['file'].help_text = _('A PDF of up to %(limit)s. Its text is read when it is saved, page by page, '
                                          'for the search and, later, for the AI agents.') % {
            'limit': filesizeformat(settings.KNOWLEDGE_MAX_FILE_BYTES)}
        if not self.instance._state.adding:
            self.tab_help['file'] = self.instance.text_summary()

    def clean_authors(self):
        return normalise_authors(self.cleaned_data['authors'])

    def clean_doi(self):
        return normalise_doi(self.cleaned_data['doi'])
