from django.urls import path

from core.crud import Resource

from .feeding import views as feeding
from .health import views as health
from .stock import views as stock
from .water import views as water

app_name = 'farm'

# The tabs' routes come from the tabs (core.crud.Resource): their list, form and delete pages and their
# row lists. Operations › Production units, Feeding records, Water chemistry, Treatments and Sea-lice counts are
# read pages with dialogs, not tabs: their routes are here, each under its menu entry's address so the menu
# marks it while a dialog is open as a page (a unit's feeding dialog belongs to Production units, where its
# drawer offers it). A health event is a tab; its void is here, under the tab's address.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('operations/units/', stock.production_units, name='production_units'),
    path('operations/units/new-batch/', stock.stock_input, name='stock_input'),
    *(path(f'operations/units/<uuid:pk>/{kind}/', stock.record_operation, {'kind': kind}, name=f'stock_{kind}')
      for kind in stock.OPERATIONS),
    path('operations/units/void/<uuid:pk>/', stock.void_operation, name='stock_void'),
    path('operations/units/<uuid:pk>/feeding/', feeding.record_feeding, name='feeding_record'),
    path('operations/feeding/', feeding.feeding_records, name='feeding_records'),
    path('operations/feeding/new/', feeding.choose_unit, name='feeding_new'),
    path('operations/feeding/void/<uuid:pk>/', feeding.void_feeding, name='feeding_void'),
    path('operations/water/', water.water_page, name='water'),
    path('operations/water/record/', water.record_sample, name='water_record'),
    path('operations/water/round/', water.record_round, name='water_round'),
    path('operations/water/void/<uuid:pk>/', water.void_sample, name='water_void'),
    path('operations/health/treatments/', health.treatments, name='treatments'),
    path('operations/health/treatments/new/', health.record_treatment, name='treatment_record'),
    path('operations/health/treatments/<uuid:pk>/last-day/', health.change_last_day, name='treatment_last_day'),
    path('operations/health/treatments/<uuid:pk>/void/', health.void_treatment, name='treatment_void'),
    path('operations/health/events/<uuid:pk>/void/', health.void_event, name='healthevent_void'),
    path('operations/health/lice/', health.lice_counts, name='lice_counts'),
    path('operations/health/lice/new/', health.record_lice_count, name='lice_record'),
    path('operations/health/lice/<uuid:pk>/void/', health.void_lice_count, name='lice_void'),
]
