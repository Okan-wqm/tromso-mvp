from django.urls import path

from core.crud import Resource

from .stock import views as stock

app_name = 'farm'

# The tabs' routes come from the tabs (core.crud.Resource): their list, form and delete pages and their
# row lists. Operations › Production units is a read page with operation dialogs, not a tab: its routes
# are here, all under its menu entry's address so the menu marks it while a dialog is open as a page.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('operations/units/', stock.production_units, name='production_units'),
    path('operations/units/new-batch/', stock.stock_input, name='stock_input'),
    *(path(f'operations/units/<uuid:pk>/{kind}/', stock.record_operation, {'kind': kind}, name=f'stock_{kind}')
      for kind in stock.OPERATIONS),
    path('operations/units/void/<uuid:pk>/', stock.void_operation, name='stock_void'),
]
