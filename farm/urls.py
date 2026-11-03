from django.urls import path

from core.crud import Resource

from .feeding import views as feeding
from .stock import views as stock
from .water import views as water

app_name = 'farm'

# The tabs' routes come from the tabs (core.crud.Resource): their list, form and delete pages and their
# row lists (Feeding › Protocols and Assignments are tabs, under /operations/feeding/). Operations › Production
# units, Feeding › Meal board and Records, and Water chemistry are read pages with dialogs, not tabs: their routes
# are here, each under its menu entry's address so the menu marks it while a dialog is open as a page (a unit's
# feeding dialog belongs to Production units, where its drawer offers it).
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('operations/units/', stock.production_units, name='production_units'),
    path('operations/units/new-batch/', stock.stock_input, name='stock_input'),
    *(path(f'operations/units/<uuid:pk>/{kind}/', stock.record_operation, {'kind': kind}, name=f'stock_{kind}')
      for kind in stock.OPERATIONS),
    path('operations/units/void/<uuid:pk>/', stock.void_operation, name='stock_void'),
    path('operations/units/<uuid:pk>/feeding/', feeding.record_feeding, name='feeding_record'),
    path('operations/feeding/', feeding.feeding_records, name='feeding_records'),
    path('operations/feeding/board/', feeding.meal_board, name='meal_board'),
    path('operations/feeding/new/', feeding.choose_unit, name='feeding_new'),
    path('operations/feeding/void/<uuid:pk>/', feeding.void_feeding, name='feeding_void'),
    path('operations/water/', water.water_page, name='water'),
    path('operations/water/calculator/', water.calculator, name='water_calculator'),
    path('operations/water/record/', water.record_sample, name='water_record'),
    path('operations/water/round/', water.record_round, name='water_round'),
    path('operations/water/void/<uuid:pk>/', water.void_sample, name='water_void'),
]
