"""A document as a reference list cites it, in the shape of APA 7:

    Olsen, B. E., & Hansen, K. (2019). Carbon dioxide and growth of Atlantic salmon. Aquaculture, 512(3),
    45–67. https://doi.org/10.1016/j.aquaculture.2019.01.001

and as a text cites it in passing: "Olsen & Hansen (2019)", "Olsen et al. (2019)".

Authors are the document's lines, family name first ("Olsen, Bjørn Erik"); a line without a comma (an
organisation, "Mattilsynet") is cited as it is written. The venue (the journal) and its volume are in italics;
a document without authors is cited by its title, one without a year with "n.d.". One builder serves the HTML
of the pages and the plain text an agent will quote, so the two never differ.
"""
import re

from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

DOI_LINK = 'https://doi.org/'
APA_LISTED = 20     # APA 7 lists up to 20 authors; beyond that the first 19, an ellipsis and the last


def author_lines(text):
    """The authors, one per line, in their order."""
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def family_name(line):
    return line.split(',', 1)[0].strip()


def initials(given):
    """'Bjørn Erik' as 'B. E.', 'Bjørn-Erik' as 'B.-E.', 'B.E.' as 'B. E.'."""
    names = [name for name in re.split(r'[\s.]+', given) if name]
    return ' '.join('-'.join(f'{part[0]}.' for part in name.split('-') if part) for name in names)


def apa_author(line):
    """'Olsen, Bjørn Erik' as 'Olsen, B. E.'; an organisation as written."""
    if ',' not in line:
        return line
    family, given = (part.strip() for part in line.split(',', 1))
    shown = initials(given)
    return f'{family}, {shown}' if shown else family


def apa_authors(lines):
    """The author part of a reference: 'A', 'A, & B', 'A, B, & C'; past 20, the first 19, '…' and the last."""
    names = [apa_author(line) for line in lines]
    if len(names) <= 1:
        return ''.join(names)
    if len(names) > APA_LISTED:
        return ', '.join(names[:APA_LISTED - 1]) + ', … ' + names[-1]
    return ', '.join(names[:-1]) + ', & ' + names[-1]


def short_authors(lines):
    """How a text names the authors in passing: 'Olsen', 'Olsen & Hansen', 'Olsen et al.'."""
    families = [family_name(line) for line in lines]
    if len(families) > 2:
        return _('%(first)s et al.') % {'first': families[0]}
    return ' & '.join(families)


def year_of(document):
    return str(document.year) if document.year else _('n.d.')


def sentence(text):
    """A title or a name as a sentence of the reference: it ends with a full stop unless it ends with one already
    (or with ? or !)."""
    text = text.strip()
    return text if text.endswith(('.', '?', '!')) else f'{text}.'


def short(document):
    """'Olsen et al. (2019)'; a document without authors by its title."""
    lines = author_lines(document.authors)
    who = short_authors(lines) if lines else document.short_title()
    return f'{who} ({year_of(document)})'


def link(document):
    """Where the document is found: its DOI as a link, else its address; '' when it has neither."""
    return f'{DOI_LINK}{document.doi}' if document.doi else document.url


def _build(document, text, italic, linked):
    """The reference made of `text` (plain or escaped), `italic` and `linked` pieces."""
    lines = author_lines(document.authors)
    if lines:
        head = f'{text(sentence(apa_authors(lines)))} ({text(year_of(document))}). {text(sentence(document.title))}'
    else:
        head = f'{text(sentence(document.title))} ({text(year_of(document))}).'
    source = []
    if document.venue:
        source.append(italic(document.venue))
    if document.volume or document.issue:
        volume = italic(document.volume) if document.volume else ''
        source.append(volume + (f'({text(document.issue)})' if document.issue else ''))
    if document.page_range:
        source.append(text(document.page_range))
    parts = [head]
    if source:
        parts.append(', '.join(source) + '.')
    if link(document):
        parts.append(linked(link(document)))
    return ' '.join(parts)


def reference(document):
    """The reference as HTML: the venue and the volume in italics, the link clickable."""
    return mark_safe(_build(
        document, escape, lambda value: f'<i>{escape(value)}</i>',
        lambda url: f'<a href="{escape(url)}" rel="noopener noreferrer">{escape(url)}</a>'))


def plain(document):
    """The reference as plain text, as an agent will quote it or a person copies it into a paper."""
    same = lambda value: value
    return _build(document, same, same, same)
