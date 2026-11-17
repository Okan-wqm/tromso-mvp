"""The message catalogs: complete, translated, in step with the code, and every tab translatable."""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from importlib import import_module
from pathlib import Path
from unittest import mock

from babel.messages.mofile import write_mo
from django.conf import settings
from django.core.management import call_command
from django.db import models
from django.forms import ChoiceField, ModelChoiceField, ModelMultipleChoiceField
from django.test import SimpleTestCase, override_settings
from django.utils.functional import Promise
from django.utils.module_loading import import_string

from . import audit, catalogs
from .crud import Resource, tab_fields
from .models import AuditedModel


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


def named_placeholders(text):
    return set(re.findall(r'%\((\w+)\)', text))


def tags(text):
    return sorted(re.findall(r'</?\w+', text))


def forms_of(value):
    """The forms of a msgid or msgstr: one text, or the singular and plural of a counted message."""
    return value if isinstance(value, tuple) else (value,)


class CatalogCompletenessTests(SimpleTestCase):
    """What a person translating would trip over: an empty, fuzzy or broken translation."""

    def messages(self, language):
        return [message for message in catalogs.load(language) if message.id]

    def test_there_are_catalogs_for_every_language_but_the_source(self):
        self.assertEqual(catalogs.languages(), ['tr', 'nb'])
        for language in catalogs.languages():
            self.assertTrue(catalogs.po_path(language).exists(), language)

    def test_every_msgid_is_translated_in_every_language(self):
        for language in catalogs.languages():
            catalog = catalogs.load(language)
            for message in self.messages(language):
                with self.subTest(language=language, msgid=message.id):
                    self.assertFalse(message.fuzzy, 'fuzzy translation')
                    strings = forms_of(message.string)
                    self.assertEqual(len(strings), catalog.num_plurals if isinstance(message.id, tuple) else 1)
                    for text in strings:
                        self.assertTrue(text.strip(), 'empty translation')

    def test_translations_keep_the_placeholders_and_markup_of_their_msgid(self):
        for language in catalogs.languages():
            for message in self.messages(language):
                allowed = set().union(*(named_placeholders(form) for form in forms_of(message.id)))
                for text in forms_of(message.string):
                    with self.subTest(language=language, msgid=message.id, text=text):
                        self.assertLessEqual(named_placeholders(text), allowed)
                        if not isinstance(message.id, tuple):
                            self.assertEqual(named_placeholders(text), allowed)
                            self.assertEqual(tags(text), tags(message.id))

    def test_each_language_has_the_plural_rule_django_uses_for_it(self):
        for language in catalogs.languages():
            self.assertEqual(catalogs.load(language).plural_forms, catalogs.new_catalog(language).plural_forms)


class CatalogInStepWithCodeTests(SimpleTestCase):
    """`manage.py update_catalogs` would change nothing: every msgid in the code and templates is in
    the catalogs, and the catalogs hold nothing the code no longer uses."""

    def test_the_catalogs_hold_exactly_the_msgids_of_the_code(self):
        found = {(message.context, message.id) for message in catalogs.extract() if message.id}
        self.assertGreater(len(found), 200)
        for language in catalogs.languages():
            kept = {(message.context, message.id) for message in catalogs.load(language) if message.id}
            with self.subTest(language=language):
                self.assertEqual(sorted(found - kept, key=str), [], 'not in the catalog: run manage.py update_catalogs')
                self.assertEqual(sorted(kept - found, key=str), [], 'no longer used: run manage.py update_catalogs')

    def test_update_catalogs_would_change_nothing(self):
        for language in catalogs.languages():
            with self.subTest(language=language):
                self.assertEqual(catalogs.dump(catalogs.updated(language)), catalogs.po_path(language).read_bytes(),
                                 'run manage.py update_catalogs')

    def test_the_system_check_says_when_a_catalog_is_not_built(self):
        from .checks import catalogs_are_built
        self.assertEqual(catalogs_are_built(None), [])
        with override_settings(LOCALE_PATHS=[Path(settings.BASE_DIR) / 'static']):
            ids = [warning.id for warning in catalogs_are_built(None)]
        self.assertEqual(ids, ['core.W002'] * len(catalogs.languages()))


