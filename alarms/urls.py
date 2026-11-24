from django.urls import path

from core.crud import Resource

from . import views

app_name = 'alarms'

# The recipient rules are a tab (core.crud.Resource); the alarms themselves are a read page with its acknowledgement.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('alarms/', views.alarm_list, name='alarm_list'),
    path('alarms/<int:pk>/', views.alarm_detail, name='alarm_detail'),
    path('alarms/<int:pk>/acknowledge/', views.alarm_acknowledge, name='alarm_acknowledge'),
    path('alarms/<int:pk>/snooze/', views.alarm_snooze, name='alarm_snooze'),
    path('alarms/<int:pk>/snooze/end/', views.alarm_snooze_end, name='alarm_snooze_end'),
    path('alarms/snoozes/', views.alarm_snoozes, name='alarm_snoozes'),
    path('alarms/watch/', views.alarm_watch_notice, name='alarm_watch_notice'),
]
