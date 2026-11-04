from django.urls import path

from core.crud import Resource

from . import views

app_name = 'reports'

# The report tab's routes come from its Resource (core.crud); recording a filing, starting a correction, the exports
# and the print page live under the same address.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('reports/<uuid:pk>/submit/', views.submit, name='report_submit'),
    path('reports/<uuid:pk>/correct/', views.correct, name='report_correct'),
    path('reports/<uuid:pk>/export.<str:fmt>', views.export, name='report_export'),
    path('reports/<uuid:pk>/print/', views.print_page, name='report_print'),
    path('reports/close/', views.close, name='due_close'),
    path('reports/duties/', views.outside_duties, name='outside_duties'),
    path('reports/duties/done/', views.duty_done, name='duty_done'),
    path('reports/duties/done/<uuid:pk>/undo/', views.duty_undo, name='duty_undo'),
    path('reports/closed/<uuid:pk>/reopen/', views.reopen, name='due_reopen'),
]
