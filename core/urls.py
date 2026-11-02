from django.urls import path

from . import views
from .resources import RoleResource, UserResource

app_name = 'core'

urlpatterns = [
    path('activity/', views.activity_log, name='activity_log'),
    *RoleResource.urls(),
    *UserResource.urls(),
]
