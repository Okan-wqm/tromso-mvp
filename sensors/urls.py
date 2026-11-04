from django.urls import path

from core.crud import Resource

from . import views

app_name = 'sensors'

# The configuration tabs' routes come from their Resource (core.crud): list, form, delete and their row lists.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('sensors/', views.home, name='home'),
    path('sensors/credentials/<uuid:pk>/rotate/', views.credential_rotate, name='credential_rotate'),
    path('sensors/charts/', views.charts, name='charts'),
    path('sensors/charts/csv/', views.chart_csv, name='chart_csv'),
    path('sensors/charts/place/', views.target_charts, name='target_charts'),
    path('sensors/live/', views.live, name='live'),
    path('sensors/dead-letters/', views.dead_letters, name='dead_letters'),
    path('sensors/alarm-events/', views.alarm_events, name='alarm_events'),
    path('sensors/alarm-events/<int:pk>/acknowledge/', views.alarm_event_acknowledge, name='alarm_event_acknowledge'),
    path('sensors/dead-letters/<int:pk>/resolve/', views.dead_letter_resolve, name='dead_letter_resolve'),
    path('sensors/charts/trail/', views.trail_points, name='trail'),
]
