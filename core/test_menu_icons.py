"""Every icon the menu and the tabs name exists as a file: `icons/_icon.html` includes it, and a missing one would raise
on every page that shows the entry."""
from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils.module_loading import import_string

from .crud import Resource


class IconTests(SimpleTestCase):
    def assertIconExists(self, name, where):
        self.assertTrue(name, f'{where} names no icon')
        get_template(f'icons/{name}.svg')               # raises TemplateDoesNotExist for a missing file

    def test_every_menu_entry_has_its_icon(self):
        found = 0
        for workspace in import_string(settings.RAIL_MENU):
            for section in workspace.sections:
                for group in section.groups:
                    for entry in group.entries:
                        with self.subTest(entry=str(entry.label)):
                            self.assertIconExists(entry.icon, f'menu entry {entry.label}')
                            found += 1
        self.assertGreater(found, 20)

    def test_every_tab_has_its_icon(self):
        for tab in Resource.registry:
            with self.subTest(tab=tab.model.__name__):
                self.assertIconExists(tab.icon, f'tab {tab.model.__name__}')

    def test_the_icons_the_monitoring_page_draws_exist(self):
        for name in ('monitor', 'maximize', 'x'):
            with self.subTest(icon=name):
                self.assertIconExists(name, name)
