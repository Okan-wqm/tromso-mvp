from django.urls import path

from core.crud import Resource

from . import views

app_name = 'sensors'

# The configuration tabs' routes come from their Resource (core.crud): list, form, delete and their row lists.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('sensors/', views.home, name='home'),
    path('sensors/credentials/<uuid:pk>/rotate/', views.credential_rotate, name='credential_rotate'),
]
