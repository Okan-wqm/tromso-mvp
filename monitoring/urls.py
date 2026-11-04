from django.urls import path

from core.crud import Resource

from . import views

app_name = 'monitoring'

# The boards' routes come from their tab (core.crud.Resource): list, form, delete and the cards' list.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('operations/monitoring/', views.monitor, name='monitor'),
    path('operations/monitoring/cards/', views.cards, name='cards'),
]
