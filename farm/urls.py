from django.urls import path

from core.crud import Resource

from . import views

app_name = 'farm'

urlpatterns = [
    *(route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()),
    path('sites/<uuid:pk>/contacts/', views.site_contacts, name='site_contacts'),
]
