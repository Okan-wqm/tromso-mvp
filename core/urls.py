from django.urls import path

from . import dbview, views
from .resources import RoleResource, UserResource

app_name = 'core'

urlpatterns = [
    path('language/', views.set_language, name='set_language'),
    path('activity/', views.activity_log, name='activity_log'),
    path('database/', dbview.overview, name='database'),
    path('database/<slug:name>/', dbview.browse, name='database_table'),
    path('database/<slug:name>/export.csv', dbview.export, name='database_export'),
    *RoleResource.urls(),
    *UserResource.urls(),
]
