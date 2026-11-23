"""The message catalogs (locale/<language>/LC_MESSAGES/django.po) without GNU gettext: Babel does what
makemessages and compilemessages do, so a Windows machine without gettext can build them too.

- `extract()` reads every msgid from the code and the templates (templates go through Django's own
  `templatize`, as makemessages does);
- `update(language)` adds the new msgids to the language's .po file and drops the ones no longer used;
- `compile(language)` writes the .mo file Django loads. The .mo files are built, not committed.

The source language (settings.LANGUAGE_CODE) has no catalog: its msgids are the text itself."""
import io
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import django
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir, extract_python
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po
from django.conf import settings
from django.template.base import Origin
from django.utils.translation import templatize, to_locale

# What Django's makemessages looks for, in Babel's keyword notation (the argument positions).
KEYWORDS = {
    '_': None, 'gettext': None, 'gettext_lazy': None, 'gettext_noop': None,
    'ngettext': (1, 2), 'ngettext_lazy': (1, 2),
    'pgettext': ((1, 'c'), 2), 'pgettext_lazy': ((1, 'c'), 2),
    'npgettext': ((1, 'c'), 2, 3), 'npgettext_lazy': ((1, 'c'), 2, 3),
}
TRANSLATOR_COMMENT = 'Translators:'
# Code that never shows text to people: build output, dependencies, migrations, the catalogs themselves.
SKIPPED_DIRECTORIES = {'node_modules', 'static', 'locale', 'migrations'}
PROJECT = 'balik-ciftligi'
HEADER = '# {language} translations of the fish farm prototype.\n#'


def languages():
    """The languages that have a catalog: all but the source language."""
    return [code for code, _ in settings.LANGUAGES if code != settings.LANGUAGE_CODE]


def language_name(language):
    return dict(settings.LANGUAGES)[language]


def po_path(language):
    return Path(settings.LOCALE_PATHS[0]) / language / 'LC_MESSAGES' / 'django.po'


def mo_path(language):
    return po_path(language).with_suffix('.mo')


def is_built(language):
    """Whether the .mo file exists and is not older than the .po file it was built from."""
    po, mo = po_path(language), mo_path(language)
    return po.exists() and mo.exists() and mo.stat().st_mtime >= po.stat().st_mtime


def extract_template(fileobj, keywords, comment_tags, options):
    """Babel extractor for Django templates: the template becomes Python calls that Babel reads."""
    source = templatize(fileobj.read().decode(options.get('encoding', 'utf-8')), origin=Origin(fileobj.name))
    # The template's own indentation survives and Python's tokenizer rejects it; msgids never span lines.
    source = '\n'.join(line.lstrip() for line in source.split('\n'))
    return extract_python(io.BytesIO(source.encode()), keywords, comment_tags, options)


def keep_directory(path):
    name = Path(path).name
    return not name.startswith('.') and name not in SKIPPED_DIRECTORIES


def extract():
    """A catalog holding every msgid of the project, untranslated."""
    method_map = [
        ('**/tests.py', 'ignore'), ('**/test_*.py', 'ignore'), ('**.py', 'python'),
        ('**.html', extract_template), ('**.txt', extract_template),
    ]
    catalog = Catalog(header_comment=None)
    for filename, line, message, comments, context in extract_from_dir(
            settings.BASE_DIR, method_map, keywords=KEYWORDS, comment_tags=[TRANSLATOR_COMMENT],
            directory_filter=keep_directory):
        catalog.add(message, locations=[(filename, line)], auto_comments=comments, context=context)
    return catalog


def load(language):
    with po_path(language).open('rb') as file:
        return read_po(file, locale=language)


def new_catalog(language):
    """The header of a language's first .po file. Its plural rule is the one Django's own catalog of the
    language uses, so the two always agree."""
    django_po = Path(django.__file__).parent / 'conf' / 'locale' / to_locale(language) / 'LC_MESSAGES' / 'django.po'
    with django_po.open('rb') as file:
        plural_forms = read_po(file).plural_forms
    now = datetime.now(timezone.utc)
    catalog = Catalog(
        locale=language, header_comment=HEADER.format(language=language_name(language)), project=PROJECT,
        version='1.0', msgid_bugs_address='', last_translator='Suderra', language_team=f'{language_name(language)}',
        creation_date=now, revision_date=now, charset='utf-8', fuzzy=False,
    )
    catalog.mime_headers = [('Plural-Forms', plural_forms)]
    return catalog


def updated(language):
    """The language's catalog brought up to date with the code: its translations, the project's current
    msgids, nothing else. A new msgid has an empty translation until someone writes it."""
    catalog = load(language) if po_path(language).exists() else new_catalog(language)
    catalog.update(extract(), no_fuzzy_matching=True, update_creation_date=False)
    return catalog


def dump(catalog):
    """The catalog as the bytes of its .po file: sorted, without locations, so a change to the code
    shows in the file only where a msgid or a translator's note changed."""
    file = io.BytesIO()
    write_po(file, catalog, width=100, sort_output=True, ignore_obsolete=True, no_location=True)
    return file.getvalue()


def update(language):
    path = po_path(language)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump(updated(language)))


def compile(language):
    """Writes the language's .mo file. Other processes may be loading it meanwhile (the parallel test workers each
    build the catalogs, a running server reads them), so a reader must never meet a half-written file: the new file is
    written beside the old one and takes its place in one step, and a file that would not change is left as it is
    (only its time is brought up to the .po file's, for `is_built`)."""
    path = mo_path(language)
    file = io.BytesIO()
    write_mo(file, load(language))
    content = file.getvalue()
    if path.exists() and path.read_bytes() == content:
        if not is_built(language):
            os.utime(path)
        return
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'wb') as written:
            written.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
