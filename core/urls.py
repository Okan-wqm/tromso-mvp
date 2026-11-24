from django.urls import path

from . import dbview, theme, ui, views
from .resources import PlatformSettingsResource, RoleResource, UserResource

app_name = 'core'

urlpatterns = [
    path('language/', views.set_language, name='set_language'),
    path('theme/', theme.set_theme, name='set_theme'),
    path('ui/strip/alarms/', ui.strip_alarms, name='ui_strip_alarms'),
    path('activity/', views.activity_log, name='activity_log'),
    path('database/', dbview.overview, name='database'),
    path('database/<slug:name>/', dbview.browse, name='database_table'),
    path('database/<slug:name>/export.csv', dbview.export, name='database_export'),
    *RoleResource.urls(),
    *UserResource.urls(),
    *PlatformSettingsResource.urls(),
]