class CatalogBuildTests(SimpleTestCase):
    """Building a .mo file while other processes load it (the parallel test workers each build the catalogs, and a
    running server reads them): a reader sees the old file or the new one, never a half-written one."""

    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        po = catalogs.po_path('nb')
        self.folder = folder / 'nb' / 'LC_MESSAGES'
        self.folder.mkdir(parents=True)
        shutil.copyfile(po, self.folder / po.name)
        settings_override = override_settings(LOCALE_PATHS=[folder])
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def test_a_failed_build_leaves_the_previous_file_whole(self):
        catalogs.compile('nb')
        built = catalogs.mo_path('nb').read_bytes()

        def half_written(file, catalog):
            file.write(built[:7])
            raise OSError('disk full')

        with mock.patch.object(catalogs, 'write_mo', half_written), self.assertRaises(OSError):
            catalogs.compile('nb')
        self.assertEqual(catalogs.mo_path('nb').read_bytes(), built)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ['django.mo', 'django.po'])

    def test_an_unchanged_catalog_is_not_written_again(self):
        catalogs.compile('nb')
        mo = catalogs.mo_path('nb')
        later = catalogs.po_path('nb').stat().st_mtime + 100
        os.utime(mo, (later, later))
        catalogs.compile('nb')
        self.assertEqual(mo.stat().st_mtime, later)

    def test_an_unchanged_catalog_older_than_its_po_file_counts_as_built_after_a_build(self):
        catalogs.compile('nb')
        mo = catalogs.mo_path('nb')
        earlier = catalogs.po_path('nb').stat().st_mtime - 100
        os.utime(mo, (earlier, earlier))
        self.assertFalse(catalogs.is_built('nb'))
        catalogs.compile('nb')
        self.assertTrue(catalogs.is_built('nb'))

    def test_a_changed_catalog_is_written(self):
        catalogs.compile('nb')
        catalogs.mo_path('nb').write_bytes(b'stale')
        catalogs.compile('nb')
        file = io.BytesIO()
        write_mo(file, catalogs.load('nb'))
        self.assertEqual(catalogs.mo_path('nb').read_bytes(), file.getvalue())


# Choices that are names, not text: time zones, and the languages' own names.
NOT_TEXT = {('farm.Site', 'timezone'), ('auth.User', 'language')}


