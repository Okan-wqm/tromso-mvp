from django.urls import path

from core.crud import Resource

from . import views

app_name = 'inventory'

# The storage location tab's routes come from its Resource (core.crud); the Storage page and its dialogs live
# under its menu entry's address, so the menu marks Storage while a dialog is open as a page.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('operations/storage/', views.storage, name='storage'),
    path('operations/storage/receive/', views.receive, name='receive'),
    *(path(f'operations/storage/{kind.replace("_", "-")}/', views.departure, {'kind': kind}, name=kind)
      for kind in views.DEPARTURES),
    path('operations/storage/count/', views.count, name='count'),
    path('operations/storage/void/<uuid:pk>/', views.void, name='void'),
    path('operations/storage/items/<uuid:pk>/', views.item_page, name='item'),
    path('operations/storage/lots/<uuid:pk>/', views.lot_page, name='lot'),
]
