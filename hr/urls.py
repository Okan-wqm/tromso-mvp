from django.urls import path

from core.crud import Resource

from . import views

app_name = 'hr'

# The tabs' routes come from the tabs (core.crud.Resource); the HR pages that are not a tab (the roster's batch plan, later
# Today and the organisation chart) have routes of their own below.
urlpatterns = [route for tab in Resource.registry if tab.model._meta.app_label == app_name for route in tab.urls()]
urlpatterns += [
    path('hr/schedule/plan/', views.plan, name='roster_plan'),
]