class TabTranslationTests(SimpleTestCase):
    """Every tab (a Resource) declares its text as translatable text. A tab that writes a plain
    English string where a person reads it fails here, like one missing from the permission matrix
    fails TabRulesTests; the catalog test above then makes sure the msgids are in every catalog."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import_module(settings.ROOT_URLCONF)    # declares every resource
        cls.tabs = list(Resource.registry)
        # Each catalog's msgids, read once: parsing a .po file for every text took a quarter of an hour.
        cls.msgids = {language: {message.id for message in catalogs.load(language)} for language in catalogs.languages()}

    def assertTranslatable(self, text, where):
        self.assertIsInstance(text, Promise, f'{where} is plain text: wrap it in gettext_lazy')
        english = audit.english(text)
        for language in catalogs.languages():
            self.assertIn(english, self.msgids[language], f'{where}: {english!r} is not in the {language} catalog')

    def test_the_tabs_are_found(self):
        self.assertGreaterEqual(len(self.tabs), 5)

    def test_a_tabs_names_are_translatable(self):
        for tab in self.tabs:
            for attribute in ('name', 'plural'):
                self.assertTranslatable(getattr(tab, attribute), f'{tab.__name__}.{attribute}')

    def test_a_tabs_form_texts_are_translatable(self):
        for tab in self.tabs:
            form = tab.form_class
            for key, label, _ in form.tabs:
                self.assertTranslatable(label, f'{tab.__name__} inner tab {key!r}')
            for name in tab_fields(form.tabs):
                field, where = form.base_fields[name], f'{tab.__name__}.{name}'
                self.assertTranslatable(field.label, f'{where} label')
                if field.help_text:
                    self.assertTranslatable(field.help_text, f'{where} help text')
                if (tab.model._meta.label, name) in NOT_TEXT:
                    continue
                if isinstance(field, ChoiceField) and not isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
                    for value, text in field.choices:
                        if re.search('[A-Za-z]', str(text)) and value != '':
                            self.assertTranslatable(text, f'{where} choice {value!r}')

    def test_a_tabs_model_texts_are_translatable(self):
        for tab in self.tabs:
            if not issubclass(tab.model, AuditedModel):
                continue    # Django's own models (roles, users) are translated by Django
            meta = tab.model._meta
            self.assertTranslatable(meta.verbose_name, f'{meta.label} verbose_name')
            self.assertTranslatable(meta.verbose_name_plural, f'{meta.label} verbose_name_plural')
            for constraint in meta.constraints:
                if constraint.violation_error_message is not constraint.default_violation_error_message:
                    self.assertTranslatable(constraint.violation_error_message, f'{meta.label} {constraint.name}')
            for field in meta.get_fields():
                if isinstance(field, models.Field) and field.name in tab_fields(tab.form_class.tabs):
                    self.assertTranslatable(field.verbose_name, f'{meta.label}.{field.name} verbose_name')

    def test_menu_and_access_areas_are_translatable(self):
        for workspace in import_string(settings.RAIL_MENU):
            self.assertTranslatable(workspace.label, f'menu panel {workspace.key!r}')
            for section in workspace.sections:
                if section.label:
                    self.assertTranslatable(section.label, f'menu heading {section.label!r}')
                for group in section.groups:
                    if group.label:
                        self.assertTranslatable(group.label, f'menu group {group.label!r}')
                    for entry in group.entries:
                        self.assertTranslatable(entry.label, f'menu entry {entry.label!r}')
        for area in import_string(settings.ACCESS_AREAS):
            self.assertTranslatable(area.label, f'access area {area.model}')


class TypeScriptTests(SimpleTestCase):
    """The browser code is TypeScript with no text of its own: it type-checks, and the texts it
    shows come from data attributes the templates render in the person's language."""

    ROOT = Path(settings.BASE_DIR)
    # Key names the browser reports, not text.
    KEY_NAMES = {'Escape', 'Enter', 'Delete', 'Backspace', 'Home'}

    @classmethod
    def shipped(cls, root):
        """The TypeScript compiled for the browser: every .ts under frontend/ but the tests (`*.test.ts`,
        frontend/test/), which tsconfig.json leaves out of the build."""
        return sorted(path for path in (root / 'frontend').rglob('*.ts')
                      if not path.name.endswith('.test.ts') and 'test' not in path.relative_to(root / 'frontend').parts[:-1])

    @classmethod
    def ui_text(cls, root):
        """[(file, line number, line)] of every sentence in quotes in the shipped TypeScript (a key name is not text)."""
        sentence = re.compile(r"""(['"])([A-Z][a-z]+(?: [A-Za-z]+)*[.!?]?)\1""")
        found = []
        for path in cls.shipped(root):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                code = line.split('//')[0]
                found += [(path.relative_to(root).as_posix(), number, line.strip()) for match in sentence.finditer(code)
                          if match.group(2) not in cls.KEY_NAMES]
        return found

    def test_no_ui_text_in_the_typescript(self):
        self.assertEqual(self.ui_text(self.ROOT), [])

    def test_the_rule_reads_every_folder_of_the_browser_code_and_not_its_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('frontend/grid/layout.ts', 'frontend/grid/layout.test.ts', 'frontend/test/random.ts'):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("const word = 'Saved for you';\n", encoding='utf-8')
            self.assertEqual(self.ui_text(root), [('frontend/grid/layout.ts', 1, "const word = 'Saved for you';")])

    def test_the_browser_build_leaves_the_tests_out_and_the_test_build_has_them(self):
        shipped = json.loads((self.ROOT / 'tsconfig.json').read_text(encoding='utf-8'))
        self.assertEqual(shipped['exclude'], ['frontend/**/*.test.ts', 'frontend/test/**'])
        tests = json.loads((self.ROOT / 'tsconfig.test.json').read_text(encoding='utf-8'))
        self.assertEqual(tests['extends'], './tsconfig.json')
        self.assertEqual((tests['exclude'], tests['compilerOptions']['outDir']), ([], '.build/test'))
        self.assertIn('.build/', (self.ROOT / '.gitignore').read_text(encoding='utf-8').splitlines())

    def test_the_typescript_unit_tests_pass(self):
        """`npm test`: the test build, then `node --test` on it. Skipped on a machine without Node and `npm install`;
        under CI (`CI=1`) a missing Node is a failure, never a skip."""
        npm = shutil.which('npm')
        if npm is None or not (self.ROOT / 'node_modules').is_dir():
            if os.environ.get('CI') == '1':
                self.fail('CI needs Node and `npm install` to run the TypeScript tests')
            self.skipTest('Node and `npm install` are needed to run the TypeScript tests')
        result = subprocess.run([npm, 'test', '--silent'], cwd=self.ROOT, capture_output=True, text=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])

    def test_the_typescript_type_checks(self):
        npx = shutil.which('npx')
        if npx is None or not (self.ROOT / 'node_modules').is_dir():
            self.skipTest('Node and `npm install` are needed to type-check the TypeScript')
        result = subprocess.run([npx, 'tsc', '-p', 'tsconfig.json', '--noEmit'], cwd=self.ROOT,
                                capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
